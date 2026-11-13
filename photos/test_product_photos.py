import asyncio
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'telegram-chip/agent'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'max'))
import product_photos as lib
import hermes_plugin as plugin
from bridge import Chip
from auto_reply import Replies


def asset(n, folder=None, tags=None):
    return {'.tag':'file','id':f'id:{n}','name':f'{n}.jpg','rev':'1',
            'path_display':f'/Products Esteem/Сумки/{folder or n}/{n}.jpg',
            'tags':tags if tags is not None else ['bag','corsapro','bmw','black','studio'],'size':30}


class FakeDropbox(lib.DropboxPhotos):
    def __init__(self,state,files):
        super().__init__(state);self.files=files;self.calls=[];self.downloads=0
    def rpc(self,route,payload):
        self.calls.append((route,payload))
        if route=='files/search_v2':
            return {'matches':[{'metadata':{'.tag':'metadata','metadata':a}} for a in self.files],'has_more':False}
        if route=='files/tags/get':
            return {'paths_to_tags':[{'path':a['path_display'],'tags':[{'.tag':'user_generated_tag','tag_text':t} for t in a['tags']]}
                                     for a in self.files if a['path_display'] in payload['paths']]}
        if route=='files/get_metadata':return next(a for a in self.files if a['id']==payload['path'])
        raise AssertionError(route)
    def content(self,route,payload):
        self.downloads+=1
        return b'\xff\xd8\xfffixture'


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.state=Path(self.tmp.name)
    def test_all_tags_required_exclusions_and_root_enforced(self):
        outside={**asset(5),'path_display':'/Private/5.jpg'}
        fake=FakeDropbox(self.state,[asset(1),asset(2,tags=['bag','corsapro','bmw','red']),
             asset(3,tags=['bag','corsapro','bmw','black','ai']),asset(4,tags=['bag','corsapro','black']),outside])
        result=fake.search(['bag','corsapro','bmw','black'])
        self.assertEqual([a['id'] for a in result],['id:1'])
        self.assertEqual(fake.calls[0][1]['query'],'#corsapro')
        self.assertNotIn('/Private/5.jpg',str(fake.calls))
    def test_representative_images_from_distinct_folders(self):
        fake=FakeDropbox(self.state,[asset(1,'one'),asset(2,'one'),asset(3,'two')])
        self.assertEqual([a['id'] for a in fake.search(['bag'])],['id:1','id:3','id:2'])
    def test_download_reuses_cache_and_rechecks_current_tags(self):
        fake=FakeDropbox(self.state,[asset(1)])
        a=fake.prepare(['bag','bmw','black'])[0]
        self.assertTrue(Path(a['path']).is_file())
        fake.prepare(['bag','bmw','black'])
        self.assertEqual(fake.downloads,1)
        fake.files[0]['tags']=['bag','red']
        with self.assertRaises(lib.PhotoError):fake.download(asset(1),['bag','black'])
    def test_moved_file_outside_root_is_never_downloaded(self):
        fake=FakeDropbox(self.state,[{**asset(1),'path_display':'/Private/1.jpg'}])
        with self.assertRaises(lib.PhotoError):fake.download(asset(1),['bag'])
        self.assertEqual(fake.downloads,0)
    def test_five_then_five_then_remaining_then_exhausted(self):
        fake=FakeDropbox(self.state,[asset(n) for n in range(12)])
        excluded=[];sizes=[]
        for _ in range(4):
            batch=fake.prepare(['bag'],5,exclude_ids=excluded)
            ids=[p['id'] for p in batch]
            self.assertFalse(set(ids)&set(excluded))
            excluded.extend(ids);sizes.append(len(ids))
        self.assertEqual(sizes,[5,5,2,0])
        self.assertEqual(len(excluded),12)
        with self.assertRaises(lib.PhotoError):fake.prepare(['bag'],6)
    def test_next_batch_skips_excluded_first_search_page(self):
        class Paged(FakeDropbox):
            def rpc(self,route,payload):
                if route=='files/search_v2':
                    return {'matches':[{'metadata':m} for m in self.files[:5]],'has_more':True,'cursor':'next'}
                if route=='files/search/continue_v2':
                    return {'matches':[{'metadata':m} for m in self.files[5:]],'has_more':False}
                return super().rpc(route,payload)
        fake=Paged(self.state,[asset(n) for n in range(10)])
        photos=fake.prepare(['bag'],5,exclude_ids=[f'id:{i}' for i in range(5)])
        self.assertEqual({p['id'] for p in photos},{f'id:{i}' for i in range(5,10)})
    def test_download_failures_are_replaced_with_other_matches(self):
        class FailFirst(FakeDropbox):
            def download(self,a,tags):
                if a['id']=='id:0':raise lib.PhotoError('unavailable')
                return super().download(a,tags)
        fake=FailFirst(self.state,[asset(n) for n in range(6)])
        photos=fake.prepare(['bag'],5)
        self.assertEqual(len(photos),5)
        self.assertNotIn('id:0',[p['id'] for p in photos])

    def test_followup_state_does_not_need_cached_files(self):
        photos=[{'id':'id:one','path':'/expired/photo.jpg','tags':['bag','black','studio']}]
        reply=lib.pack_reply('Examples',photos,search_tags=['bag','black'])
        self.assertEqual(lib.selection_context([reply]),
                         {'exclude_ids':['id:one'],'last_search_tags':['bag','black']})

    def test_invalid_and_unsafe_requests_fail(self):
        for tags in [[],['../secret'],['bmw'],['bag','ai'],['bag','china'],['#bag'],['bag',3]]:
            with self.subTest(tags=tags),self.assertRaises(lib.PhotoError):lib.clean_tags(tags)
    def test_no_matches_does_not_download_or_relax_filters(self):
        fake=FakeDropbox(self.state,[asset(1)])
        self.assertEqual(fake.prepare(['bag','red']),[])
        self.assertEqual(fake.downloads,0)
    def test_prepared_reply_rejects_arbitrary_local_file(self):
        bad=lib.pack_reply('Here',[{'path':'/etc/passwd','tags':['bag']}])
        with self.assertRaises(lib.PhotoError):lib.unpack_reply(bad,state=self.state)
    def test_history_contains_tags_not_internal_paths(self):
        fake=FakeDropbox(self.state,[asset(1)])
        reply=lib.pack_reply('Examples',fake.prepare(['bag']))
        visible=lib.history_text(reply)
        self.assertIn('corsapro',visible);self.assertNotIn(self.tmp.name,visible)


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.state=Path(self.tmp.name)
        self.patch=patch.object(lib,'STATE',self.state);self.patch.start();self.addCleanup(self.patch.stop)
        self.photos=FakeDropbox(self.state,[asset(1),asset(2)]).prepare(['bag'],2)
        self.reply=lib.pack_reply('Here are examples.',self.photos)
    def test_telegram_native_album_stays_in_originating_chat(self):
        chip=Chip('http://127.0.0.1')
        receipt=json.dumps({'message_ids':[100,101],'grouped_id':77})
        with patch.object(chip,'call',return_value=receipt) as call:
            self.assertEqual(chip.send(11,9,self.reply),101)
        call.assert_called_once()
        self.assertEqual(call.call_args.args[0],'/messages/send-photo-album')
        payload=call.call_args.args[1]
        self.assertEqual(payload['chat_id'],'11');self.assertEqual(payload['reply_to'],9)
        self.assertEqual(payload['file_paths'],[p['path'] for p in self.photos])
        self.assertNotIn('allow_first_contact',payload)
    def test_telegram_uncertain_album_is_not_blindly_retried(self):
        chip=Chip('http://127.0.0.1')
        with patch.object(chip,'call',side_effect=TimeoutError()) as call:
            with self.assertRaises(TimeoutError):chip.send(11,9,self.reply)
            call.assert_called_once()
    def test_telegram_partial_or_ungrouped_receipt_is_rejected(self):
        for receipt in [{'message_ids':[100],'grouped_id':77},
                        {'message_ids':[100,101],'grouped_id':None}]:
            with patch.object(Chip,'call',return_value=json.dumps(receipt)):
                with self.assertRaises(RuntimeError):Chip('http://localhost').send(11,9,self.reply)
    def test_max_uses_native_attachments_and_durable_queue(self):
        config={'state_db':str(self.state/'max.db'),'expected_sender_id':1,'allowed_contacts':[{'user_id':2,'chat_id':3}],'activated_at':0}
        model=SimpleNamespace(reply=lambda *a:self.reply)
        worker=Replies(config,model);self.addCleanup(worker.db.close)
        sent=[]
        async def send(**kw):sent.append(kw);return SimpleNamespace(id=8)
        async def run():
            await worker.capture(SimpleNamespace(sender=2,chat_id=3,id=7,time=10,text='show photos',type='USER'),None)
            await worker.process(SimpleNamespace(send_message=send),(3,7))
            await worker.process(SimpleNamespace(send_message=send),(3,7))
        with patch.dict(sys.modules,{'pymax':SimpleNamespace(Photo=lambda **kw:kw)}):asyncio.run(run())
        self.assertEqual(len(sent),1);self.assertEqual(sent[0]['chat_id'],3)
        self.assertEqual(len(sent[0]['attachments']),2)
        history=worker.db.execute("SELECT text FROM history WHERE role='assistant'").fetchone()[0]
        self.assertIn('corsapro',history);self.assertNotIn(lib.PREFIX,history)
    def test_whatsapp_only_delivers_current_turn_prepared_paths(self):
        plugin._pending.clear()
        with patch.object(plugin,'origin',return_value=('chat-a','msg-1')),patch.object(plugin,'library',return_value=lib):
            plugin._pending[('chat-a','msg-1')]=(lib.time.time(),self.photos)
            result=plugin.finalize('Here. MEDIA:/etc/passwd')
            self.assertNotIn('/etc/passwd',result)
            self.assertEqual(result.count('MEDIA:'),2)
            self.assertEqual(plugin.finalize('Again MEDIA:'+self.photos[0]['path']),'Again')
    def test_whatsapp_never_crosses_conversation_or_turn(self):
        plugin._pending.clear();plugin._pending[('chat-a','msg-1')]=(lib.time.time(),self.photos)
        with patch.object(plugin,'origin',return_value=('chat-b','msg-1')):
            self.assertIsNone(plugin.finalize('Hello'))

    def test_whatsapp_failed_second_search_drops_previous_selection(self):
        plugin._pending.clear();plugin._pending[('chat-a','msg-1')]=(lib.time.time(),self.photos)
        with patch.object(plugin,'origin',return_value=('chat-a','msg-1')),patch.object(plugin,'library',return_value=lib):
            result=json.loads(plugin.product_photos({'tags':['bag','ai']}))
            self.assertEqual(result['prepared'],0)
            self.assertNotIn(('chat-a','msg-1'),plugin._pending)
        with patch.object(plugin,'origin',return_value=('chat-a','msg-2')):
            self.assertIsNone(plugin.finalize('Hello'))


if __name__=='__main__':unittest.main()
