"""Exercise the HTTP/native album contract without sending Telegram messages."""
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,patch
from fastapi.testclient import TestClient
import telegram_core as tc
import api

class AlbumTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        base=Path(self.tmp.name)
        folder=base/'photos/state/photo-cache';folder.mkdir(parents=True)
        self.paths=[]
        for i in range(5):
            p=folder/(f'{i:064x}'+'.jpg');p.write_bytes(b'\xff\xd8\xfffixture');self.paths.append(str(p))
        self.filepatch=patch.object(tc,'__file__',str(base/'telegram-chip/telegram_core.py'))
        self.filepatch.start();self.addCleanup(self.filepatch.stop)
        self.core=object.__new__(tc.TelegramCore)
        self.core._check_message_rate_limit=AsyncMock();self.core._wait_for_rate_limit=AsyncMock()
        self.core._ensure_may_write=AsyncMock()
        self.core.client=SimpleNamespace(get_entity=AsyncMock(return_value='customer'),send_file=AsyncMock(
            return_value=[SimpleNamespace(id=10+i,grouped_id=77) for i in range(5)]))
    def test_five_sent_in_one_native_call_with_one_caption(self):
        result=asyncio.run(self.core.send_photo_album(11,self.paths,'Examples',9))
        self.assertEqual(result,{'message_ids':[10,11,12,13,14],'grouped_id':77})
        self.core.client.send_file.assert_awaited_once_with('customer',self.paths,
            caption=['Examples','','','',''],reply_to=9,parse_mode=None,force_document=False)
        self.core._ensure_may_write.assert_awaited_once_with('customer')
    def test_single_remaining_photo(self):
        self.core.client.send_file.return_value=[SimpleNamespace(id=10,grouped_id=None)]
        result=asyncio.run(self.core.send_photo_album(11,self.paths[:1]))
        self.assertEqual(result['message_ids'],[10])
    def test_first_contact_refusal_stops_album(self):
        self.core._ensure_may_write.side_effect=tc.SendRefusedError('refused')
        with self.assertRaises(tc.SendRefusedError):asyncio.run(self.core.send_photo_album(11,self.paths))
        self.core.client.send_file.assert_not_called()
    def test_uncertain_failure_is_not_retried(self):
        self.core.client.send_file.side_effect=TimeoutError()
        with self.assertRaises(TimeoutError):asyncio.run(self.core.send_photo_album(11,self.paths))
        self.core.client.send_file.assert_awaited_once()
    def test_partial_or_ungrouped_result_is_uncertain(self):
        for results in [[SimpleNamespace(id=10,grouped_id=77)],
                        [SimpleNamespace(id=10+i,grouped_id=None) for i in range(5)]]:
            self.core.client.send_file.return_value=results
            with self.assertRaises(RuntimeError):asyncio.run(self.core.send_photo_album(11,self.paths))
    def test_reject_over_limit_duplicate_and_outside_paths(self):
        for paths in [self.paths+[self.paths[0]],self.paths[:1]*2,['/etc/passwd']]:
            with self.assertRaises(ValueError):asyncio.run(self.core.send_photo_album(11,paths))
        self.core.client.send_file.assert_not_called()
    def test_http_schema_and_route(self):
        # No lifespan startup, so no Telegram session is opened.
        client=TestClient(api.app)
        handler=AsyncMock(return_value={'message_ids':[10,11,12,13,14],'grouped_id':77})
        with patch.object(api.telegram,'send_photo_album',handler):
            r=client.post('/messages/send-photo-album',json={'chat_id':11,'file_paths':self.paths,'caption':'Examples','reply_to':9})
            self.assertEqual(r.status_code,200);self.assertTrue(r.json()['success'])
            handler.assert_awaited_once()
            bad=client.post('/messages/send-photo-album',json={'chat_id':11,'file_paths':self.paths+self.paths[:1]})
            self.assertEqual(bad.status_code,422)

if __name__=='__main__':unittest.main()
