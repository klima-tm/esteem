from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
import unittest
from fastapi.testclient import TestClient
from telethon.tl.types import User
import telegram_core as tc
import api

class MarkReadTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.entity=User(id=11,first_name='test')
        self.core=object.__new__(tc.TelegramCore)
        self.core._wait_for_rate_limit=AsyncMock()
        self.core.client=SimpleNamespace(get_entity=AsyncMock(return_value=self.entity),
            get_messages=AsyncMock(return_value=SimpleNamespace(id=7,chat_id=11,out=False)),
            send_read_acknowledge=AsyncMock(return_value=True))
    async def test_explicit_max_id_only(self):
        result=await self.core.mark_read(11,7)
        self.assertEqual(result,{'read_through_message_id':7,'acknowledged':True})
        self.core.client.send_read_acknowledge.assert_awaited_once_with(self.entity,max_id=7)
    async def test_invalid_all_messages_or_foreign_outgoing_message_rejected(self):
        for mid in [0,-1,True,'7']:
            with self.assertRaises(ValueError):await self.core.mark_read(11,mid)
        for msg in [None,SimpleNamespace(id=7,chat_id=33,out=False),SimpleNamespace(id=7,chat_id=11,out=True),SimpleNamespace(id=8,chat_id=11,out=False)]:
            self.core.client.get_messages.return_value=msg
            with self.assertRaises(ValueError):await self.core.mark_read(11,7)
        self.core.client.send_read_acknowledge.assert_not_called()
    async def test_unconfirmed_receipt_is_an_error(self):
        self.core.client.send_read_acknowledge.return_value=False
        with self.assertRaises(RuntimeError):await self.core.mark_read(11,7)
    async def test_http_positive_integer_boundary(self):
        client=TestClient(api.app);handler=AsyncMock(return_value={'read_through_message_id':7,'acknowledged':True})
        with patch.object(api.telegram,'mark_read',handler):
            self.assertEqual(client.post('/chats/11/read',json={'max_id':7}).status_code,200)
            handler.assert_awaited_once_with('11',7)
            for mid in [0,-1,True,'7']:
                self.assertEqual(client.post('/chats/11/read',json={'max_id':mid}).status_code,422)

if __name__=='__main__':unittest.main()
