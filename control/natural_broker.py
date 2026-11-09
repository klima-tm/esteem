"""Persist interpretation before execution; replay decisions without new sends."""
import json,threading
from server import Broker,OWNER
from profiles import is_owner

class NaturalBroker(Broker):
    def __init__(self,path,send,interpreter):
        super().__init__(path,send)
        self.lock=threading.RLock();self.interpreter=interpreter
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS owner_turns (message_id INTEGER PRIMARY KEY,text TEXT,decision TEXT,result TEXT);
        CREATE TABLE IF NOT EXISTS owner_state (id INTEGER PRIMARY KEY,pending TEXT);
        INSERT OR IGNORE INTO owner_state VALUES (1,'[]');
        ''');self.db.commit()
    def natural(self,p):
        if p.get('owner_id')!=OWNER or not is_owner(p['owner_id']):raise PermissionError('Owner only')
        mid=p.get('message_id');text=p.get('text')
        if type(mid)!=int or mid<=0 or not isinstance(text,str) or not text.strip() or len(text)>6000:
            raise ValueError('Invalid owner message')
        with self.lock:
            row=self.db.execute('SELECT text,decision,result FROM owner_turns WHERE message_id=?',(mid,)).fetchone()
            if row and row[0]!=text:raise ValueError('Message ID reused with changed text')
            if row and row[2]:return json.loads(row[2])
            pending=json.loads(self.db.execute('SELECT pending FROM owner_state WHERE id=1').fetchone()[0])
            if row:decision=json.loads(row[1])
            else:
                decision=self.interpreter.interpret(text,pending)
                self.db.execute('INSERT INTO owner_turns VALUES (?,?,?,NULL)',(mid,text,json.dumps(decision,ensure_ascii=False)));self.db.commit()
            if decision['action']=='send':
                # Reuse the existing durable first-contact tool and all its authorization checks.
                command=f"/contact {decision['channel']} {decision['phone']} {decision['message']}"
                result=self.request({'owner_id':OWNER,'message_id':mid,'text':command})
                # Include the exact actual outgoing content in the owner's receipt.
                result={'reply':result['reply']+'\n\n'+decision['message']}
                updated=[]
            else:
                result={'reply':decision['reply']}
                updated=([*pending,text][-8:] if decision['action']=='clarify' else [])
            with self.db:
                self.db.execute('UPDATE owner_turns SET result=? WHERE message_id=?',(json.dumps(result,ensure_ascii=False),mid))
                self.db.execute('UPDATE owner_state SET pending=? WHERE id=1',(json.dumps(updated,ensure_ascii=False),))
            return result
