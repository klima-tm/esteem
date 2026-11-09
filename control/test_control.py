import tempfile,unittest,json
from pathlib import Path
from server import Broker,OWNER,parse

class ControlTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.calls=[]
        def send(target,key):self.calls.append((target,key));return 'receipt-1'
        self.broker=Broker(Path(self.temp.name)/'requests.db',send)
    def tearDown(self):self.broker.db.close();self.temp.cleanup()
    def payload(self,**changes):
        p={'owner_id':OWNER,'message_id':1,'text':'/contact whatsapp +12025550123 Hello'};p.update(changes);return p
    def test_owner_only(self):
        with self.assertRaises(PermissionError):self.broker.request(self.payload(owner_id=4))
        self.assertFalse(self.calls)
    def test_exact_text_and_channel(self):
        self.assertEqual(parse('/contact MAX +12025550123 Привет!\nВторая строка'),{'channel':'max','phone':'+12025550123','message':'Привет!\nВторая строка'})
        self.assertIsNone(parse('hello'))
    def test_ambiguous_or_incomplete_commands_do_not_send(self):
        for text in ['/contact','/contact sms +12025550123 hi','/contact whatsapp +12025550123','/contact whatsapp 12025550123 hi','/contact whatsapp +123 hi']:
            with self.assertRaises(ValueError):self.broker.request(self.payload(text=text))
        self.assertFalse(self.calls)
    def test_same_request_sent_once(self):
        a=self.broker.request(self.payload());b=self.broker.request(self.payload())
        self.assertEqual(a,b);self.assertEqual(len(self.calls),1)
    def test_request_key_cannot_be_reused_with_different_content(self):
        self.broker.request(self.payload())
        with self.assertRaises(ValueError):self.broker.request(self.payload(text='/contact max +12025550123 Different'))
        self.assertEqual(len(self.calls),1)
    def test_uncertain_outcome_blocks_repeat_even_after_restart(self):
        def fail(*a):raise TimeoutError()
        self.broker.send=fail;self.broker.request(self.payload());self.broker.db.close()
        self.broker=Broker(Path(self.temp.name)/'requests.db',lambda *a:self.fail('must not send'))
        r=self.broker.request(self.payload());self.assertIn('не подтверждена',r['reply'])
    def test_crash_after_start_does_not_resend(self):
        target=parse(self.payload()['text']);key=f'telegram:{OWNER}:1'
        self.broker.db.execute('INSERT INTO requests VALUES (?,?,?,?)',(key,json.dumps(target,sort_keys=True,ensure_ascii=False),'sending',None));self.broker.db.commit();self.broker.db.close()
        self.broker=Broker(Path(self.temp.name)/'requests.db',lambda *a:self.fail('must not send'))
        self.assertIn('неизвестен',self.broker.request(self.payload())['reply'])

if __name__=='__main__':unittest.main()
