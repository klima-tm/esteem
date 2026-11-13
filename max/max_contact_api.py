"""Owner broker endpoint, hosted inside the existing MAX connection process."""
import asyncio,hmac,json,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path

def install(client,replies,ready):
    loop=asyncio.get_running_loop()
    token=Path('/root/projects/esteem/control/token').read_text().strip()
    db=replies.db
    db.execute('CREATE TABLE IF NOT EXISTS contact_requests (id TEXT PRIMARY KEY,payload TEXT,status TEXT,message_id INTEGER)')
    db.execute("UPDATE contact_requests SET status='uncertain' WHERE status='sending'");db.commit()
    async def contact(p):
        if not ready.is_set() or not client.me or client.me.contact.id!=replies.config['expected_sender_id']:
            raise RuntimeError('MAX not ready')
        phone,text,key=p['phone'],p['message'],p['request_id']
        if not isinstance(text,str) or not text.strip() or len(text)>3000:raise ValueError('Invalid message')
        import re
        if not re.fullmatch(r'\+\d{8,15}',phone):raise ValueError('Invalid phone')
        encoded=json.dumps([phone,text])
        row=db.execute('SELECT * FROM contact_requests WHERE id=?',(key,)).fetchone()
        if row:
            if row['payload']!=encoded:raise ValueError('Request ID conflict')
            if row['status']=='sent':return {'success':True,'message_id':row['message_id']}
            raise RuntimeError('Previous send outcome uncertain')
        user=await client.search_by_phone(phone)
        if not user:raise ValueError('Number not found on MAX')
        if user.id==replies.config['expected_sender_id']:raise ValueError('Cannot contact sender account')
        cid=client.get_chat_id(first_user_id=replies.config['expected_sender_id'],second_user_id=user.id)
        cfg=Path('/root/projects/esteem/max/auto_reply.json');c=json.loads(cfg.read_text())
        if not any(x['user_id']==user.id for x in c['allowed_contacts']):
            c['allowed_contacts'].append({'phone':phone,'user_id':user.id,'chat_id':cid,'activated_at':time.time()-1})
            tmp=cfg.with_suffix('.tmp');tmp.write_text(json.dumps(c,indent=2)+'\n');tmp.chmod(0o600);tmp.replace(cfg)
        replies.allowed[user.id]=cid
        replies.contact_activation[user.id]=next(x.get('activated_at',c['activated_at']) for x in c['allowed_contacts'] if x['user_id']==user.id)
        with db:db.execute("INSERT INTO contact_requests VALUES (?,?,'sending',NULL)",(key,encoded))
        try:sent=await asyncio.wait_for(client.send_message(chat_id=cid,text=text),45)
        except BaseException:
            with db:db.execute("UPDATE contact_requests SET status='uncertain' WHERE id=?",(key,))
            raise
        with db:
            db.execute("UPDATE contact_requests SET status='sent',message_id=? WHERE id=?",(sent.id,key))
            db.execute('INSERT OR IGNORE INTO history(chat_id,message_id,role,text) VALUES(?,?,?,?)',(cid,sent.id,'assistant',text))
        return {'success':True,'message_id':sent.id}
    async def handoff_answer(p):
        cid=int(p['chat_id'])
        if cid not in replies.allowed.values() or not ready.is_set():raise ValueError('Conversation not authorized')
        text=p['message'];key=p['request_id'];encoded=json.dumps([cid,text])
        if not isinstance(text,str) or not text.strip() or len(text)>3000:raise ValueError('Invalid answer')
        row=db.execute('SELECT * FROM contact_requests WHERE id=?',(key,)).fetchone()
        if row:raise RuntimeError('Request already processed; check status')
        with db:db.execute("INSERT INTO contact_requests VALUES (?,?,'sending',NULL)",(key,encoded))
        try:sent=await asyncio.wait_for(client.send_message(chat_id=cid,text=text),45)
        except BaseException:
            with db:db.execute("UPDATE contact_requests SET status='uncertain' WHERE id=?",(key,))
            raise
        with db:
            db.execute("UPDATE contact_requests SET status='sent',message_id=? WHERE id=?",(sent.id,key))
            db.execute('INSERT OR IGNORE INTO history(chat_id,message_id,role,text) VALUES(?,?,?,?)',(cid,sent.id,'assistant',text))
        return {'success':True,'message_id':sent.id}
    async def resolve(p):
        if not ready.is_set() or not client.me or client.me.contact.id!=replies.config['expected_sender_id']:
            raise RuntimeError('MAX not ready')
        import re
        phone=p.get('phone','')
        if not re.fullmatch(r'\+\d{8,15}',phone):raise ValueError('Invalid phone')
        user=await client.search_by_phone(phone)
        return {'exists':user is not None}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*a):pass
        def do_POST(self):
            if self.path not in ('/contact','/resolve','/handoff-answer'):self.send_error(404);return
            if not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+token):self.send_error(403);return
            try:
                size=int(self.headers.get('Content-Length',0))
                if not 0<size<=16000:raise ValueError('Invalid size')
                payload=json.loads(self.rfile.read(size))
                future=asyncio.run_coroutine_threadsafe(resolve(payload) if self.path=='/resolve' else handoff_answer(payload) if self.path=='/handoff-answer' else contact(payload),loop)
                result=future.result(timeout=100);status=200
            except Exception:result={'success':False,'error':'Contact not confirmed; check status before retrying'};status=500
            body=json.dumps(result).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(body)
    server=ThreadingHTTPServer(('127.0.0.1',3012),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    return server
