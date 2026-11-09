import json,tempfile,unittest,uuid
from pathlib import Path
from app import Flow,SOURCE,validate
from errors import Unavailable
class CRM:
 def __init__(self):self.records={};self.calls=[];self.fail_update=False
 def call(self,m,p):
  self.calls.append(m)
  if m=='crm.deal.add':
   i=len(self.records)+1;self.records[i]=p['fields'].copy();return i
  if m=='crm.deal.get':return self.records[p['id']]
  if m=='crm.deal.update':
   if self.fail_update:raise TimeoutError()
   self.records[p['id']].update(p['fields']);return True
  if m=='crm.timeline.comment.add':return 1
  raise AssertionError(m)
class Tests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'state.db';self.crm=CRM();self.calls=[]
  self.flow=Flow(self.path,self.crm,lambda p:'Здравствуйте! Это тест.',self.attempt)
  self.key=str(uuid.uuid4());self.data={'name':'Tester','phone':'+12025550123','inquiry':'Test bag'}
 def tearDown(self):self.temp.cleanup()
 def attempt(self,*args):self.calls.append(args);return 'receipt'
 def test_repeated_submission_and_process_send_once(self):
  self.flow.submit(self.key,self.data);self.flow.submit(self.key,self.data)
  self.flow.process(self.key);self.flow.process(self.key)
  self.assertEqual(len(self.calls),1);self.assertEqual(len(self.crm.records),1)
  self.assertEqual(self.flow.get(self.key)['status'],'sent')
 def test_fallback_only_on_definitive_rejection(self):
  def attempt(channel,*a):
   self.calls.append(channel)
   if channel!='max':raise Unavailable('not found')
   return 'max-receipt'
  self.flow.attempt=attempt;self.flow.submit(self.key,self.data);self.flow.process(self.key)
  self.assertEqual(self.calls,['telegram','whatsapp','max']);self.assertEqual(self.flow.get(self.key)['status'],'sent')
 def test_uncertain_send_stops_without_fallback(self):
  def attempt(channel,*a):self.calls.append(channel);raise TimeoutError()
  self.flow.attempt=attempt;self.flow.submit(self.key,self.data);self.flow.process(self.key)
  self.assertEqual(self.calls,['telegram']);self.assertEqual(self.flow.get(self.key)['status'],'review')
 def test_crash_while_sending_never_auto_resends(self):
  self.flow.submit(self.key,self.data);self.flow.update(self.key,status='sending')
  other=Flow(self.path,self.crm,lambda p:'hi',self.attempt);other.process(self.key)
  self.assertEqual(other.get(self.key)['status'],'review');self.assertFalse(self.calls)
 def test_crm_failure_blocks_all_sends(self):
  def fail(*a):raise TimeoutError()
  self.crm.call=fail;self.flow.submit(self.key,self.data);self.flow.process(self.key)
  self.assertFalse(self.calls);self.assertEqual(self.flow.get(self.key)['status'],'review')
 def test_saved_record_identity_must_match_before_sending(self):
  self.flow.submit(self.key,self.data)
  original=self.crm.call
  def wrong(m,p):
   result=original(m,p)
   if m=='crm.deal.get':return {**result,'ORIGINATOR_ID':'something-else'}
   return result
  self.crm.call=wrong;self.flow.process(self.key);self.assertFalse(self.calls)
 def test_failed_crm_sync_after_send_never_resends(self):
  self.crm.fail_update=True;self.flow.submit(self.key,self.data);self.flow.process(self.key);self.flow.process(self.key)
  self.assertEqual(len(self.calls),1);self.assertEqual(self.flow.get(self.key)['status'],'sent')
 def test_record_only_check_never_sends_or_generates(self):
  self.flow.generate=lambda p:self.fail('must not generate')
  self.flow.submit(self.key,self.data,send=False);self.flow.process(self.key)
  self.assertEqual(self.flow.get(self.key)['status'],'saved');self.assertFalse(self.calls)
 def test_validation_and_submission_conflict(self):
  self.assertEqual(validate({**self.data,'phone':'+1 (202) 555-0123'})['phone'],'+12025550123')
  with self.assertRaises(ValueError):validate({**self.data,'phone':'12025550123'})
  self.flow.submit(self.key,self.data)
  with self.assertRaises(ValueError):self.flow.submit(self.key,{**self.data,'inquiry':'Other'})
if __name__=='__main__':unittest.main()
