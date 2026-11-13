import unittest
from unittest.mock import Mock,patch
import test_bridge as helpers
from test_bridge import message

class HandoffAdapterTests(unittest.TestCase):
    create_worker=helpers.BridgeTests.create_worker
    feed=helpers.BridgeTests.feed
    status=helpers.BridgeTests.status
    def setUp(self):
        helpers.BridgeTests.setUp(self)
        self.config['handoff_enabled']=True
        self.handoff=Mock()
        self.handoff.state.return_value={'allowed':True,'ack_source':None}
        self.handoff.call.return_value={'allowed':True,'token':'lease'}
        patcher=patch('bridge.handoff_module',return_value=self.handoff)
        patcher.start();self.addCleanup(patcher.stop)
    def test_paused_customer_is_recorded_without_model_reply(self):
        self.handoff.state.return_value={'allowed':False,'ack_source':None}
        self.feed([message(1)])
        self.worker.tick()
        self.assertEqual(self.status(1),'cancelled')
        self.assertEqual(self.model.calls,[]);self.assertEqual(self.chip.sent,[])
        self.assertEqual(self.worker.db.execute("SELECT count(*) FROM messages WHERE role='user'").fetchone()[0],1)
    def test_takeover_during_generation_cancels_prepared_reply(self):
        def generate(*args):
            self.handoff.state.return_value={'allowed':False,'ack_source':None}
            return 'old prepared reply'
        self.model.reply=generate
        self.feed([message(1)]);self.worker.tick()
        self.assertEqual(self.status(1),'cancelled');self.assertEqual(self.chip.sent,[])
    def test_resume_answers_only_new_customer_message(self):
        self.handoff.state.return_value={'allowed':False,'ack_source':None}
        self.feed([message(1)]);self.worker.tick()
        self.handoff.state.return_value={'allowed':True,'ack_source':None}
        self.now=1010
        self.feed([message(1),message(2,stamp=1010)])
        self.worker.tick()
        self.assertEqual(self.chip.sent,[(11,2,'reply: hello')])
    def test_human_outgoing_messages_stay_in_native_history(self):
        self.handoff.state.return_value={'allowed':False,'ack_source':None}
        self.feed([message(1),message(2,'Manager confirmed dimensions',out=True)])
        self.worker.tick()
        self.assertTrue(any('Manager confirmed dimensions' in r['text'] for r in self.worker.history(11)))
    def test_final_delivery_permit_can_cancel_even_after_generation(self):
        self.handoff.call.return_value={'allowed':False}
        self.feed([message(1)]);self.worker.tick()
        self.assertEqual(self.status(1),'cancelled');self.assertEqual(self.chip.sent,[])
