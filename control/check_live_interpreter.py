import json,concurrent.futures
from owner_interpreter import Interpreter
cases=[
 ('russian','Напиши в ватсап на +1 (202) 555-0123: «Здравствуйте! Что вас интересует?»',[],'send','whatsapp'),
 ('spanish','Escribe por Telegram al +12025550123 y dile: Hola, ¿qué bolso te interesa?',[],'send','telegram'),
 ('informal','hey can u msg +12025550123 on max, just say hi and ask which bag they wanted',[],'send','max'),
 ('draft_only','Draft a WhatsApp message to +12025550123 saying hello. Do not send it.',[],'no_send',None),
 ('missing_channel','Напиши на +12025550123, спроси какая сумка интересует.',[],'clarify',None),
 ('followup','В ватсап',['Напиши на +12025550123, спроси какая сумка интересует.'],'send','whatsapp'),
 ('capability','Can you send first messages on WhatsApp?',[],'no_send',None),
 ('cancel','Нет, ничего не отправляй',['Напиши на +12025550123, спроси какая сумка интересует.'],'no_send',None),
]
def check(c):
 name,text,pending,expected,channel=c
 d=Interpreter().interpret(text,pending)
 okay=(d['action']!='send' if expected=='no_send' else d['action']==expected)
 if channel:okay=okay and d.get('channel')==channel
 if name=='russian':okay=okay and d.get('message')=='Здравствуйте! Что вас интересует?'
 return {'case':name,'passed':okay,'decision':d}
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
 results=list(pool.map(check,cases))
for r in results:print(json.dumps(r,ensure_ascii=False),flush=True)
assert all(r['passed'] for r in results),'Interpreter acceptance failure'
print('Live interpretation only: no sending tool was provided or called.')
