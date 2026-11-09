import json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from natural_broker import NaturalBroker
from server import OWNER
from owner_interpreter import validate
from profiles import get_profile,is_owner

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name);self.calls=[]
        self.interpreter=Mock()
        self.b=NaturalBroker(self.path/'state.db',lambda target,key:self.calls.append(target) or 'receipt',self.interpreter)
        self.auth=patch('natural_broker.is_owner',return_value=True);self.auth.start()
        self.auth2=patch('profiles.is_owner',return_value=True);self.auth2.start()
    def tearDown(self):self.b.db.close();self.auth.stop();self.auth2.stop();self.tmp.cleanup()
    def p(self,mid,text='Write via WhatsApp to +12025550123: Hello',**kw):return {'owner_id':OWNER,'message_id':mid,'text':text,**kw}
    def decision(self):return {'action':'send','channel':'whatsapp','phone':'+12025550123','phone_evidence':'+12025550123','message':'Hello','reply':''}
    def test_nonowner_never_reaches_llm(self):
        with self.assertRaises(PermissionError):self.b.natural(self.p(1,owner_id=5))
        self.interpreter.interpret.assert_not_called();self.assertFalse(self.calls)
    def test_repeat_reuses_decision_and_send_receipt(self):
        self.interpreter.interpret.return_value=self.decision()
        a=self.b.natural(self.p(1));b=self.b.natural(self.p(1))
        self.assertEqual(a,b);self.assertEqual(len(self.calls),1);self.interpreter.interpret.assert_called_once()
    def test_clarification_followup_and_context_clear(self):
        self.interpreter.interpret.side_effect=[{'action':'clarify','reply':'Which channel?'},self.decision(),{'action':'chat','reply':'Hi'}]
        self.b.natural(self.p(1,'Write +12025550123: Hello'));self.assertFalse(self.calls)
        self.b.natural(self.p(2,'WhatsApp'))
        self.assertEqual(self.interpreter.interpret.call_args.args[1],['Write +12025550123: Hello'])
        self.b.natural(self.p(3,'Hi'));self.assertEqual(self.interpreter.interpret.call_args.args[1],[])
    def test_chat_and_cancel_do_not_send(self):
        for i,action in enumerate(['chat','cancel'],1):
            self.interpreter.interpret.return_value={'action':action,'reply':'Okay'};self.b.natural(self.p(i))
        self.assertFalse(self.calls)
    def test_model_failure_never_sends(self):
        self.interpreter.interpret.side_effect=ValueError('bad JSON')
        with self.assertRaises(ValueError):self.b.natural(self.p(1))
        self.assertFalse(self.calls)
    def test_phone_must_have_owner_evidence_and_preserved_digits(self):
        d=self.decision();validate(d,'Write +12025550123',[])
        for text,pending in [('No number',[]),('Hello',['assistant said number'])]:
            with self.assertRaises(ValueError):validate(d,text,pending)
        d['phone']='+12025550124'
        with self.assertRaises(ValueError):validate(d,'Write +12025550123',[])
    def test_profile_binding_and_no_auto_creation(self):
        self.assertEqual(get_profile('telegram',9,self.path)['role'],'contact')
        self.assertFalse((self.path/'telegram/9.json').exists())
        (self.path/'telegram').mkdir();(self.path/'telegram/9.json').write_text(json.dumps({'platform':'telegram','user_id':'8','role':'owner'}))
        with self.assertRaises(ValueError):get_profile('telegram',9,self.path)

if __name__=='__main__':unittest.main()
