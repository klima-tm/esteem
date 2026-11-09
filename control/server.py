"""Local authenticated broker for owner-requested first contacts."""
import ast,hashlib,hmac,json,os,re,sqlite3,subprocess,threading,time
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.request import Request,urlopen
BASE=Path('/root/projects/esteem')
_owner_config=BASE/'telegram-chip/agent/config.json'
OWNER=int(json.loads(_owner_config.read_text()).get('owner_id',0)) if _owner_config.exists() else 0
HELP='Формат: /contact telegram|whatsapp|max +номер Точный текст сообщения\nНапример: /contact whatsapp +12025550123 Здравствуйте! Это тест.'

def parse(text):
    if not text.strip().lower().startswith('/contact'):
        return None
    m=re.fullmatch(r'/contact\s+(telegram|whatsapp|max)\s+(\+\d{8,15})\s+(.+)',text.strip(),re.I|re.S)
    if not m: raise ValueError(HELP)
    phone='+'+re.sub(r'\D','',m[2]);body=m[3].strip()
    if not 8<=len(phone[1:])<=15 or not body or len(body)>3000:raise ValueError(HELP)
    return {'channel':m[1].lower(),'phone':phone,'message':body}

def write_json(path,data):
    tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n');tmp.chmod(0o600);tmp.replace(path)

def call(url,data=None,token=None,timeout=90):
    headers={'Content-Type':'application/json'}
    if token:headers['Authorization']='Bearer '+token
    req=Request(url,data=None if data is None else json.dumps(data).encode(),headers=headers)
    with urlopen(req,timeout=timeout) as r:return json.load(r)

def chip(path,data=None):
    r=call('http://127.0.0.1:8080'+path,data)
    if not r.get('success'):raise RuntimeError('Telegram API rejected request')
    return r['data']

class Broker:
    def __init__(self,path,send):
        self.db=sqlite3.connect(path,check_same_thread=False);self.lock=threading.Lock();self.send=send
        self.db.execute('CREATE TABLE IF NOT EXISTS requests (key TEXT PRIMARY KEY,payload TEXT,status TEXT,result TEXT)')
        self.db.execute("UPDATE requests SET status='uncertain',result='Исход предыдущей отправки неизвестен; повтор автоматически заблокирован.' WHERE status='sending'");self.db.commit()
    def request(self,p):
        from profiles import is_owner
        if p.get('owner_id')!=OWNER or not is_owner(p['owner_id']):raise PermissionError('Owner only')
        mid=p.get('message_id')
        if type(mid)!=int or mid<=0:raise ValueError('Invalid message ID')
        target=parse(p.get('text',''))
        if not target:return {'reply':HELP}
        key=f'telegram:{OWNER}:{mid}'
        encoded=json.dumps(target,sort_keys=True,ensure_ascii=False)
        with self.lock:
            row=self.db.execute('SELECT payload,status,result FROM requests WHERE key=?',(key,)).fetchone()
            if row:
                if row[0]!=encoded:raise ValueError('Request ID already used for different text')
                return {'reply':row[2] or 'Запрос уже выполняется; повтор не отправлен.'}
            self.db.execute("INSERT INTO requests VALUES (?,?,'sending',NULL)",(key,encoded));self.db.commit()
            try:
                result=self.send(target,key)
                reply=f"Отправлено через {target['channel']} на {target['phone']}. ID: {result}. Это подтверждение отправки, не прочтения. Ответы клиента разрешены."
                status='sent'
            except Exception as e:
                # Never retry a send whose outcome might be ambiguous.
                reply=f"Отправка не подтверждена ({type(e).__name__}). Автоматический повтор заблокирован; требуется проверить результат."
                status='uncertain'
            self.db.execute('UPDATE requests SET status=?,result=? WHERE key=?',(status,reply,key));self.db.commit()
            return {'reply':reply}

def send(target,key):
    channel,phone,text=target['channel'],target['phone'],target['message']
    if channel=='max':
        r=call('http://127.0.0.1:3012/contact',{**target,'request_id':key},TOKEN)
        if not r.get('success'):raise RuntimeError('MAX first contact not confirmed')
        return r['message_id']
    if channel=='telegram':
        expected=json.loads((BASE/'telegram-chip/agent/config.json').read_text())['expected_sender_id']
        if json.loads(chip('/me'))['id']!=expected:raise RuntimeError('Unexpected Telegram sender')
        result=chip('/contacts',{'phone':phone,'first_name':'Esteem lead'})
        match=re.search(r"['\"]id['\"]:\s*(\d+)",str(result))
        if not match:raise ValueError('Number not resolved on Telegram')
        uid=int(match[1]);cfg=BASE/'telegram-chip/agent/config.json';c=json.loads(cfg.read_text())
        if not any(x['chat_id']==uid for x in c['allowed_chats']):
            c['allowed_chats'].append({'chat_id':uid,'phone':phone,'activated_at':time.time()-1});write_json(cfg,c)
        result=chip('/messages/send',{'chat_id':str(uid),'message':text,'allow_first_contact':True})
        match=re.fullmatch(r'Message sent successfully\. Message ID: (\d+)',str(result))
        if not match:raise RuntimeError('Telegram did not confirm send')
        return match[1]
    if channel=='whatsapp':
        p=BASE/'hermes/.env';lines=p.read_text().splitlines();updated=[]
        for line in lines:
            if line.startswith('WHATSAPP_ALLOWED_USERS='):
                users=line.split('=',1)[1].split(',')
                if phone[1:] not in users:users.append(phone[1:])
                line='WHATSAPP_ALLOWED_USERS='+','.join(users)
            updated.append(line)
        new='\n'.join(updated)+'\n'
        if new!=p.read_text():
            p.write_text(new);p.chmod(0o600)
            subprocess.run(['systemctl','restart','esteem-hermes.service'],check=True,timeout=100)
        for _ in range(60):
            try:
                if call('http://127.0.0.1:3011/health',timeout=2).get('status')=='connected':break
            except Exception:pass
            time.sleep(1)
        else:raise RuntimeError('WhatsApp not connected')
        r=call('http://127.0.0.1:3011/send',{'chatId':phone[1:]+'@s.whatsapp.net','message':text})
        if not r.get('success') or not r.get('messageId'):raise RuntimeError('WhatsApp did not confirm send')
        return r['messageId']
    raise ValueError('Unsupported channel')

if __name__=='__main__':
    os.umask(0o077);TOKEN=(BASE/'control/token').read_text().strip()
    from natural_broker import NaturalBroker
    from owner_interpreter import Interpreter
    broker=NaturalBroker(BASE/'control/requests.sqlite3',send,Interpreter())
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            if self.path not in ('/contact','/interpret'):self.send_error(404);return
            if not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+TOKEN):self.send_error(403);return
            try:
                n=int(self.headers.get('Content-Length',0))
                if not 0<n<=16000:raise ValueError('Invalid request size')
                payload=json.loads(self.rfile.read(n))
                result=(broker.natural(payload) if self.path=='/interpret' else broker.request(payload));status=200
            except PermissionError:result={'reply':'Owner only'};status=403
            except ValueError as e:result={'reply':str(e)};status=400
            except Exception:result={'reply':'Control service error; check request status before retrying.'};status=500
            body=json.dumps(result,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(body)
    ThreadingHTTPServer(('127.0.0.1',3013),Handler).serve_forever()
