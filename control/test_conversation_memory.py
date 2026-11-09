import sqlite3,unittest
from conversation_memory import ConversationMemory

def rows(n,start=1):return [{'cursor':i,'role':'user' if i%2 else 'assistant','text':f'message {i}'} for i in range(start,start+n)]
class Tests(unittest.TestCase):
 def setUp(self):self.db=sqlite3.connect(':memory:');self.memory=ConversationMemory(self.db);self.calls=[]
 def tearDown(self):self.db.close()
 def summarize(self,prev,batch):self.calls.append((prev,batch));return prev+' facts '+','.join(r['text'] for r in batch)
 def test_short_history_no_summary_call(self):
  summary,recent=self.memory.context('a',rows(16),self.summarize)
  self.assertEqual(summary,'');self.assertEqual(len(recent),16);self.assertFalse(self.calls)
 def test_older_messages_summarized_recent_retained(self):
  summary,recent=self.memory.context('a',rows(20),self.summarize)
  self.assertIn('message 1',summary);self.assertEqual(recent[0]['text'],'message 5');self.assertEqual(len(recent),16)
  self.assertEqual(self.db.execute('select count(*) from conversation_memory_items').fetchone()[0],4)
 def test_repeat_and_restart_do_not_resummarize(self):
  self.memory.context('a',rows(20),self.summarize);self.memory=ConversationMemory(self.db)
  self.memory.context('a',rows(20),self.summarize);self.assertEqual(len(self.calls),1)
 def test_incremental_merge(self):
  self.memory.context('a',rows(20),self.summarize);summary,_=self.memory.context('a',rows(22),self.summarize)
  self.assertEqual([r['text'] for r in self.calls[1][1]],['message 5','message 6']);self.assertIn('message 1',summary)
 def test_chats_are_isolated(self):
  self.memory.context('a',rows(20),self.summarize)
  summary,_=self.memory.context('b',rows(10),self.summarize);self.assertEqual(summary,'')
 def test_failed_summary_leaves_checkpoint_untouched(self):
  def fail(*a):raise TimeoutError()
  with self.assertRaises(TimeoutError):self.memory.context('a',rows(20),fail)
  self.assertEqual(self.db.execute('select count(*) from conversation_memory_items').fetchone()[0],0)
 def test_small_batches_cover_every_message(self):
  data=rows(60)
  while True:
   summary,through,batch,recent=self.memory.plan('a',data,batch_chars=20)
   if not batch:break
   self.memory.save('a','summary',batch[-1]['cursor'],through,[r['cursor'] for r in batch])
  self.assertEqual(self.db.execute('select count(*) from conversation_memory_items').fetchone()[0],44)
 def test_late_lower_id_is_not_skipped(self):
  data=[r for r in rows(22) if r['cursor']!=2]
  self.memory.context('a',data,self.summarize)
  self.memory.context('a',rows(22),self.summarize)
  self.assertIn('message 2',[r['text'] for r in self.calls[-1][1]])
 def test_invalid_summary_does_not_advance(self):
  with self.assertRaises(ValueError):self.memory.context('a',rows(20),lambda *a:'')
  self.assertEqual(self.db.execute('select count(*) from conversation_memory_items').fetchone()[0],0)
if __name__=='__main__':unittest.main()
