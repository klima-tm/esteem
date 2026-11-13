import asyncio
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from auto_reply import Replies

class MaxHandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.model=SimpleNamespace(reply=Mock(return_value='New answer'))
        cfg={'state_db':str(Path(self.tmp.name)/'max.db'),'expected_sender_id':1,'allowed_contacts':[{'user_id':2,'chat_id':3}],'activated_at':0,'handoff_enabled':True}
        self.w=Replies(cfg,self.model);self.addCleanup(self.w.db.close)
        self.control=Mock();self.control.state.return_value={'allowed':False,'ack_source':None}
        self.control.call.return_value={'allowed':True,'token':'lease'}
        self.w.handoff=lambda:self.control
        self.sent=[]
        async def send(**kw):self.sent.append(kw);return SimpleNamespace(id=100)
        self.client=SimpleNamespace(send_message=send)
    def msg(self,sender,mid,text):return SimpleNamespace(sender=sender,chat_id=3,id=mid,time=mid,text=text,type='USER')
    def test_paused_messages_and_human_responses_are_saved(self):
        async def run():
            await self.w.capture(self.msg(2,10,'Customer question'),self.client)
            await self.w.capture(self.msg(1,11,'Human response'),self.client)
            await self.w.process(self.client,(3,10))
        asyncio.run(run())
        self.assertEqual(self.sent,[]);self.model.reply.assert_not_called()
        self.assertEqual(self.w.db.execute('SELECT count(*) FROM history').fetchone()[0],2)
    def test_resume_answers_next_message_using_human_history(self):
        async def run():
            await self.w.capture(self.msg(2,10,'Old question'),self.client)
            await self.w.capture(self.msg(1,11,'Human response'),self.client)
            await self.w.process(self.client,(3,10))
            self.control.state.return_value={'allowed':True,'ack_source':None}
            await self.w.capture(self.msg(2,12,'New question'),self.client)
            await self.w.process(self.client,(3,12))
        asyncio.run(run())
        self.assertEqual(len(self.sent),1)
        history=self.model.reply.call_args.args[0]
        self.assertTrue(any(r['text']=='Human response' for r in history))
