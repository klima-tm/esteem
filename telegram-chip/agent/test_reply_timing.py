import unittest
from unittest.mock import patch
import test_bridge as helpers
from test_bridge import message
from bridge import Bridge,RESET_REPLY,TypingPulse

class ReplyTimingTests(unittest.TestCase):
    create_worker=helpers.BridgeTests.create_worker
    feed=helpers.BridgeTests.feed
    status=helpers.BridgeTests.status
    def setUp(self):
        helpers.BridgeTests.setUp(self)
        self.config.update(reply_min_delay_seconds=60,typing_enabled=True,reset_allowed_chat_ids=[11])
        self.typing=[]
        self.chip.set_typing=lambda chat,active:self.typing.append((chat,active))
    def test_ready_reply_waits_until_sixty_seconds_without_regeneration(self):
        self.feed([message(1)])
        self.worker.tick()
        self.assertEqual(self.status(1),'generated');self.assertEqual(self.chip.sent,[])
        self.assertEqual(self.typing,[(11,True)])
        self.now=1059;self.worker.tick();self.assertEqual(self.chip.sent,[])
        self.now=1060;self.worker.tick()
        self.assertEqual(self.chip.sent,[(11,1,'reply: hello')]);self.assertEqual(len(self.model.calls),1)
        self.assertEqual(self.typing[-1],(11,False))
    def test_slow_generation_is_not_delayed_an_extra_minute(self):
        def slow(history,text):self.now=1080;return 'Prepared'
        self.model.reply=slow;self.feed([message(1)])
        self.worker.tick()
        self.assertEqual(self.chip.sent,[(11,1,'Prepared')])
        self.assertEqual(self.typing,[(11,True),(11,False)])
    def test_restart_preserves_deadline_and_prepared_reply(self):
        self.feed([message(1)]);self.worker.tick()
        self.now=1030;self.worker=self.create_worker();self.worker.tick()
        self.assertEqual(self.chip.sent,[])
        self.now=1061;self.worker.tick()
        self.assertEqual(len(self.chip.sent),1);self.assertEqual(len(self.model.calls),1)
    def test_waiting_does_not_prevent_other_chat_preparation(self):
        self.config['allowed_chats']=[{'chat_id':11},{'chat_id':33}];self.worker=self.create_worker()
        self.feed([message(1)],other=[message(2)])
        self.worker.tick()
        self.assertEqual(len(self.model.calls),2);self.assertEqual(self.chip.sent,[])
        self.assertEqual(set(self.typing),{(11,True),(33,True)})
    def test_reset_discards_waiting_reply_and_cancels_typing(self):
        self.feed([message(1)]);self.worker.tick()
        self.now=1010;self.feed([message(2,'/reset',stamp=1010)]);self.worker.tick()
        self.assertEqual(self.chip.sent,[(11,2,RESET_REPLY)])
        self.assertEqual(self.typing[-1],(11,False))
        self.now=1080;self.worker.tick();self.assertEqual(len(self.chip.sent),1)
    def test_failed_generation_and_uncertain_send_stop_typing(self):
        self.feed([message(1)]);self.model.fail=True;self.worker.tick()
        self.assertEqual(self.typing[-1],(11,False));self.assertEqual(self.chip.sent,[])
        self.model.fail=False;self.chip.send_error=True;self.now=1061;self.worker.tick()
        self.assertEqual(self.status(1),'uncertain');self.assertEqual(self.typing[-1],(11,False))
        self.now=1100;self.worker.tick();self.assertEqual(len(self.chip.sent),1)
    def test_typing_error_does_not_block_reply(self):
        def unavailable(*args):raise TimeoutError()
        self.chip.set_typing=unavailable;self.feed([message(1)])
        self.worker.tick();self.now=1060;self.worker.tick()
        self.assertEqual(len(self.chip.sent),1)
    def test_owner_control_is_not_delayed(self):
        self.config['owner_id']=11
        self.feed([message(1)])
        with patch.object(self.worker,'owner_reply',return_value='Owner reply'):self.worker.tick()
        self.assertEqual(self.chip.sent,[(11,1,'Owner reply')]);self.assertEqual(self.typing,[])
    def test_heartbeat_renews_during_blocking_generation_and_stops(self):
        pulse=TypingPulse(self.chip,11,True)
        with patch.object(pulse.stop,'wait',side_effect=[False,False,True]):pulse.renew()
        self.assertEqual(self.typing,[(11,True),(11,True)])
        with pulse:pass
        self.assertTrue(pulse.stop.is_set());self.assertFalse(pulse.thread.is_alive())
        self.assertEqual(self.typing[-1],(11,False))

if __name__=='__main__':unittest.main()
