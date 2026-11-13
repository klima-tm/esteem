import unittest
import test_bridge as helpers
from test_bridge import message

class ReadReceiptTests(unittest.TestCase):
    create_worker=helpers.BridgeTests.create_worker
    feed=helpers.BridgeTests.feed
    def setUp(self):
        helpers.BridgeTests.setUp(self)
        self.config.update(mark_read_enabled=True,engagement_delay_seconds=10,
                           reply_min_delay_seconds=60,typing_enabled=True)
        self.events=[]
        self.chip.mark_read=lambda chat,mid:self.events.append(('read',chat,mid))
        self.chip.set_typing=lambda chat,active:self.events.append(('typing',chat,active))
        old=self.model.reply
        def reply(history,text):self.events.append(('generate',));return old(history,text)
        self.model.reply=reply
    def test_ten_seconds_before_read_typing_generation_then_sixty_before_send(self):
        self.feed([message(1)]);self.worker.tick()
        self.now=1009;self.worker.tick()
        self.assertEqual(self.events,[]);self.assertEqual(self.chip.sent,[])
        self.now=1010;self.worker.tick()
        self.assertEqual(self.events[:3],[('read',11,1),('typing',11,True),('generate',)])
        self.now=1059;self.worker.tick();self.assertEqual(self.chip.sent,[])
        self.now=1060;self.worker.tick();self.assertEqual(len(self.chip.sent),1)
        self.assertEqual([e for e in self.events if e[0]=='read'],[('read',11,1)])
    def test_only_processed_chat_and_message_are_acknowledged(self):
        self.config['allowed_chats']=[{'chat_id':11},{'chat_id':33}];self.worker=self.create_worker()
        self.feed([message(1),message(2,stamp=1005)],other=[message(3,stamp=1005)])
        self.now=1010;self.worker.tick()
        self.assertEqual([e for e in self.events if e[0]=='read'],[('read',11,1)])
        self.now=1015;self.worker.tick()
        self.assertEqual([e for e in self.events if e[0]=='read'],[('read',11,1),('read',33,3)])
    def test_failed_receipt_retries_but_does_not_block_reply(self):
        def fail(chat,mid):self.events.append(('failed_read',chat,mid));raise TimeoutError()
        self.chip.mark_read=fail;self.feed([message(1)])
        self.now=1010;self.worker.tick();self.assertEqual(self.worker._read_through,{})
        self.now=1060;self.worker.tick();self.assertEqual(len(self.chip.sent),1)
        self.assertEqual(len([e for e in self.events if e[0]=='failed_read']),2)
    def test_reset_remains_immediate_and_is_marked_read(self):
        self.config['reset_allowed_chat_ids']=[11]
        self.feed([message(1,'/reset')]);self.worker.tick()
        self.assertEqual([e for e in self.events if e[0]=='read'],[('read',11,1)])
        self.assertEqual(len(self.chip.sent),1)
        self.assertNotIn(('typing',11,True),self.events)

if __name__=='__main__':unittest.main()
