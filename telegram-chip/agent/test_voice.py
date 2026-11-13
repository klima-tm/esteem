import ast,asyncio,io,json,sys,unittest
from pathlib import Path
from datetime import datetime,timezone
from types import SimpleNamespace
from unittest.mock import patch
import test_bridge as helpers
from test_bridge import message
from bridge import Chip,VoiceUnavailable,VOICE_FAILURE,VOICE_MAX_BYTES
import voice_transcription as vt
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from media_info import incoming_voice_info

def voice(mid,caption='',stamp=1000,out=False,size=100):
    return {**message(mid,caption,out,stamp),'voice':{'kind':'voice','mime_type':'audio/ogg','size':size,'duration':8}}

class VoiceTests(unittest.TestCase):
    create_worker=helpers.BridgeTests.create_worker
    feed=helpers.BridgeTests.feed
    status=helpers.BridgeTests.status
    def setUp(self):
        helpers.BridgeTests.setUp(self)
        self.config.update(voice_enabled_since=0,transcription_key_file='/not-used')
        self.downloads=[]
        def download(chat,mid,path):self.downloads.append(path);path.write_bytes(b'OggSfixture')
        self.chip.download_voice=download
        self.transcription=patch('bridge.transcribe',return_value='Мне нужны чёрные коврики для BMW X7.')
        self.transcribe=self.transcription.start();self.addCleanup(self.transcription.stop)
    def test_captionless_voice_transcribed_remembered_and_temporary_audio_removed(self):
        self.feed([voice(1)]);self.worker.tick();self.worker.tick()
        self.assertEqual(len(self.chip.sent),1);self.transcribe.assert_called_once()
        self.assertIn('BMW X7',self.model.calls[0][1]);self.assertFalse(self.downloads[0].exists())
        self.assertIn('BMW X7',self.worker.history(11)[0]['text'])
    def test_caption_and_transcript_survive_repoll_and_model_retry(self):
        self.feed([voice(1,'Посмотри, пожалуйста')]);self.model.fail=True;self.worker.tick()
        self.model.fail=False;self.now=1030;self.worker.tick()
        self.transcribe.assert_called_once();self.assertIn('Посмотри',self.model.calls[-1][1])
        self.feed([message(102,'А какой материал?',stamp=1040)]);self.worker.tick()
        self.assertIn('BMW X7',str(self.model.calls[-1][0]))
    def test_outgoing_unauthorized_and_old_voice_are_not_processed(self):
        self.config['voice_enabled_since']=1010
        self.feed([voice(1),voice(2,stamp=1011,out=True)],other=[voice(3,stamp=1011)])
        self.worker.tick();self.assertEqual(self.chip.sent,[]);self.transcribe.assert_not_called()
    def test_reset_clears_transcript_and_backfill_cannot_restore_it(self):
        self.config['reset_allowed_chat_ids']=[11]
        self.feed([voice(1)]);self.worker.tick()
        self.feed([message(102,'/reset',stamp=1010)]);self.worker.tick()
        self.assertEqual(self.worker.db.execute('SELECT count(*) FROM conversation_audio').fetchone()[0],0)
        self.worker.capture([{'chat_id':11,'messages':[voice(1)]}],include_older=True)
        self.assertEqual(self.worker.db.execute('SELECT count(*) FROM conversation_audio').fetchone()[0],0)
    def test_transcription_failure_has_truthful_fallback_and_no_model_call(self):
        self.transcribe.side_effect=VoiceUnavailable('unavailable')
        self.feed([voice(1)]);self.worker.tick();self.worker.tick()
        self.assertEqual(self.chip.sent,[(11,1,VOICE_FAILURE)]);self.assertEqual(self.model.calls,[])
        self.assertFalse(self.downloads[0].exists());self.assertIn('could not be transcribed',self.worker.history(11)[0]['text'])
    def test_oversize_declined_before_download(self):
        self.feed([voice(1,size=VOICE_MAX_BYTES+1)]);self.worker.tick();self.worker.tick()
        self.assertEqual(self.downloads,[]);self.assertEqual(self.chip.sent,[(11,1,VOICE_FAILURE)])
    def test_voice_obeys_ten_second_read_and_sixty_second_reply_timing(self):
        self.config.update(engagement_delay_seconds=10,reply_min_delay_seconds=60,mark_read_enabled=True,typing_enabled=True)
        events=[];self.chip.mark_read=lambda *a:events.append('read');self.chip.set_typing=lambda c,a:events.append(('typing',a))
        self.feed([voice(1)]);self.worker.tick();self.transcribe.assert_not_called();self.assertEqual(events,[])
        self.now=1010;self.worker.tick();self.assertEqual(events[:2],['read',('typing',True)])
        self.transcribe.assert_called_once();self.assertEqual(self.chip.sent,[])
        self.now=1060;self.worker.tick();self.assertEqual(len(self.chip.sent),1)
    def test_spoken_reset_is_not_an_administrative_command(self):
        self.transcribe.return_value='/reset';self.config['reset_allowed_chat_ids']=[11]
        self.feed([voice(1)]);self.worker.tick()
        self.assertEqual(self.worker.db.execute('SELECT count(*) FROM conversation_resets').fetchone()[0],0)
        self.assertIn('/reset',self.model.calls[0][1])
    def test_owner_voice_does_not_invoke_owner_send_broker(self):
        self.worker.capture([{'chat_id':11,'messages':[voice(1)]}]);self.config['owner_id']=11
        row=self.worker.db.execute('SELECT * FROM reply_jobs').fetchone()
        with patch('bridge.urlopen') as network:self.assertIsNone(self.worker.owner_reply(row))
        network.assert_not_called()

class TranscriptionTests(unittest.TestCase):
    def test_multipart_ogg_and_json_transcript(self):
        with helpers.TemporaryDirectory() as tmp:
            audio=Path(tmp)/'voice.ogg';audio.write_bytes(b'OggStest')
            key=Path(tmp)/'key';key.write_text('test-secret')
            requests=[]
            def opener(req,timeout):requests.append(req);return io.BytesIO(b'{"text":"Hello BMW"}')
            self.assertEqual(vt.transcribe(audio,key,opener=opener),'Hello BMW')
            self.assertIn(b'gpt-transcribe',requests[0].data);self.assertIn(b'audio/ogg',requests[0].data)
            self.assertIn(b'filename="voice.ogg"',requests[0].data)
    def test_empty_transcript_and_provider_error_do_not_leak_secret(self):
        with helpers.TemporaryDirectory() as tmp:
            audio=Path(tmp)/'voice.ogg';audio.write_bytes(b'OggStest');key=Path(tmp)/'key';key.write_text('private-secret')
            def fail(*a,**kw):raise RuntimeError('private-secret provider error')
            with self.assertRaises(vt.VoiceUnavailable) as caught:vt.transcribe(audio,key,opener=fail)
            self.assertNotIn('private-secret',str(caught.exception))
            with self.assertRaises(vt.VoiceUnavailable):vt.transcribe(audio,key,opener=lambda *a,**k:io.BytesIO(b'{"text":""}'))
    def test_download_rejects_wrong_media_or_disguised_text(self):
        with helpers.TemporaryDirectory() as tmp:
            p=Path(tmp)/'voice.ogg';p.write_text('<html>')
            for kind in ['voice','document']:
                with patch.object(Chip,'call',return_value=json.dumps({'success':True,'path':str(p),'kind':kind})):
                    with self.assertRaises(VoiceUnavailable):Chip('http://localhost').download_voice(11,1,p)

class VoicePollTests(unittest.TestCase):
    def test_poll_includes_voice_but_not_music_or_link_preview(self):
        source=Path(__file__).resolve().parents[1]/'telegram_core.py'
        method=next(n for n in ast.walk(ast.parse(source.read_text())) if isinstance(n,ast.AsyncFunctionDef) and n.name=='poll_new_dms')
        env={'datetime':datetime,'json':json,'User':SimpleNamespace,'get_sender_name':lambda m:'Customer',
             'format_entity':lambda e:{'id':11},'json_serializer':str}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[method],type_ignores=[])),str(source),'exec'),env)
        def obj(name,**kw):return type(name,(),kw)()
        doc=SimpleNamespace(mime_type='audio/ogg',size=100,attributes=[obj('DocumentAttributeAudio',voice=True,duration=8)])
        audio=obj('MessageMediaDocument',document=doc)
        music=obj('MessageMediaDocument',document=SimpleNamespace(mime_type='audio/mpeg',size=10,attributes=[obj('DocumentAttributeAudio',voice=False,duration=10)]))
        preview=obj('MessageMediaWebPage',webpage=SimpleNamespace(document=doc,photo=None))
        date=datetime(2026,11,13,tzinfo=timezone.utc)
        msgs=[SimpleNamespace(id=i+1,date=date,message='',media=m,out=False) for i,m in enumerate([audio,music,preview])]
        async def dialogs(**k):return [SimpleNamespace(entity=SimpleNamespace(),date=date)]
        async def messages(*a,**k):return msgs
        async def wait():pass
        fake=SimpleNamespace(client=SimpleNamespace(get_dialogs=dialogs,get_messages=messages),_wait_for_rate_limit=wait)
        result=json.loads(asyncio.run(env['poll_new_dms'](fake,date.timestamp()-1)))
        self.assertEqual([m['msg_id'] for m in result[0]['messages']],[1])
        self.assertEqual(result[0]['messages'][0]['voice']['kind'],'voice')

if __name__=='__main__':unittest.main()
