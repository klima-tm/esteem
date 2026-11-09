"""Per-conversation rolling summaries; original transcript stays untouched."""
import time

class ConversationMemory:
    def __init__(self,db):
        self.db=db
        self.db.execute('''CREATE TABLE IF NOT EXISTS conversation_memory (
          chat_id TEXT PRIMARY KEY, summary TEXT NOT NULL, through_message_id INTEGER NOT NULL,
          updated_at REAL NOT NULL)''')
        self.db.execute('CREATE TABLE IF NOT EXISTS conversation_memory_items (chat_id TEXT,cursor INTEGER,PRIMARY KEY(chat_id,cursor))')
        self.db.commit()

    def plan(self,chat_id,rows,keep=16,batch_chars=16000):
        saved=self.db.execute('SELECT summary,through_message_id FROM conversation_memory WHERE chat_id=?',(str(chat_id),)).fetchone()
        summary,through=(saved[0],saved[1]) if saved else ('',-1)
        recent=rows[-keep:]
        covered={r[0] for r in self.db.execute('SELECT cursor FROM conversation_memory_items WHERE chat_id=?',(str(chat_id),))}
        pending=[r for r in rows[:-keep] if r['cursor'] not in covered]
        batch=[];size=0
        for r in pending:
            if batch and size+len(r['text'])>batch_chars:break
            batch.append(r);size+=len(r['text'])
        return summary,through,batch,[{'role':r['role'],'text':r['text']} for r in recent]

    def save(self,chat_id,summary,through,expected_previous,covered):
        if not isinstance(summary,str) or not summary.strip() or len(summary)>3500:raise ValueError('Invalid conversation summary')
        current=self.db.execute('SELECT through_message_id FROM conversation_memory WHERE chat_id=?',(str(chat_id),)).fetchone()
        current=current[0] if current else -1
        if current!=expected_previous or not covered:raise RuntimeError('Memory checkpoint changed')
        with self.db:
            self.db.execute('''INSERT INTO conversation_memory VALUES (?,?,?,?)
              ON CONFLICT(chat_id) DO UPDATE SET summary=excluded.summary,
              through_message_id=excluded.through_message_id,updated_at=excluded.updated_at''',
              (str(chat_id),summary,max(current,through),time.time()))
            self.db.executemany("INSERT INTO conversation_memory_items VALUES (?,?)",[(str(chat_id),cursor) for cursor in covered])

    def context(self,chat_id,rows,summarize):
        while True:
            summary,through,batch,recent=self.plan(chat_id,rows)
            if not batch:return summary,recent
            updated=summarize(summary,[{'role':r['role'],'text':r['text']} for r in batch])
            self.save(chat_id,updated,batch[-1]['cursor'],through,[r['cursor'] for r in batch])
