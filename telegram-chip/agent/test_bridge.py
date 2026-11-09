import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from datetime import datetime, timezone

from bridge import Bridge, Chip, CodexChat


def message(message_id, text="hello", out=False, stamp=1000):
    return {"msg_id": message_id, "text": text, "out": out,
            "date": datetime.fromtimestamp(stamp, timezone.utc).isoformat()}


class FakeChip:
    def __init__(self):
        self.chats = []
        self.sent = []
        self.send_error = False
        self.wrong_sender = False

    def incoming(self, since):
        return self.chats

    def verify_sender(self, expected):
        if self.wrong_sender:
            raise RuntimeError("wrong sender")

    def send(self, chat, mid, text):
        self.sent.append((chat, mid, text))
        if self.send_error:
            raise TimeoutError()
        return mid + 100


class FakeModel:
    def __init__(self):
        self.calls = []
        self.fail = False

    def reply(self, history, text):
        self.calls.append((history, text))
        if self.fail:
            raise TimeoutError()
        return "reply: " + text


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 1000
        self.config = {"state_db": str(Path(self.temp.name) / "state.db"),
                       "allowed_chat_id": 11, "expected_sender_id": 22}
        self.chip, self.model = FakeChip(), FakeModel()
        self.worker = self.create_worker()

    def create_worker(self):
        worker = Bridge(self.config, self.chip, self.model, clock=lambda: self.now)
        self.addCleanup(worker.db.close)
        return worker

    def feed(self, messages, other=None):
        self.chip.chats = [{"chat_id": 11, "messages": messages}]
        if other:
            self.chip.chats.append({"chat_id": 33, "messages": other})

    def status(self, mid):
        return self.worker.db.execute("SELECT status FROM reply_jobs WHERE message_id=?", (mid,)).fetchone()[0]

    def test_only_fresh_incoming_authorized_text_is_answered(self):
        self.feed([message(1), message(2, out=True), message(3, stamp=900),
                   message(4, text=""), message(5, out=None)], other=[message(6)])
        self.worker.tick()
        self.assertEqual(self.chip.sent, [(11, 1, "reply: hello")])
        self.assertEqual(self.worker.db.execute("SELECT count(*) FROM messages").fetchone()[0], 3)
        self.assertEqual(self.worker.db.execute("SELECT count(*) FROM reply_jobs").fetchone()[0], 1)

    def test_repeat_poll_and_restart_do_not_duplicate(self):
        self.feed([message(1)])
        self.worker.tick()
        self.worker.tick()
        self.worker = self.create_worker()
        self.worker.tick()
        self.assertEqual(len(self.chip.sent), 1)
        self.assertEqual(len(self.model.calls), 1)

    def test_chronological_order_and_history(self):
        self.feed([message(2, "second", stamp=1001), message(1, "first")])
        self.worker.tick()
        self.assertEqual([entry[1] for entry in self.chip.sent], [1, 2])
        self.assertEqual(self.model.calls[1][0], [
            {"role": "user", "text": "first"},
            {"role": "assistant", "text": "reply: first"}])

    def test_generation_retry_waits_and_preserves_order(self):
        self.feed([message(1), message(2, "later", stamp=1001)])
        self.model.fail = True
        self.worker.tick()
        self.model.fail = False
        self.now = 1010
        self.worker.tick()
        self.assertEqual(len(self.model.calls), 1)
        self.assertEqual(self.chip.sent, [])
        self.now = 1030
        self.worker.tick()
        self.assertEqual([entry[1] for entry in self.chip.sent], [1, 2])

    def test_generation_stops_after_three_failures(self):
        self.feed([message(1)])
        self.model.fail = True
        for now in [1000, 1030, 1090, 1200]:
            self.now = now
            self.worker.tick()
        self.assertEqual(len(self.model.calls), 3)
        self.assertEqual(self.status(1), "failed")
        self.assertEqual(self.chip.sent, [])

    def test_uncertain_send_is_not_retried_even_after_restart(self):
        self.feed([message(1)])
        self.chip.send_error = True
        self.worker.tick()
        self.assertEqual(self.status(1), "uncertain")
        self.chip.send_error = False
        self.worker = self.create_worker()
        self.worker.tick()
        self.assertEqual(len(self.chip.sent), 1)

    def test_crash_during_send_is_held_for_manual_check(self):
        self.worker.db.execute("INSERT INTO reply_jobs(chat_id,message_id,date_ts,text,reply,status) VALUES(11,1,1000,'x','y','sending')")
        self.worker.db.commit()
        self.worker = self.create_worker()
        self.worker.tick()
        self.assertEqual(self.status(1), "uncertain")
        self.assertEqual(self.chip.sent, [])

    def test_wrong_sender_blocks_send_and_keeps_generated_reply(self):
        self.feed([message(1)])
        self.chip.wrong_sender = True
        with self.assertRaises(RuntimeError):
            self.worker.tick()
        self.assertEqual(self.status(1), "generated")
        self.assertEqual(self.chip.sent, [])
        self.chip.wrong_sender = False
        self.worker.tick()
        self.assertEqual(len(self.model.calls), 1)
        self.assertEqual(self.status(1), "sent")

    def test_send_payload_never_enables_first_contact(self):
        chip = Chip("http://127.0.0.1")
        with patch.object(chip, "call", return_value="Message sent successfully. Message ID: 9") as call:
            self.assertEqual(chip.send(11, 1, "test"), 9)
        self.assertEqual(call.call_args.args, ("/messages/send", {"chat_id": 11, "message": "test", "reply_to": 1}))

    def test_two_chats_store_both_directions_and_keep_context_separate(self):
        self.config["allowed_chats"] = [{"chat_id": 11, "phone": "+12025550111"},
                                        {"chat_id": 33, "phone": "+12025550133"}]
        self.worker = self.create_worker()
        self.feed([message(1, "first private detail")], other=[message(2, "second private detail")])
        self.worker.tick()
        self.assertEqual([entry[0] for entry in self.chip.sent], [11, 33])
        self.assertEqual(self.model.calls[1][0], [])
        self.assertNotIn("first private detail", json.dumps(self.worker.history(33)))
        self.assertNotIn("second private detail", json.dumps(self.worker.history(11)))
        self.assertEqual(self.worker.db.execute("SELECT count(*) FROM messages").fetchone()[0], 4)
        self.assertEqual(self.worker.db.execute("SELECT count(*) FROM messages_by_user WHERE chat_id=33").fetchone()[0], 2)

    def test_newly_enabled_chat_recovers_its_missed_incoming_message(self):
        self.config["allowed_chats"] = [{"chat_id": 11}, {"chat_id": 33, "activated_at": 950}]
        self.worker = self.create_worker()
        self.feed([], other=[message(9, "missed reply", stamp=980), message(8, "first contact", out=True, stamp=960)])
        self.worker.tick()
        self.assertEqual(self.chip.sent, [(33, 9, "reply: missed reply")])
        self.assertEqual(self.model.calls[0][0], [{"role": "assistant", "text": "first contact"}])

    def test_generation_failure_in_one_chat_does_not_block_another(self):
        self.config["allowed_chats"] = [{"chat_id": 11}, {"chat_id": 33}]
        self.worker = self.create_worker()
        self.feed([message(1, "a")], other=[message(2, "b")])
        with patch.object(self.model, "reply", side_effect=[TimeoutError(), "answer b"]):
            self.worker.tick()
        self.assertEqual(self.chip.sent, [(33, 2, "answer b")])

    def test_same_message_id_in_different_chats_does_not_collide(self):
        self.config["allowed_chats"] = [{"chat_id": 11}, {"chat_id": 33}]
        self.worker = self.create_worker()
        self.feed([message(1, "a")], other=[message(1, "b")])
        self.worker.tick()
        self.assertEqual(len(self.chip.sent), 2)
        self.assertEqual(self.worker.db.execute("SELECT count(*) FROM messages WHERE message_id=1").fetchone()[0], 2)

    def test_backfill_stores_old_outgoing_message_without_sending(self):
        self.worker.capture([{"chat_id": 11, "messages": [message(8, "earlier test", out=True, stamp=900)]}],
                            enqueue=False, include_older=True)
        self.assertEqual(self.worker.db.execute("SELECT text FROM messages").fetchone()[0], "earlier test")
        self.assertEqual(self.chip.sent, [])
        self.assertEqual(self.worker.db.execute("SELECT count(*) FROM reply_jobs").fetchone()[0], 0)

    def test_legacy_database_migrates_without_losing_jobs_or_resending(self):
        path = str(Path(self.temp.name) / "legacy.db")
        old = sqlite3.connect(path)
        old.executescript("""
            CREATE TABLE meta(key TEXT PRIMARY KEY,value REAL NOT NULL);
            INSERT INTO meta VALUES('activated_at',800),('cursor',950);
            CREATE TABLE messages(message_id INTEGER PRIMARY KEY,date_ts REAL,text TEXT,reply TEXT,
                status TEXT,attempts INTEGER,retry_at REAL,reply_id INTEGER,error TEXT);
            INSERT INTO messages VALUES(1,900,'old incoming','old reply','sent',1,20,2,NULL);
            INSERT INTO messages VALUES(3,940,'pending',NULL,'received',2,1100,NULL,'TimeoutError');
        """)
        old.close()
        self.config["state_db"] = path
        self.worker = self.create_worker()
        self.assertEqual(self.worker.history(11), [
            {"role": "user", "text": "old incoming"},
            {"role": "assistant", "text": "old reply"},
            {"role": "user", "text": "pending"}])
        self.assertEqual(self.worker.db.execute("SELECT attempts,retry_at,error FROM reply_jobs WHERE message_id=3").fetchone()[:],
                         (2, 1100, "TimeoutError"))
        self.assertIsNone(self.worker.db.execute("SELECT date_ts FROM messages WHERE message_id=2").fetchone()[0])
        self.worker.tick()
        self.assertEqual(self.chip.sent, [])
        self.assertEqual(self.worker.db.execute("SELECT cursor FROM conversations").fetchone()[0], 950)


class CodexTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.memory = Path(self.temp.name) / "MEMORY.md"
        self.memory.write_text("Ты — ИИ-агент Lionaire Car Atelier, Esteem.Pro.", encoding="utf-8")
        self.model = CodexChat({"workspace": "/tmp/test", "model": "test-model",
                               "memory_file": str(self.memory)})

    @staticmethod
    def output(*events):
        return SimpleNamespace(returncode=0, stdout="\n".join(json.dumps(e) for e in events))

    def test_cli_uses_chatgpt_and_ignores_global_config_and_api_env(self):
        output = self.output({"type": "item.completed", "item": {"type": "agent_message", "text": "Hello"}}, {"type": "turn.completed"})
        with patch.dict("os.environ", {"OPENAI_API_KEY": "do-not-use", "CODEX_API_KEY": "do-not-use"}):
            with patch("bridge.subprocess.run", return_value=output) as run:
                self.assertEqual(self.model.reply([], "Hi"), "Hello")
        args, kwargs = run.call_args
        self.assertIn("--ignore-user-config", args[0])
        self.assertIn('forced_login_method="chatgpt"', args[0])
        self.assertNotIn("OPENAI_API_KEY", kwargs["env"])
        self.assertNotIn("CODEX_API_KEY", kwargs["env"])
        self.assertIn("shell_tool", args[0])

    def test_tool_activity_is_rejected(self):
        output = self.output({"type": "item.started", "item": {"type": "command_execution"}}, {"type": "turn.completed"})
        with patch("bridge.subprocess.run", return_value=output), self.assertRaises(RuntimeError):
            self.model.reply([], "Hi")

    def test_persistent_memory_is_included_and_reloaded_for_each_request(self):
        output = self.output({"type": "item.completed", "item": {"type": "agent_message", "text": "Hello"}}, {"type": "turn.completed"})
        with patch("bridge.subprocess.run", return_value=output) as run:
            self.model.reply([{"role": "user", "text": "Earlier message"}], "Hi")
            first_prompt = run.call_args.kwargs["input"]
            self.assertTrue(first_prompt.startswith(self.memory.read_text(encoding="utf-8")))
            self.assertIn("Earlier message", first_prompt)
            self.assertIn('"latest_message": "Hi"', first_prompt)
            self.memory.write_text("Updated owner-maintained memory", encoding="utf-8")
            self.model.reply([], "Next message")
            next_prompt = run.call_args.kwargs["input"]
            self.assertTrue(next_prompt.startswith("Updated owner-maintained memory"))
            self.assertNotIn("Lionaire", next_prompt)

    def test_missing_or_empty_memory_blocks_model_request(self):
        with patch("bridge.subprocess.run") as run:
            self.memory.write_text(" \n", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                self.model.reply([], "Hi")
            self.memory.unlink()
            with self.assertRaises(FileNotFoundError):
                self.model.reply([], "Hi")
            run.assert_not_called()

    def test_warning_is_allowed_but_failed_or_incomplete_turn_is_not(self):
        warning = {"type": "item.completed", "item": {"type": "error", "message": "code-mode host disabled"}}
        answer = {"type": "item.completed", "item": {"type": "agent_message", "text": "Hello"}}
        with patch("bridge.subprocess.run", return_value=self.output(warning, answer, {"type": "turn.completed"})):
            self.assertEqual(self.model.reply([], "Hi"), "Hello")
        for events in [(answer,), ({"type": "turn.failed"},)]:
            with self.subTest(events=events), patch("bridge.subprocess.run", return_value=self.output(*events)), self.assertRaises(RuntimeError):
                self.model.reply([], "Hi")


if __name__ == "__main__":
    unittest.main()
