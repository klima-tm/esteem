import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'telegram-chip/agent'))
import product_photos as lib
from bridge import Bridge,CodexChat

class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.config={'state_db':str(Path(self.tmp.name)/'chat.db'),'allowed_chat_id':11,
                     'expected_sender_id':22,'product_photos_enabled':True}
        self.model=SimpleNamespace(reply_for_contact=Mock(return_value='reply'))
        self.worker=Bridge(self.config,None,self.model,clock=lambda:1000)
        self.addCleanup(self.worker.db.close)
    def job(self,chat,mid,status,photo):
        self.worker.db.execute('INSERT OR IGNORE INTO conversations(chat_id,activated_at,cursor) VALUES(?,0,0)',(chat,))
        reply=lib.pack_reply('Examples',[{'id':photo,'path':'/expired/photo.jpg','tags':['mats','black']}],search_tags=['mats','black'])
        self.worker.db.execute('INSERT INTO reply_jobs(chat_id,message_id,date_ts,text,reply,status) VALUES(?,?,1000,?,?,?)',
                               (chat,mid,'photos',reply,status));self.worker.db.commit()
    def test_durable_per_chat_history_and_reset(self):
        self.job(11,1,'sent','id:a');self.job(11,2,'uncertain','id:b');self.job(11,3,'generated','id:c')
        self.job(33,1,'sent','id:other')
        restarted=Bridge(self.config,None,self.model,clock=lambda:1001);self.addCleanup(restarted.db.close)
        self.assertEqual(restarted.photo_selection_context(11,4),
                         {'exclude_ids':['id:a','id:b'],'last_search_tags':['mats','black']})
        restarted.reset_conversation(11,4,1002)
        self.assertEqual(restarted.photo_selection_context(11,5)['exclude_ids'],[])
        self.assertEqual(restarted.photo_selection_context(33,5)['exclude_ids'],['id:other'])
    def test_worker_passes_persisted_selection_to_model(self):
        self.job(11,1,'sent','id:a')
        self.worker.generate_reply({'chat_id':11,'message_id':2,'text':'More please'})
        self.assertEqual(self.model.reply_for_contact.call_args.kwargs['photo_context']['exclude_ids'],['id:a'])
    def test_model_requests_five_and_keeps_exact_search_tags(self):
        model=CodexChat({'product_photos_enabled':True})
        tags=['mats','mercedes','gclass','black']
        photos=[{'id':'id:new','path':'/cached.jpg','tags':tags+['2d']}]
        context={'exclude_ids':['id:old'],'last_search_tags':tags}
        with patch.object(model,'reply',return_value={'reply':'More examples','photo_tags':tags}) as reply,patch.object(model,'inspect_outgoing',return_value={'reply':'Examples','image_description':'Photo 1: black mat with raised sides.'}) as inspect,patch.object(lib.DropboxPhotos,'prepare',return_value=photos) as prepare:
            result=model.reply_for_contact([],'More please','telegram',0,photo_context=context)
        prepare.assert_called_once_with(tags,5,exclude_ids=['id:old'])
        inspect.assert_called_once()
        self.assertIn('Photo 1: black mat',lib.history_text(result))
        self.assertIn(json.dumps(tags),reply.call_args.kwargs['tool_result'])
        self.assertEqual(json.loads(result[len(lib.PREFIX):])['search_tags'],tags)
    def test_exhausted_search_uses_truthful_fallback(self):
        model=CodexChat({'product_photos_enabled':True})
        with patch.object(model,'reply',side_effect=[{'reply':'Examples','photo_tags':['mats']},'No more matching photos.']) as reply,patch.object(lib.DropboxPhotos,'prepare',return_value=[]):
            result=model.reply_for_contact([],'More','telegram',0,photo_context={'exclude_ids':['id:old']})
        self.assertEqual(result,'No more matching photos.')
        self.assertIn('previously selected images were excluded',reply.call_args.kwargs['tool_result'])

if __name__=='__main__':unittest.main()
