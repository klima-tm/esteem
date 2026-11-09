import importlib.util,sqlite3,tempfile,asyncio
from pathlib import Path
from types import SimpleNamespace

def load(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
base=Path('/root/projects/esteem')
tg=load('tg',base/'telegram-chip/agent/bridge.py');mx=load('mx',base/'max/auto_reply.py')
class Model:
 def __init__(self):self.summary_calls=[];self.context=None
 def summarize(self,previous,older):self.summary_calls.append(older);return 'Customer needs a black Mercedes bag; availability unconfirmed.'
 def reply_for_contact(self,history,text,channel,user_id,summary=''):
  assert len(history)==16 and 'black Mercedes' in summary
  self.context=(history,summary);return 'test reply'
class Chip:
 def incoming(self,since):return [{'chat_id':10,'messages':[{'msg_id':21,'text':'new','out':False,'date':'1970-01-01T00:16:42+00:00'}]}]
 def verify_sender(self,expected):pass
 def send(self,*args):return 22
async def check():
 with tempfile.TemporaryDirectory() as tmp:
  model=Model();b=tg.Bridge({'state_db':tmp+'/tg.db','allowed_chat_id':10,'expected_sender_id':7},Chip(),model,clock=lambda:1000)
  for i in range(1,21):
   b._store_message(10,i,1001,f'old {i}',i%2==0)
  b.db.commit();b.tick();assert model.context and len(model.summary_calls)==1
  assert b.db.execute('select count(*) from messages').fetchone()[0]==22
  b.db.close();print('Telegram: summary +16 recent messages reach reply model; full transcript retained')
  model=Model();r=mx.Replies({'state_db':tmp+'/max.db','expected_sender_id':7,'allowed_contacts':[{'user_id':2,'chat_id':10}],'activated_at':0},model)
  for i in range(1,21):r.db.execute('insert into history(chat_id,message_id,role,text) values (?,?,?,?)',(10,i,'user' if i%2 else 'assistant',f'old {i}'))
  r.db.commit()
  class Client:
   async def send_message(self,**kwargs):return SimpleNamespace(id=22)
  await r.capture(SimpleNamespace(sender=2,chat_id=10,id=21,text='new',time=1000,type='USER'),None)
  await r.process(Client(),(10,21));assert model.context and len(model.summary_calls)==1
  assert r.db.execute('select count(*) from history').fetchone()[0]==22
  r.db.close();print('MAX: summary +16 recent messages reach reply model; full transcript retained')
 print('Only fake sending methods were used; no external messages sent.')
asyncio.run(check())
