import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock
from handoff_service import Store

class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.now=1000;self.notify=Mock(side_effect=lambda *a:100+a[0]);self.send=Mock(return_value='sent')
        self.path=Path(self.tmp.name)/'state.db'
        self.cfg={'group_id':5,'manager_ids':[7]}
        self.s=Store(self.path,self.cfg,self.notify,self.send,lambda:self.now)
        self.addCleanup(self.s.db.close)
    def request(self,chat='11',source='1',kind='specialist'):
        return self.s.request({'channel':'telegram','chat':chat,'source':source,'kind':kind,'question':'Exact fit?','summary':'Customer context'})
    def command(self,text,mid=20,reply_to=101,sender=7,group=5):
        return self.s.command({'group':group,'sender':sender,'id':mid,'reply_to':reply_to,'text':text})
    def state(self,chat='11',stamp=None):return self.s.state({'channel':'telegram','chat':chat,'stamp':stamp})
    def test_specialist_request_is_not_a_takeover(self):
        self.request();self.assertTrue(self.state()['allowed']);self.assertEqual(self.state()['mode'],'waiting')
    def test_explicit_human_request_holds_automatic_replies(self):
        self.request(kind='human');self.assertFalse(self.state()['allowed']);self.assertEqual(self.state()['ack_source'],'1')
    def test_takeover_and_resume_keep_history_and_ignore_old_messages(self):
        self.request();self.command('/takeover')
        self.s.event({'channel':'telegram','chat':'11','mid':'human1','text':'Manager confirmed fit','outgoing':True})
        self.assertFalse(self.state()['allowed'])
        self.now=1100;self.command('/resume',mid=21)
        self.assertFalse(self.state(stamp=1050)['allowed']);self.assertTrue(self.state(stamp=1101)['allowed'])
        self.assertTrue(any(e['text']=='Manager confirmed fit' for e in self.state()['context']))
    def test_reply_target_required(self):
        self.request();self.command('/takeover',reply_to=None);self.assertTrue(self.state()['allowed'])
    def test_authorization_checks_group_and_sender(self):
        self.request()
        for fields in ({'sender':9},{'group':6}):
            with self.assertRaises(PermissionError):self.command('/takeover',**fields)
        self.assertTrue(self.state()['allowed'])
    def test_takeover_is_per_customer(self):
        self.request();self.request(chat='22');self.command('/takeover')
        self.assertFalse(self.state()['allowed']);self.assertTrue(self.state('22')['allowed'])
    def test_notification_and_answer_idempotency(self):
        self.request();self.request();self.assertEqual(self.notify.call_count,1)
        self.command('/answer Yes, confirmed.');self.command('/answer Yes, confirmed.')
        self.assertEqual(self.send.call_count,1)
    def test_uncertain_answer_is_never_retried(self):
        self.request();self.send.side_effect=TimeoutError()
        self.command('/answer Yes.');self.command('/answer Yes.')
        self.assertEqual(self.send.call_count,1)
    def test_notification_failure_does_not_claim_success_or_retry(self):
        self.notify.side_effect=TimeoutError()
        self.assertFalse(self.request()['notified']);self.assertFalse(self.request()['notified'])
        self.assertEqual(self.notify.call_count,1)
    def test_manual_control_survives_restart(self):
        self.request();self.command('/takeover')
        other=Store(self.path,self.cfg,self.notify,self.send,lambda:self.now);self.addCleanup(other.db.close)
        self.assertFalse(other.state({'channel':'telegram','chat':'11'})['allowed'])
    def test_answer_does_not_release_explicit_takeover(self):
        self.request();self.command('/takeover');self.command('/answer Confirmed.',mid=21)
        self.assertFalse(self.state()['allowed'])
    def test_closed_request_cannot_control_a_newer_handoff(self):
        self.request();self.command('/resume');self.request(source='2')
        self.command('/takeover',mid=21,reply_to=101)
        self.assertTrue(self.state()['allowed'])

    def test_final_send_permission_is_denied_after_takeover(self):
        self.request()
        self.assertTrue(self.s.begin_send({'channel':'telegram','chat':'11','source':'1','stamp':1000})['allowed'])
        self.command('/takeover')
        self.assertFalse(self.s.begin_send({'channel':'telegram','chat':'11','source':'1','stamp':1000})['allowed'])

    def test_customer_cannot_release_control_by_sending_resume_text(self):
        self.request();self.command('/takeover')
        self.s.event({'channel':'telegram','chat':'11','mid':'customer-command','text':'/resume','outgoing':False})
        self.assertFalse(self.state()['allowed'])

if __name__=='__main__':unittest.main()
