import unittest
import test_bridge as helpers
from test_bridge import message

class AdaptiveTimingTests(unittest.TestCase):
    create_worker=helpers.BridgeTests.create_worker
    feed=helpers.BridgeTests.feed
    def setUp(self):
        helpers.BridgeTests.setUp(self)
        self.config.update(engagement_delay_seconds=10,reply_seconds_per_character=0.2,
                           reply_base_delay_seconds=2,mark_read_enabled=True)
        self.reads=[]
        self.chip.mark_read=lambda *args:self.reads.append(self.now)
        self.model.reply=lambda *args:"x"*150
    def test_read_clock_generation_included_and_restart(self):
        self.feed([message(1)])
        self.worker.tick()
        self.assertEqual(self.reads,[])
        self.now=1010
        self.worker.tick()
        self.assertEqual(self.reads,[1010])
        self.assertEqual(self.chip.sent,[])
        self.now=1020
        self.worker=self.create_worker()
        self.worker.tick()
        self.now=1041
        self.worker.tick()
        self.assertEqual(self.chip.sent,[])
        self.now=1042
        self.worker.tick()
        self.assertEqual(len(self.chip.sent),1)
    def test_slow_generation_sends_immediately(self):
        def slow(*args):
            self.now=1050
            return "x"*150
        self.model.reply=slow
        self.feed([message(1)])
        self.now=1010
        self.worker.tick()
        self.assertEqual(len(self.chip.sent),1)
    def test_no_cap(self):
        self.model.reply=lambda *args:"x"*1000
        self.feed([message(1)])
        self.now=1010
        self.worker.tick()
        self.now=1211
        self.worker.tick()
        self.assertEqual(self.chip.sent,[])
        self.now=1212
        self.worker.tick()
        self.assertEqual(len(self.chip.sent),1)
    def test_failed_read_does_not_generate_or_start_clock(self):
        def fail(*args):raise TimeoutError()
        self.chip.mark_read=fail
        self.feed([message(1)])
        self.now=1010
        self.worker.tick()
        row=self.worker.db.execute("SELECT read_at,status FROM reply_jobs").fetchone()
        self.assertEqual(tuple(row),(None,"received"))


    def test_six_second_read_then_four_second_typing(self):
        self.config.update(engagement_delay_seconds=6,typing_delay_after_read_seconds=4,typing_enabled=True)
        typing=[]
        self.chip.set_typing=lambda chat,active:typing.append((self.now,active))
        self.feed([message(1)])
        self.now=1005;self.worker.tick()
        self.assertEqual(self.reads,[]);self.assertEqual(typing,[])
        self.now=1006;self.worker.tick()
        self.assertEqual(self.reads,[1006]);self.assertEqual(typing,[])
        self.now=1009;self.worker.tick()
        self.assertEqual(typing,[])
        self.now=1010;self.worker.tick()
        self.assertEqual(typing,[(1010,True)])
        self.now=1037;self.worker.tick()
        self.assertEqual(self.chip.sent,[])
        self.now=1038;self.worker.tick()
        self.assertEqual(len(self.chip.sent),1)
