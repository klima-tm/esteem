import unittest
import test_bridge as helpers
from test_bridge import message
from bridge import RESET_REPLY


class ResetTests(unittest.TestCase):
    create_worker = helpers.BridgeTests.create_worker
    feed = helpers.BridgeTests.feed
    status = helpers.BridgeTests.status

    def setUp(self):
        helpers.BridgeTests.setUp(self)
        self.config['allowed_chats'] = [{'chat_id': 11}, {'chat_id': 33}]
        self.config['reset_allowed_chat_ids'] = [11]
        self.worker = self.create_worker()

    def seed_memory(self):
        self.worker.db.executescript('''
            CREATE TABLE conversation_memory(chat_id TEXT PRIMARY KEY,summary TEXT,through_message_id INTEGER,updated_at REAL);
            CREATE TABLE conversation_memory_items(chat_id TEXT,cursor INTEGER,PRIMARY KEY(chat_id,cursor));
            INSERT INTO conversation_memory VALUES ('11','private old facts',1,1000),('33','other facts',2,1000);
            INSERT INTO conversation_memory_items VALUES ('11',1),('33',2);
        ''')
        self.worker.db.commit()

    def test_reset_clears_summaries_pending_jobs_and_preserves_other_chat(self):
        self.seed_memory()
        self.feed([message(1, 'old detail')], other=[message(2, 'other detail')])
        self.worker.capture(self.chip.chats)
        self.now = 1010
        self.feed([message(3, '/reset', stamp=1010), message(4, 'fresh start', stamp=1010)])
        self.worker.tick()
        self.assertEqual(self.chip.sent, [(33,2,'reply: other detail'), (11,3,RESET_REPLY), (11,4,'reply: fresh start')])
        self.assertEqual(self.model.calls[-1], ([], 'fresh start'))
        self.assertEqual([r[0] for r in self.worker.db.execute('SELECT chat_id FROM conversation_memory')], ['33'])
        self.assertEqual([r[0] for r in self.worker.db.execute('SELECT chat_id FROM conversation_memory_items')], ['33'])
        self.assertIsNone(self.worker.db.execute('SELECT 1 FROM reply_jobs WHERE chat_id=11 AND message_id=1').fetchone())

    def test_restart_and_backfill_cannot_restore_old_history_or_repeat_reset(self):
        self.feed([message(1, 'old'), message(2, '/reset', stamp=1001)])
        self.worker.tick()
        self.worker = self.create_worker()
        self.worker.tick()
        self.worker.capture(self.chip.chats, enqueue=False, include_older=True)
        self.assertEqual(self.chip.sent, [(11,2,RESET_REPLY)])
        self.assertEqual(self.worker.history(11), [])
        self.feed([message(102, RESET_REPLY, out=True, stamp=1002), message(103, 'new', stamp=1003)])
        self.worker.tick()
        self.assertEqual(self.model.calls[-1], ([], 'new'))

    def test_unauthorized_account_cannot_reset_itself_or_another_chat(self):
        self.seed_memory()
        self.feed([], other=[message(1, '/reset')])
        self.worker.tick()
        self.assertEqual(self.worker.db.execute('SELECT COUNT(*) FROM conversation_memory').fetchone()[0], 2)
        self.assertEqual(self.worker.db.execute('SELECT COUNT(*) FROM conversation_resets').fetchone()[0], 0)
        self.assertEqual(self.model.calls, [])
        self.assertIn('не разрешён', self.chip.sent[0][2])

    def test_quoted_or_outgoing_command_does_not_reset(self):
        self.seed_memory()
        self.feed([message(1, 'please say /reset'), message(2, '/reset', out=True)])
        self.worker.tick()
        self.assertEqual(self.worker.db.execute('SELECT COUNT(*) FROM conversation_resets').fetchone()[0], 0)

    def test_uncertain_ack_does_not_repeat_reset_or_send_after_restart(self):
        self.feed([message(1, '/reset')])
        self.chip.send_error = True
        self.worker.tick()
        self.assertEqual(self.status(1), 'uncertain')
        self.chip.send_error = False
        self.worker = self.create_worker()
        self.worker.tick()
        self.assertEqual(len(self.chip.sent), 1)
        self.assertEqual(self.worker.history(11), [])

    def test_manual_reset_fences_unseen_old_messages_and_preserves_new_ones(self):
        self.seed_memory()
        self.feed([message(1, 'old')], other=[message(2, 'other')])
        self.worker.capture(self.chip.chats)
        self.worker.reset_conversation(11, 1, 1010)
        self.feed([message(3, 'unseen old', stamp=1009), message(4, 'new', stamp=1011)])
        self.worker.tick()
        self.assertEqual(self.model.calls[-1], ([], 'new'))
        self.assertNotIn(RESET_REPLY, [s[2] for s in self.chip.sent])

    def test_multiple_resets_in_one_poll_only_acknowledge_latest(self):
        self.feed([message(1, '/reset'), message(2, 'between', stamp=1001),
                   message(3, '/reset', stamp=1002), message(4, 'after', stamp=1003)])
        self.worker.tick()
        self.assertEqual(self.chip.sent, [(11,3,RESET_REPLY), (11,4,'reply: after')])
        self.assertEqual(self.model.calls, [([], 'after')])


if __name__ == '__main__':
    unittest.main()
