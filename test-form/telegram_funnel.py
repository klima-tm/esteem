"""Explicit first-contact endpoint with provider-level definitive failure results."""
import json,re,sqlite3,time
from pathlib import Path
from pydantic import BaseModel,Field
from telethon import functions
from telethon.tl.types import InputPhoneContact
from fastapi import HTTPException
ROOT=Path('/root/projects/esteem')
class Contact(BaseModel):
    phone:str=Field(pattern=r'^\+\d{8,15}$')
    message:str=Field(min_length=1,max_length=3000)
    request_id:str=Field(pattern=r'^[a-zA-Z0-9:_-]{1,100}$')

def install(app,telegram):
    @app.post('/funnel/contact')
    async def contact(p:Contact):
        db=sqlite3.connect(ROOT/'telegram-chip/funnel-requests.sqlite3')
        db.execute('CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY,payload TEXT,status TEXT,result TEXT)')
        payload=json.dumps([p.phone,p.message])
        row=db.execute('SELECT payload,status,result FROM requests WHERE id=?',(p.request_id,)).fetchone()
        if row:
            db.close()
            if row[0]!=payload:raise HTTPException(409,'Request ID conflict')
            return json.loads(row[2]) if row[2] else {'status':'uncertain','reason':'Previous operation still pending or interrupted'}
        try:
            # All awaits before a send are lookups, never blind resend attempts.
            cfg=ROOT/'telegram-chip/agent/config.json';expected=json.loads(cfg.read_text())['expected_sender_id']
            if (await telegram.client.get_me()).id!=expected:raise RuntimeError('Unexpected Telegram sender')
            await telegram._wait_for_rate_limit()
            imported=await telegram.client(functions.contacts.ImportContactsRequest(contacts=[InputPhoneContact(client_id=0,phone=p.phone,first_name='Esteem test lead',last_name='')]))
            if not imported.users:return {'status':'unavailable','reason':'Phone not discoverable on Telegram'}
            user=imported.users[0]
            if user.id==(await telegram.client.get_me()).id:return {'status':'unavailable','reason':'Cannot contact the sender account itself'}
            cfg=ROOT/'telegram-chip/agent/config.json';c=json.loads(cfg.read_text())
            if not any(x['chat_id']==user.id for x in c['allowed_chats']):
                c['allowed_chats'].append({'chat_id':user.id,'phone':p.phone,'activated_at':time.time()-1})
                tmp=cfg.with_suffix('.funnel.tmp');tmp.write_text(json.dumps(c,ensure_ascii=False,indent=2)+'\n');tmp.chmod(0o600);tmp.replace(cfg)
            await telegram._check_message_rate_limit(user.id)
            await telegram._wait_for_rate_limit()
            db.execute("INSERT INTO requests VALUES (?,?,'sending',NULL)",(p.request_id,payload));db.commit()
            try:
                sent=await telegram.client.send_message(user,p.message)
                result={'status':'sent','message_id':sent.id,'recipient_id':user.id}
            except Exception as e:
                definitive={'UserPrivacyRestrictedError','ChatWriteForbiddenError','UserIsBlockedError','YouBlockedUserError','PeerIdInvalidError','UserDeactivatedError','InputUserDeactivatedError','UserNotMutualContactError','PrivacyPremiumRequiredError'}
                result={'status':'unavailable' if type(e).__name__ in definitive else 'uncertain','reason':type(e).__name__}
            db.execute('UPDATE requests SET status=?,result=? WHERE id=?',(result['status'],json.dumps(result),p.request_id));db.commit()
            return result
        finally:db.close()
