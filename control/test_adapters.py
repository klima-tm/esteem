import importlib.util,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import server

class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
        (self.base/'telegram-chip/agent').mkdir(parents=True)
        self.cfg=self.base/'telegram-chip/agent/config.json'
        self.cfg.write_text(json.dumps({'expected_sender_id':7,'allowed_chats':[]}))
        self.target={'channel':'telegram','phone':'+12025550123','message':'Exact text'}
    def tearDown(self):self.temp.cleanup()
    def test_telegram_verifies_sender_resolves_and_enables_replies(self):
        with patch.object(server,'BASE',self.base),patch.object(server,'chip',side_effect=['{"id":7}',"Contact added successfully: {'id': 19}",'Message sent successfully. Message ID: 32']) as api:
            self.assertEqual(server.send(self.target,'key'),'32')
            self.assertEqual(api.call_args.args[1]['allow_first_contact'],True)
            self.assertEqual(api.call_args.args[1]['message'],'Exact text')
        self.assertEqual(json.loads(self.cfg.read_text())['allowed_chats'][0]['chat_id'],19)
    def test_wrong_telegram_sender_blocks_send(self):
        with patch.object(server,'BASE',self.base),patch.object(server,'chip',return_value='{"id":8}') as api:
            with self.assertRaises(RuntimeError):server.send(self.target,'key')
            self.assertEqual(api.call_count,1)
    def test_missing_telegram_number_blocks_send(self):
        with patch.object(server,'BASE',self.base),patch.object(server,'chip',side_effect=['{"id":7}','Contact added but user not found on Telegram.']) as api:
            with self.assertRaises(ValueError):server.send(self.target,'key')
            self.assertEqual(api.call_count,2)
    def test_whatsapp_permission_before_send_and_exact_recipient(self):
        (self.base/'hermes').mkdir();(self.base/'hermes/.env').write_text('WHATSAPP_ALLOWED_USERS=111\n')
        target={**self.target,'channel':'whatsapp'}
        with patch.object(server,'BASE',self.base),patch.object(server.subprocess,'run') as restart,patch.object(server,'call',side_effect=[{'status':'connected'},{'success':True,'messageId':'wa1'}]) as api:
            self.assertEqual(server.send(target,'key'),'wa1')
            restart.assert_called_once()
            self.assertEqual(api.call_args.args[1],{'chatId':'12025550123@s.whatsapp.net','message':'Exact text'})
        self.assertIn('12025550123',(self.base/'hermes/.env').read_text())

if __name__=='__main__':unittest.main()
