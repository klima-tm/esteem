import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'telegram-chip/agent'))
import product_photos as lib
from bridge import CodexChat

class OutgoingVisionTests(unittest.TestCase):
    def test_exact_ordered_files_are_inspected_and_not_treated_as_uploads(self):
        model=CodexChat({})
        photos=[{'path':'/a.jpg','tags':['mats']},{'path':'/b.jpg','tags':['mats','3d']}]
        result={'reply':'Examples','image_description':'Photo 1: flat mat. Photo 2: raised sides.'}
        with patch.object(model,'reply',return_value=result) as reply:
            self.assertEqual(model.inspect_outgoing(photos),result)
        self.assertEqual(reply.call_args.kwargs['images'],['/a.jpg','/b.jpg'])
        self.assertTrue(reply.call_args.kwargs['outgoing_images'])
    def test_numbered_notes_survive_serialization_without_local_paths(self):
        photos=[{'path':'/secret/a.jpg','tags':['mats']},{'path':'/secret/b.jpg','tags':['mats','3d']}]
        envelope=lib.pack_reply('Examples',photos,visual_notes='Photo 1: flat mat. Photo 2: raised sides.')
        restored=lib.history_text(envelope)
        self.assertIn('Photo 1: flat mat',restored)
        self.assertIn('Photo 2: raised sides',restored)
        self.assertNotIn('/secret',restored)


    def test_followup_reopens_same_ordered_files_without_resending(self):
        photos=[{'path':'/cached/1.jpg','tags':['mats']},{'path':'/cached/2.jpg','tags':['mats','3d']}]
        model=CodexChat({'product_photos_enabled':True})
        answers=[{'reply':'draft','photo_tags':[],'review_previous_photos':True},
                 {'reply':'На втором видны высокие борта.','photo_tags':[],'image_description':'Photo 2: raised sides.'}]
        with patch.object(model,'reply',side_effect=answers) as reply,patch.object(lib,'unpack_reply',return_value=('',photos)):
            result=model.reply_for_contact([],'А на втором фото?', 'telegram',0,photo_context={'previous_photos':photos})
        self.assertEqual(result,'На втором видны высокие борта.')
        self.assertEqual(reply.call_count,2)
        self.assertEqual(reply.call_args.kwargs['images'],['/cached/1.jpg','/cached/2.jpg'])
        self.assertTrue(reply.call_args.kwargs['outgoing_images'])
    def test_thanks_does_not_reinspect(self):
        model=CodexChat({'product_photos_enabled':True})
        with patch.object(model,'reply',return_value={'reply':'Пожалуйста!','photo_tags':[]}) as reply:
            result=model.reply_for_contact([],'Спасибо','telegram',0,photo_context={'previous_photos':[{'path':'/cached/1.jpg','tags':['mats']}]})
        self.assertEqual(reply.call_count,1)
    def test_missing_file_does_not_pretend_to_see_photo(self):
        model=CodexChat({'product_photos_enabled':True})
        answers=[{'reply':'draft','photo_tags':[],'review_previous_photos':True},{'reply':'Пришлите фото ещё раз.','photo_tags':[]}]
        with patch.object(model,'reply',side_effect=answers) as reply:
            result=model.reply_for_contact([],'А на втором фото?','telegram',0,photo_context={'previous_photos':[{'path':'/missing/file.jpg','tags':['mats']}]})
        self.assertEqual(result,'Пришлите фото ещё раз.')
        self.assertNotIn('images',reply.call_args.kwargs)
