"""Esteem human handoff: durable state and reply commands in one private group."""
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen

BASE=Path('/root/projects/esteem')
LOG=logging.getLogger('esteem.handoff')

def http(url,data=None,token=None):
    headers={'Content-Type':'application/json'}
    if token:headers['Authorization']='Bearer '+token
    req=Request(url,data=None if data is None else json.dumps(data).encode(),headers=headers)
    with urlopen(req,timeout=60) as response:return json.load(response)

def chip(path,data=None):
    r=http('http://127.0.0.1:8080'+path,data)
    if not r.get('success'):raise RuntimeError('Telegram operation failed')
    return r['data']

class Store:
    def __init__(self,path,config,notify,send,clock=time.time):
        self.db=sqlite3.connect(path,check_same_thread=False,timeout=30)
        self.db.row_factory=sqlite3.Row
        self.lock=threading.RLock();self.config=config;self.notify=notify;self.send=send;self.clock=clock
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS conversations(channel TEXT,chat TEXT,mode TEXT DEFAULT 'active',cutoff REAL DEFAULT 0,PRIMARY KEY(channel,chat));
        CREATE TABLE IF NOT EXISTS requests(id INTEGER PRIMARY KEY,channel TEXT,chat TEXT,source TEXT,kind TEXT,question TEXT,summary TEXT,status TEXT,group_mid INTEGER,created REAL, UNIQUE(channel,chat,source));
        CREATE TABLE IF NOT EXISTS events(channel TEXT,chat TEXT,mid TEXT,outgoing INTEGER,text TEXT,stamp REAL,PRIMARY KEY(channel,chat,mid));
        CREATE TABLE IF NOT EXISTS commands(mid INTEGER PRIMARY KEY,result TEXT);
        CREATE TABLE IF NOT EXISTS sends(token TEXT PRIMARY KEY,channel TEXT,chat TEXT,started REAL);
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value INTEGER);
        UPDATE requests SET status='uncertain' WHERE status='notifying';
        ''');self.db.commit()

    def identity(self,p):
        channel=p.get('channel');chat=str(p.get('chat',''))
        if channel not in ('telegram','whatsapp','max') or not chat or len(chat)>100:raise ValueError('Invalid conversation')
        return channel,chat

    def state(self,p):
        channel,chat=self.identity(p)
        with self.lock:
            r=self.db.execute('SELECT mode,cutoff FROM conversations WHERE channel=? AND chat=?',(channel,chat)).fetchone()
            mode,cutoff=(r['mode'],r['cutoff']) if r else ('active',0)
            stamp=p.get('stamp')
            allowed=mode not in ('human','waiting_human') and (stamp is None or stamp>cutoff)
            events=[dict(r) for r in self.db.execute('SELECT mid,outgoing,substr(text,1,1200) AS text,stamp FROM events WHERE channel=? AND chat=? ORDER BY stamp DESC LIMIT 30',(channel,chat))][::-1]
            ack=self.db.execute("SELECT source FROM requests WHERE channel=? AND chat=? AND status='notified' AND kind='human' ORDER BY id DESC LIMIT 1",(channel,chat)).fetchone()
            return {'allowed':allowed,'mode':mode,'cutoff':cutoff,'context':events,'ack_source':ack[0] if ack and mode=='waiting_human' else None}

    def event(self,p):
        channel,chat=self.identity(p)
        with self.lock,self.db:
            self.db.execute('INSERT OR IGNORE INTO events VALUES(?,?,?,?,?,?)',
                            (channel,chat,str(p['mid']),int(bool(p.get('outgoing'))),str(p.get('text',''))[:12000],p.get('stamp') or self.clock()))
        return self.state(p)

    def begin_send(self,p):
        channel,chat=self.identity(p)
        with self.lock:
            state=self.state(p)
            if not state['allowed'] and state.get('ack_source')!=str(p.get('source','')):
                return {'allowed':False}
            import secrets
            token=secrets.token_hex(16)
            with self.db:self.db.execute('INSERT INTO sends VALUES(?,?,?,?)',(token,channel,chat,self.clock()))
            return {'allowed':True,'token':token}

    def end_send(self,p):
        with self.lock,self.db:self.db.execute('DELETE FROM sends WHERE token=?',(p.get('token'),))
        return {'ok':True}

    def reset(self,p):
        channel,chat=self.identity(p)
        with self.lock,self.db:self.db.execute('DELETE FROM events WHERE channel=? AND chat=?',(channel,chat))
        return {'cleared':True}

    def request(self,p):
        channel,chat=self.identity(p);source=str(p['source']);kind=p.get('kind')
        if kind not in ('specialist','human'):raise ValueError('Invalid handoff kind')
        question=str(p.get('question','')).strip()[:2000]
        if not question:raise ValueError('Empty question')
        with self.lock:
            r=self.db.execute("SELECT * FROM requests WHERE channel=? AND chat=? AND status IN ('notifying','notified','taken','uncertain') ORDER BY id DESC LIMIT 1",(channel,chat)).fetchone()
            if not r:r=self.db.execute('SELECT * FROM requests WHERE channel=? AND chat=? AND source=?',(channel,chat,source)).fetchone()
            if r:return {'id':r['id'],'notified':r['group_mid'] is not None}
            summary=str(p.get('summary',''))[:7000]
            with self.db:
                cur=self.db.execute("INSERT INTO requests(channel,chat,source,kind,question,summary,status,created) VALUES(?,?,?,?,?,?,'notifying',?)",(channel,chat,source,kind,question,summary,self.clock()))
                rid=cur.lastrowid
            try:
                mid=self.notify(rid,channel,chat,question,summary,p.get('photos',[]))
            except Exception:
                with self.db:self.db.execute("UPDATE requests SET status='uncertain' WHERE id=?",(rid,))
                LOG.exception('Notification uncertain for request %s; no automatic retry',rid)
                return {'id':rid,'notified':False}
            with self.db:
                self.db.execute("UPDATE requests SET group_mid=?,status='notified' WHERE id=?",(mid,rid))
                self.db.execute("INSERT INTO conversations(channel,chat,mode) VALUES(?,?,?) ON CONFLICT(channel,chat) DO UPDATE SET mode=excluded.mode",(channel,chat,'waiting_human' if kind=='human' else 'waiting'))
            return {'id':rid,'notified':True}

    def command(self,event):
        if event.get('group')!=self.config['group_id']:raise PermissionError('Wrong group')
        if event.get('sender') not in self.config['manager_ids']:raise PermissionError('Not an authorized manager')
        mid=int(event['id']);text=event.get('text','').strip()
        match=re.fullmatch(r'/(takeover|resume|answer)(?:\s+([\s\S]+))?',text)
        if not match:return None
        action,body=match.groups()
        with self.lock:
            old=self.db.execute('SELECT result FROM commands WHERE mid=?',(mid,)).fetchone()
            if old:return old[0]
            r=self.db.execute('SELECT * FROM requests WHERE group_mid=?',(event.get('reply_to'),)).fetchone()
            if not r:return self.finish(mid,'Ответьте командой на исходное сообщение нужной эскалации. Клиент не выбран.')
            channel,chat=r['channel'],r['chat']
            latest=self.db.execute('SELECT id FROM requests WHERE channel=? AND chat=? ORDER BY id DESC LIMIT 1',(channel,chat)).fetchone()
            if latest and latest['id']!=r['id']:return self.finish(mid,'Есть более новая эскалация этого клиента. Ответьте на её сообщение.')

            if action=='answer':
                if not body or len(body)>3000:return self.finish(mid,'Формат: /answer Точный ответ клиенту (до 3000 символов).')
                # Persist before sending: an ambiguous result must never cause an automatic resend.
                self.finish(mid,'Отправка выполнялась; повтор заблокирован. Проверьте переписку клиента.')
                try:sent=self.send(channel,chat,body,mid)
                except Exception:
                    LOG.exception('Manager answer outcome uncertain')
                    return 'Результат отправки неизвестен. Автоматического повтора не будет; проверьте переписку клиента.'
                self.event({'channel':channel,'chat':chat,'mid':'manager:'+str(mid),'text':body,'outgoing':True})
                mode=self.state({'channel':channel,'chat':chat})['mode']
                with self.db:
                    self.db.execute("UPDATE requests SET status='answered' WHERE id=?",(r['id'],))
                    if mode!='human':self.db.execute("UPDATE conversations SET mode='active',cutoff=? WHERE channel=? AND chat=?",(self.clock(),channel,chat))
                return self.finish(mid,'Ответ отправлен клиенту. '+('Ручной режим сохранён; /resume вернёт управление агенту.' if mode=='human' else 'Агент продолжит со следующего сообщения клиента.'))
            mode='human' if action=='takeover' else 'active'
            with self.db:
                self.db.execute('INSERT INTO conversations VALUES(?,?,?,?) ON CONFLICT(channel,chat) DO UPDATE SET mode=excluded.mode,cutoff=excluded.cutoff',(channel,chat,mode,self.clock()))
                self.db.execute('UPDATE requests SET status=? WHERE id=?',('taken' if action=='takeover' else 'closed',r['id']))
            self.event({'channel':channel,'chat':chat,'mid':'control:'+str(mid),'text':'Manager '+action,'outgoing':True})
            inflight=self.db.execute('SELECT count(*) FROM sends WHERE channel=? AND chat=?',(channel,chat)).fetchone()[0]
            pause='Ручной режим: новые ответы агента остановлены для этого клиента.'
            if inflight:pause+=' Уже начатая отправка могла ещё не завершиться; проверьте переписку.'
            return self.finish(mid,pause if action=='takeover' else 'Управление возвращено агенту. История сохранена; он ответит на следующее сообщение клиента.')

    def finish(self,mid,text):
        with self.db:self.db.execute('INSERT OR REPLACE INTO commands VALUES(?,?)',(mid,text))
        return text

def main():
    os.umask(0o077);logging.basicConfig(level=logging.INFO)
    config=json.loads((BASE/'control/state/handoff-config.json').read_text())
    token=(BASE/'control/token').read_text().strip()
    group=config['group_id']
    def send_group(text,reply_to=None):
        raw=chip('/messages/send',{'chat_id':-group,'message':text,'reply_to':reply_to})
        m=re.fullmatch(r'Message sent successfully\. Message ID: (\d+)',raw)
        if not m:raise RuntimeError('No Telegram message receipt')
        return int(m[1])
    def notify(rid,channel,chat,question,summary,photos):
        label=chat
        if channel in ('telegram','max'):
            cfg=BASE/('telegram-chip/agent/config.json' if channel=='telegram' else 'max/auto_reply.json')
            data=json.loads(cfg.read_text())
            for contact in data.get('allowed_chats',data.get('allowed_contacts',[])):
                if str(contact.get('chat_id'))==chat:
                    label=' · '.join(str(contact[k]) for k in ('name','username','phone') if contact.get(k)) or chat
                    break
        text=f'Эскалация #{rid}\nКлиент: {label} · {channel} (ID {chat})\n\nВопрос: {question[:1200]}\n\nКонтекст:\n{summary[-1800:]}\n\nОтветьте НА ЭТО сообщение:\n/answer Точный ответ клиенту\n/takeover — отвечать вручную в аккаунте\n/resume — вернуть агенту (без ответа на старые сообщения)'
        mid=send_group(text[:3900])
        # Notifications are durable even if optional attachments fail.
        for p in photos[:5]:
            try:
                path=Path(p['path']).resolve()
                if not (path.is_relative_to(BASE/'photos/state/photo-cache') or path.is_relative_to(BASE/'telegram-chip/agent/state/photo-inputs')) or not path.is_file():continue
                chip('/messages/send-file',{'chat_id':-group,'file_path':str(path),'caption':f'К эскалации #{rid}','reply_to':mid})
            except Exception:LOG.warning('Could not attach escalation photo %s',rid)
        return mid
    def send(channel,chat,text,mid):
        if channel=='telegram':
            raw=chip('/messages/send',{'chat_id':int(chat),'message':text})
            if not re.fullmatch(r'Message sent successfully\. Message ID: \d+',raw):raise RuntimeError('No receipt')
            return raw
        if channel=='whatsapp':
            r=http('http://127.0.0.1:3011/send',{'chatId':chat,'message':text,'esteemManagerToken':token})
            if not r.get('messageId'):raise RuntimeError('No receipt')
            return r['messageId']
        r=http('http://127.0.0.1:3012/handoff-answer',{'chat_id':int(chat),'message':text,'request_id':'handoff:'+str(mid)},token)
        if not r.get('success'):raise RuntimeError('No receipt')
        return r['message_id']
    store=Store(BASE/'control/state/handoff.sqlite3',config,notify,send)
    def poll():
        while True:
            try:
                log=BASE/'hermes/state/handoff-events.jsonl'
                if log.exists():
                    with store.lock:
                        offset=store.db.execute("SELECT value FROM meta WHERE key='wa_offset'").fetchone()
                    with log.open() as f:
                        f.seek(offset[0] if offset else 0)
                        for _ in range(200):
                            line=f.readline()
                            if not line or not line.endswith('\n'):break
                            record=json.loads(line);record['channel']='whatsapp'
                            store.event(record)
                            with store.lock,store.db:store.db.execute("INSERT OR REPLACE INTO meta VALUES('wa_offset',?)",(f.tell(),))
                with store.lock:
                    r=store.db.execute("SELECT value FROM meta WHERE key='cursor'").fetchone()
                data=json.loads(chip('/handoff/group-events?after='+str(r[0] if r else 0)))
                if not r:
                    with store.lock,store.db:store.db.execute("INSERT INTO meta VALUES('cursor',?)",(data['latest'],))
                else:
                    for event in data['events']:
                        if not event['out'] and event.get('text','').startswith(('/answer','/takeover','/resume')):
                            try:result=store.command(event)
                            except PermissionError:result='Команда недоступна для этого участника.'
                            if result:send_group(result,event['id'])
                        with store.lock,store.db:store.db.execute("UPDATE meta SET value=? WHERE key='cursor'",(event['id'],))
            except Exception:LOG.exception('Group polling failed')
            time.sleep(2)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*a):pass
        def do_POST(self):
            if not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+token):self.send_error(403);return
            try:
                n=int(self.headers.get('Content-Length',0))
                if not 0<n<=100000:raise ValueError('Invalid payload size')
                p=json.loads(self.rfile.read(n))
                fn={'/state':store.state,'/event':store.event,'/request':store.request,'/reset':store.reset,'/begin-send':store.begin_send,'/end-send':store.end_send}.get(self.path)
                if not fn:self.send_error(404);return
                result=fn(p);code=200
            except Exception as e:LOG.exception('Handoff API failed');result={'error':type(e).__name__};code=400
            self.send_response(code);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps(result).encode())
    threading.Thread(target=poll,daemon=True).start()
    ThreadingHTTPServer(('127.0.0.1',3014),Handler).serve_forever()

if __name__=='__main__':main()
