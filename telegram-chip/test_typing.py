import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
import unittest
from fastapi.testclient import TestClient
import telegram_core as tc
import api

class TypingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.events=[]
        @asynccontextmanager
        async def action(entity,name,**kwargs):
            self.events.append(('start',entity,name,kwargs))
            try:yield
            finally:self.events.append(('stop',entity))
        self.core=object.__new__(tc.TelegramCore)
        self.core._typing_tasks={};self.core._typing_deadlines={}
        self.core._ensure_may_write=AsyncMock()
        self.core.client=SimpleNamespace(get_entity=AsyncMock(side_effect=lambda x:x),action=action)
    async def asyncTearDown(self):
        for chat in list(self.core._typing_tasks):await self.core.set_typing(chat,False)
    async def test_native_typing_refresh_and_explicit_cancel(self):
        await self.core.set_typing(11,True);await asyncio.sleep(0)
        task=self.core._typing_tasks[11]
        await self.core.set_typing(11,True)
        self.assertIs(self.core._typing_tasks[11],task)
        self.assertEqual(self.events,[('start',11,'typing',{'delay':4,'auto_cancel':True})])
        await self.core.set_typing(11,False)
        self.assertEqual(self.events[-1],('stop',11));self.assertFalse(self.core._typing_tasks)
    async def test_expired_lease_cancels_without_a_worker(self):
        await self.core.set_typing(11,True)
        task=self.core._typing_tasks[11]
        self.core._typing_deadlines[11]=asyncio.get_running_loop().time()-1
        await task
        self.assertEqual(self.events[-1],('stop',11));self.assertFalse(self.core._typing_tasks)
    async def test_cancellation_is_chat_scoped(self):
        await self.core.set_typing(11,True);await self.core.set_typing(33,True);await asyncio.sleep(0)
        await self.core.set_typing(11,False)
        self.assertIn(33,self.core._typing_tasks);self.assertNotIn(11,self.core._typing_tasks)
    async def test_first_contact_guard(self):
        self.core._ensure_may_write.side_effect=tc.SendRefusedError('refused')
        with self.assertRaises(tc.SendRefusedError):await self.core.set_typing(11,True)
        self.assertEqual(self.events,[]);self.assertFalse(self.core._typing_tasks)
    async def test_http_contract(self):
        client=TestClient(api.app)
        handler=AsyncMock(return_value={'typing':True,'lease_seconds':20})
        with patch.object(api.telegram,'set_typing',handler):
            result=client.post('/chats/11/typing',json={'active':True})
            self.assertEqual(result.status_code,200);handler.assert_awaited_once_with('11',True)
            self.assertEqual(client.post('/chats/11/typing',json={'active':'yes'}).status_code,422)

if __name__=='__main__':unittest.main()
