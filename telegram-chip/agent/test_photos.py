import ast
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import test_bridge as helpers
from bridge import Chip, CodexChat, PHOTO_FAILURE, PHOTO_MAX_BYTES, RESET_REPLY
from media_info import incoming_image_info


def image_message(mid, caption='', stamp=1000, out=False, size=100):
    return {**helpers.message(mid, caption, out, stamp),
            'image': {'kind': 'photo', 'mime_type': 'image/jpeg', 'size': size}}


class VisionModel(helpers.FakeModel):
    def reply_for_contact(self, history, text, channel, uid, summary='', images=None):
        self.calls.append((history, text, channel, uid, summary, images))
        if self.fail:
            raise TimeoutError()
        if images:
            assert all(Path(p).is_file() for p in images)
            return {'reply': 'I can see a black car key.', 'image_description': 'A black key with three buttons; exact car model unknown.'}
        return 'follow-up'


class PhotoTests(unittest.TestCase):
    create_worker = helpers.BridgeTests.create_worker
    feed = helpers.BridgeTests.feed
    status = helpers.BridgeTests.status

    def setUp(self):
        helpers.BridgeTests.setUp(self)
        self.config['photos_enabled_since'] = 0
        self.model = VisionModel()
        self.downloads = []
        def download(chat, mid, destination):
            self.downloads.append((chat, mid, destination))
            destination.write_bytes(b'\xff\xd8\xfftest image')
        self.chip.download_photo = download
        self.worker = self.create_worker()

    def test_photo_without_caption_reaches_vision_and_temp_file_is_removed(self):
        self.feed([image_message(1)])
        self.worker.tick()
        self.assertEqual(self.chip.sent, [(11, 1, 'I can see a black car key.')])
        self.assertEqual(len(self.downloads), 1)
        self.assertFalse(self.downloads[0][2].exists())
        self.assertIn('three buttons', self.worker.history(11)[0]['text'])

    def test_caption_preserved_followup_sees_visual_notes_and_poll_does_not_overwrite_them(self):
        self.feed([image_message(1, 'Can you make a case for this?')])
        self.worker.tick()
        self.worker.tick()
        self.feed([helpers.message(102, 'And what material would work?', stamp=1010)])
        self.worker.tick()
        self.assertIn('Can you make a case', self.model.calls[0][1])
        self.assertIn('three buttons', str(self.model.calls[-1][0]))
        self.assertEqual(len(self.downloads), 1)

    def test_unauthorized_and_outgoing_photo_do_not_download(self):
        self.feed([image_message(1, out=True)], other=[image_message(2)])
        self.worker.tick()
        self.assertEqual(self.downloads, [])
        self.assertEqual(self.chip.sent, [])

    def test_enabling_photos_does_not_reply_to_historical_photos(self):
        self.config['photos_enabled_since'] = 1010
        self.feed([image_message(1, stamp=1000), image_message(2, stamp=1011)])
        self.worker.tick()
        self.assertEqual([(c,m) for c,m,p in self.downloads], [(11,2)])

    def test_reset_erases_image_notes_and_old_photo_cannot_reenter(self):
        self.config['reset_allowed_chat_ids'] = [11]
        self.feed([image_message(1)])
        self.worker.tick()
        self.feed([helpers.message(102, '/reset', stamp=1010)])
        self.worker.tick()
        self.assertEqual(self.worker.db.execute('SELECT count(*) FROM conversation_images').fetchone()[0], 0)
        self.worker = self.create_worker()
        self.feed([image_message(1), helpers.message(102, '/reset', stamp=1010)])
        self.worker.tick()
        self.assertEqual(len(self.downloads), 1)
        self.assertEqual(self.worker.history(11), [])

    def test_oversize_gets_truthful_reply_without_download(self):
        self.feed([image_message(1, size=PHOTO_MAX_BYTES + 1)])
        self.worker.tick()
        self.worker.tick()
        self.assertEqual(self.downloads, [])
        self.assertEqual(self.chip.sent, [(11, 1, PHOTO_FAILURE)])
        self.assertEqual(self.model.calls, [])

    def test_failed_download_retries_then_reports_failure(self):
        self.chip.download_photo = lambda *a: (_ for _ in ()).throw(TimeoutError())
        self.feed([image_message(1)])
        for now in [1000, 1030, 1090, 1091]:
            self.now = now
            self.worker.tick()
        self.assertEqual(self.chip.sent, [(11, 1, PHOTO_FAILURE)])
        self.assertEqual(self.model.calls, [])
        self.assertIn('could not be inspected', self.worker.history(11)[0]['text'])

    def test_restart_after_generation_reuses_saved_reply_without_image_call(self):
        self.feed([image_message(1)])
        self.chip.wrong_sender = True
        with self.assertRaises(RuntimeError):
            self.worker.tick()
        self.worker = self.create_worker()
        self.chip.wrong_sender = False
        self.worker.tick()
        self.assertEqual(len(self.model.calls), 1)
        self.assertEqual(len(self.downloads), 1)

    def test_image_caption_is_not_an_owner_command(self):
        self.config['owner_id'] = 11
        self.config['owner_control_since'] = 0
        self.feed([image_message(1, '/contact whatsapp +12025550123 hello')])
        self.worker.tick()
        self.assertEqual(len(self.model.calls), 1)
        self.assertIn('/contact', self.model.calls[0][1])

    def test_visual_notes_are_isolated_between_chats(self):
        self.config['allowed_chats'] = [{'chat_id': 11}, {'chat_id': 33}]
        self.worker = self.create_worker()
        self.feed([image_message(1)], other=[helpers.message(2, 'hello')])
        self.worker.tick()
        self.assertNotIn('three buttons', str(self.model.calls[-1]))


class PhotoCliTests(unittest.TestCase):
    def test_cli_image_attached_and_json_checked(self):
        with helpers.TemporaryDirectory() as tmp:
            memory = Path(tmp) / 'identity.md'
            memory.write_text('Test identity')
            model = CodexChat({'memory_file': str(memory), 'workspace': tmp, 'model': 'test'})
            output = helpers.CodexTests.output(
                {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps({'reply':'Hello', 'image_description':'A key'})}},
                {'type':'turn.completed'})
            with patch('bridge.subprocess.run', return_value=output) as run:
                result = model.reply([], 'photo', images=[Path(tmp)/'image.jpg'])
                command = run.call_args.args[0]
                self.assertEqual(command[command.index('--image')+1], str(Path(tmp)/'image.jpg'))
                self.assertEqual(result['image_description'], 'A key')
                self.assertIn('untrusted', run.call_args.kwargs['input'])
            output.stdout = output.stdout.replace('image_description', 'missing')
            with patch('bridge.subprocess.run', return_value=output), self.assertRaises(ValueError):
                model.reply([], 'photo', images=[Path(tmp)/'image.jpg'])

    def test_download_rejects_disguised_nonimage(self):
        with helpers.TemporaryDirectory() as tmp:
            image = Path(tmp)/'image.jpg'
            image.write_text('<html>not an image</html>')
            chip = Chip('http://127.0.0.1')
            with patch.object(chip, 'call', return_value=json.dumps({'success':True,'path':str(image),'kind':'document'})):
                from bridge import PhotoUnavailable
                with self.assertRaises(PhotoUnavailable):
                    chip.download_photo(11, 1, image)


class PollPhotoTests(unittest.TestCase):
    def test_poll_includes_captionless_photo_and_image_file_but_not_preview_or_video(self):
        source = Path(__file__).resolve().parent / 'telegram_core.py'
        if not source.exists():
            source = Path(__file__).resolve().parents[1] / 'telegram_core.py'
        tree = ast.parse(source.read_text())
        method = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == 'poll_new_dms')
        env = {'datetime':datetime, 'json':json, 'User':SimpleNamespace,
               'get_sender_name':lambda msg:'Customer', 'format_entity':lambda entity:{'id':11},
               'json_serializer':str}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[])), str(source), 'exec'),env)
        def media(name, **kw):
            return type(name, (), kw)()
        photo = media('MessageMediaPhoto', photo=SimpleNamespace(sizes=[]))
        document = media('MessageMediaDocument', document=SimpleNamespace(mime_type='image/png', size=12, attributes=[]))
        preview = media('MessageMediaWebPage', webpage=SimpleNamespace(photo=SimpleNamespace(sizes=[]), document=None))
        video = media('MessageMediaDocument', document=SimpleNamespace(mime_type='video/mp4',size=12,attributes=[]))
        date = datetime(2026,11,10,tzinfo=timezone.utc)
        messages = [SimpleNamespace(id=i+1,date=date,message='',media=m,out=False) for i,m in enumerate([photo, document, preview, video])]
        async def dialogs(**kw):return [SimpleNamespace(entity=SimpleNamespace(),date=date)]
        async def get_messages(*a,**kw):return messages
        async def wait():pass
        fake = SimpleNamespace(client=SimpleNamespace(get_dialogs=dialogs,get_messages=get_messages),_wait_for_rate_limit=wait)
        result = json.loads(asyncio.run(env['poll_new_dms'](fake,date.timestamp()-1)))
        self.assertEqual([m['msg_id'] for m in result[0]['messages']], [1,2])
        self.assertEqual(result[0]['messages'][1]['image']['mime_type'], 'image/png')


if __name__ == '__main__':
    unittest.main()
