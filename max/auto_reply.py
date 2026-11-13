"""Esteem MAX text replies. Same canonical instructions and engine as Telegram."""
import asyncio
import importlib.util
import json
import logging
import os
from pathlib import Path
import sqlite3
import time
from types import SimpleNamespace

LOG = logging.getLogger('esteem.max')
ROOT = Path(__file__).resolve().parent


def product_photos_module():
    import sys
    path=str(ROOT.parent/'photos')
    if path not in sys.path:sys.path.insert(0,path)
    import product_photos
    return product_photos


class Replies:
    def __init__(self, config, model):
        self.config, self.model = config, model
        self.allowed = {int(c['user_id']): int(c['chat_id']) for c in config['allowed_contacts']}
        self.contact_activation = {int(c["user_id"]): c.get("activated_at",config["activated_at"]) for c in config["allowed_contacts"]}
        if not self.allowed:
            raise ValueError('No test contacts configured')
        self.db = sqlite3.connect(config['state_db'])
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS jobs (
          chat_id INTEGER, message_id INTEGER, stamp REAL, text TEXT, reply TEXT,
          status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, reply_id INTEGER,
          PRIMARY KEY(chat_id,message_id));
        CREATE TABLE IF NOT EXISTS history (
          seq INTEGER PRIMARY KEY, chat_id INTEGER, message_id INTEGER, role TEXT, text TEXT,
          UNIQUE(chat_id,message_id,role));
        UPDATE jobs SET status='uncertain' WHERE status='sending';
        ''')
        self.db.commit()
        self.queue = asyncio.Queue()

    def handoff(self):
        import sys
        path=str(ROOT.parent/'control')
        if path not in sys.path:sys.path.insert(0,path)
        import handoff_client
        return handoff_client

    async def capture(self, message, client):
        if self.config.get('handoff_enabled') and message.chat_id in self.allowed.values() and message.type=='USER':
            outgoing=message.sender==self.config['expected_sender_id']
            stamp=message.time/1000 if message.time>10**11 else message.time
            with self.db:
                self.db.execute('INSERT OR IGNORE INTO history(chat_id,message_id,role,text) VALUES(?,?,?,?)',
                                (message.chat_id,message.id,'assistant' if outgoing else 'user',message.text or '[Media]'))
            try:await asyncio.to_thread(self.handoff().event,'max',message.chat_id,message.id,message.text or '[Media]',outgoing,stamp)
            except Exception:LOG.warning('Handoff history sync deferred; native history retained')
        expected = self.allowed.get(message.sender)
        stamp = message.time / 1000 if message.time > 10**11 else message.time
        if (message.sender == self.config['expected_sender_id'] or expected is None
                or message.chat_id != expected or stamp < self.contact_activation.get(message.sender,self.config['activated_at'])
                or not message.text.strip() or message.type != 'USER'):
            return
        with self.db:
            row = self.db.execute('INSERT OR IGNORE INTO jobs(chat_id,message_id,stamp,text,status) '
                "VALUES(?,?,?,?,'received')", (message.chat_id,message.id,stamp,message.text))
            fresh = row.rowcount == 1
        if fresh:
            await self.queue.put((message.chat_id,message.id))

    async def process(self, client, key):
        row = self.db.execute('SELECT * FROM jobs WHERE chat_id=? AND message_id=?',key).fetchone()
        if not row or row['status'] not in ('received','generated'):
            return
        if self.config.get('handoff_enabled'):
            state=await asyncio.to_thread(self.handoff().state,'max',key[0],row['stamp'])
            if not state['allowed'] and state.get('ack_source')!=str(key[1]):
                with self.db:self.db.execute("UPDATE jobs SET status='cancelled' WHERE chat_id=? AND message_id=?",key)
                return
        if row['status'] == 'received':
            history = list(self.db.execute('SELECT role,text FROM history WHERE chat_id=? ORDER BY seq DESC LIMIT 16',(key[0],)))
            history = [{'role':r['role'],'text':r['text']} for r in reversed(history)]
            try:
                if hasattr(self.model,"summarize"):
                    import importlib.util
                    spec=importlib.util.spec_from_file_location("esteem_conversation_memory","/root/projects/esteem/control/conversation_memory.py")
                    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
                    memory=module.ConversationMemory(self.db)
                    rows=[dict(r) for r in self.db.execute('SELECT seq AS cursor,role,text FROM history WHERE chat_id=? ORDER BY seq',(key[0],))]
                    while True:
                        summary,through,batch,history=memory.plan(key[0],rows)
                        if not batch:break
                        updated=await asyncio.to_thread(self.model.summarize,summary,[{'role':r['role'],'text':r['text']} for r in batch])
                        memory.save(key[0],updated,batch[-1]['cursor'],through,[r['cursor'] for r in batch])
                    uid=next(uid for uid,cid in self.allowed.items() if cid==key[0])
                    reply=await asyncio.to_thread(self.model.reply_for_contact,history,row['text'],"max",uid,summary=summary,photo_context={"handoff_chat":str(key[0]),"handoff_source":str(key[1])})
                elif hasattr(self.model,"reply_for_contact"):
                    uid = next(uid for uid,cid in self.allowed.items() if cid==key[0])
                    reply = await asyncio.to_thread(self.model.reply_for_contact,history,row['text'],"max",uid,photo_context={"handoff_chat":str(key[0]),"handoff_source":str(key[1])})
                else:
                    reply = await asyncio.to_thread(self.model.reply,history,row['text'])
            except Exception as exc:
                attempts = row['attempts'] + 1
                with self.db:
                    self.db.execute('UPDATE jobs SET attempts=?,status=? WHERE chat_id=? AND message_id=?',
                        (attempts,'failed' if attempts>=3 else 'received',*key))
                LOG.error('Generation failed (%s); attempt %s',type(exc).__name__,attempts)
                if attempts < 3:
                    await asyncio.sleep(10 * attempts)
                    await self.queue.put(key)
                return
            with self.db:
                self.db.execute("UPDATE jobs SET status='generated',reply=? WHERE chat_id=? AND message_id=?",(reply,*key))
        else:
            reply = row['reply']
        if self.config.get('handoff_enabled'):
            state=await asyncio.to_thread(self.handoff().state,'max',key[0],row['stamp'])
            if not state['allowed'] and state.get('ack_source')!=str(key[1]):
                with self.db:self.db.execute("UPDATE jobs SET status='cancelled' WHERE chat_id=? AND message_id=?",key)
                return
        send_token=None
        if self.config.get('handoff_enabled'):
            permit=await asyncio.to_thread(self.handoff().call,'/begin-send',{'channel':'max','chat':str(key[0]),
                           'stamp':row['stamp'],'source':str(key[1])})
            if not permit['allowed']:
                with self.db:self.db.execute("UPDATE jobs SET status='cancelled' WHERE chat_id=? AND message_id=?",key)
                return
            send_token=permit['token']
        # Persist before send: an ambiguous failure or crash is never auto-retried.
        with self.db:
            self.db.execute("UPDATE jobs SET status='sending' WHERE chat_id=? AND message_id=?",key)
        try:
            if reply.startswith('\x1eESTEEM_PHOTOS_V1:'):
                from pymax import Photo
                caption,photos=product_photos_module().unpack_reply(reply)
                sent=await asyncio.wait_for(client.send_message(chat_id=key[0],text=caption,
                    attachments=[Photo(path=p['path']) for p in photos]),timeout=120)
            else:
                sent = await asyncio.wait_for(client.send_message(chat_id=key[0],text=reply),timeout=45)
        except Exception as exc:
            with self.db:
                self.db.execute("UPDATE jobs SET status='uncertain' WHERE chat_id=? AND message_id=?",key)
            LOG.error('Send outcome uncertain (%s); manual review required',type(exc).__name__)
            return
        finally:
            if send_token:
                try:await asyncio.to_thread(self.handoff().call,'/end-send',{'token':send_token})
                except Exception:LOG.warning('Send lease release deferred')
        with self.db:
            self.db.execute("UPDATE jobs SET status='sent',reply_id=? WHERE chat_id=? AND message_id=?",(sent.id,*key))
            self.db.execute('INSERT OR IGNORE INTO history(chat_id,message_id,role,text) VALUES(?,?,?,?)',(*key,'user',row['text']))
            visible=product_photos_module().history_text(reply) if reply.startswith('\x1eESTEEM_PHOTOS_V1:') else reply
            self.db.execute('INSERT OR IGNORE INTO history(chat_id,message_id,role,text) VALUES(?,?,?,?)',(key[0],sent.id,'assistant',visible))
        LOG.info('Replied to authorized MAX test message %s',key[1])

    async def worker(self, client):
        for row in self.db.execute("SELECT chat_id,message_id FROM jobs WHERE status IN ('received','generated') ORDER BY stamp,message_id"):
            await self.queue.put(tuple(row))
        while True:
            key = await self.queue.get()
            try:
                await self.process(client,key)
            except Exception as exc:
                LOG.error('Worker failed (%s)',type(exc).__name__)
                raise  # systemd restarts; durable jobs recover without duplicate sends
            finally:
                self.queue.task_done()


async def main():
    from pymax import WebClient, ExtraConfig
    from pymax.auth.qr import QrAuthFlow
    config = json.loads((ROOT/'auto_reply.json').read_text())
    spec = importlib.util.spec_from_file_location('esteem_telegram',config['reply_engine'])
    engine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(engine)
    replies = Replies(config,engine.CodexChat(config))
    class NoInteractiveLogin:
        async def show_qr(self,url):
            raise RuntimeError('MAX session needs explicit reauthentication')
    extra = ExtraConfig(log_level='ERROR',reconnect=True,reconnect_delay=10,relogin=False)
    extra.user_agent = extra.generate_web_user_agent().model_copy(update={'app_version':'26.11.1'})
    client = WebClient(work_dir=str(ROOT/'session'),session_name='max.db',
        auth_flow=QrAuthFlow(NoInteractiveLogin()),extra_config=extra)
    ready = asyncio.Event()
    @client.on_start()
    async def start(c):
        if not c.me or c.me.contact.id != config['expected_sender_id']:
            LOG.error('Unexpected MAX sender; stopping')
            await c.close()
            return
        ready.set()
        LOG.info('MAX connected; text replies enabled for %s test contacts',len(replies.allowed))
    @client.on_message()
    async def incoming(message,c):
        if ready.is_set():
            await replies.capture(message,c)
    from max_contact_api import install
    server = install(client,replies,ready)
    worker = None
    connection = asyncio.create_task(client.start())
    waiter = asyncio.create_task(ready.wait())
    try:
        done,_ = await asyncio.wait([connection,waiter],timeout=60,return_when=asyncio.FIRST_COMPLETED)
        if not ready.is_set():
            if connection.done(): await connection
            raise RuntimeError('MAX did not become ready')
        worker = asyncio.create_task(replies.worker(client))
        done,_=await asyncio.wait([connection,worker],return_when=asyncio.FIRST_COMPLETED)
        for task in done: await task
        raise RuntimeError('MAX connection or reply worker stopped')
    finally:
        for task in (worker,connection,waiter):
            if task: task.cancel()
        await asyncio.gather(*(t for t in (worker,connection,waiter) if t),return_exceptions=True)
        server.shutdown()
        await client.close()
        replies.db.close()

if __name__=='__main__':
    os.umask(0o077)
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    asyncio.run(main())
