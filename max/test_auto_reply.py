import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from auto_reply import Replies

class Model:
    def __init__(self): self.calls=[]
    def reply(self,history,text):
        self.calls.append((history,text))
        return 'test reply'
class Client:
    def __init__(self,fail=False):self.sent=[];self.fail=fail
    async def send_message(self,**kwargs):
        self.sent.append(kwargs)
        if self.fail:raise TimeoutError()
        return SimpleNamespace(id=99)

class ReplyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.model=Model()
        self.config={'state_db':str(Path(self.temp.name)/'state.db'),'expected_sender_id':1,
            'allowed_contacts':[{'user_id':2,'chat_id':3},{'user_id':4,'chat_id':5}], 'activated_at':100}
        self.replies=Replies(self.config,self.model)
    def tearDown(self): self.replies.db.close();self.temp.cleanup()
    def message(self,**overrides):
        d=dict(sender=2,chat_id=3,id=8,time=1010000000000,text='hello',type='USER');d.update(overrides)
        return SimpleNamespace(**d)
    async def test_excludes_self_unknown_group_old_and_nontext(self):
        for overrides in [dict(sender=1),dict(sender=7),dict(chat_id=10),dict(time=50),dict(text=''),dict(type='SYSTEM')]:
            await self.replies.capture(self.message(**overrides),None)
        self.assertTrue(self.replies.queue.empty())
    async def test_duplicate_event_replies_once(self):
        msg=self.message();c=Client()
        await self.replies.capture(msg,c);await self.replies.capture(msg,c)
        self.assertEqual(self.replies.queue.qsize(),1)
        await self.replies.process(c,(3,8));await self.replies.process(c,(3,8))
        self.assertEqual(len(c.sent),1)
    async def test_history_isolated_between_chats(self):
        c=Client();await self.replies.capture(self.message(),c);await self.replies.process(c,(3,8))
        await self.replies.capture(self.message(sender=4,chat_id=5,id=9),c)
        await self.replies.process(c,(5,9));self.assertEqual(self.model.calls[1][0],[])
        await self.replies.capture(self.message(id=10),c);await self.replies.process(c,(3,10))
        self.assertEqual([x['role'] for x in self.model.calls[2][0]],['user','assistant'])
    async def test_uncertain_send_not_retried(self):
        c=Client(fail=True);await self.replies.capture(self.message(),c)
        await self.replies.process(c,(3,8));await self.replies.process(c,(3,8))
        self.assertEqual(len(c.sent),1)
        self.assertEqual(self.replies.db.execute('select status from jobs').fetchone()[0],'uncertain')
    async def test_crash_during_send_marks_uncertain_on_restart(self):
        await self.replies.capture(self.message(),None)
        self.replies.db.execute("update jobs set status='sending'");self.replies.db.commit();self.replies.db.close()
        self.replies=Replies(self.config,self.model)
        c=Client();await self.replies.process(c,(3,8));self.assertFalse(c.sent)
    async def test_generation_failure_does_not_send(self):
        def fail(*a):raise ValueError('fake failure')
        self.model.reply=fail
        await self.replies.capture(self.message(),None)
        self.replies.db.execute('update jobs set attempts=2');self.replies.db.commit()
        c=Client();await self.replies.process(c,(3,8));self.assertFalse(c.sent)
        self.assertEqual(self.replies.db.execute('select status from jobs').fetchone()[0],'failed')

if __name__=='__main__':unittest.main()
