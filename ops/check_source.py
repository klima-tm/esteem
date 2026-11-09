from pathlib import Path
import subprocess,json,re,sys
r=Path(__file__).resolve().parents[1]
files=[p for p in subprocess.check_output(['git','diff','--cached','--name-only','--diff-filter=ACMR','-z'],cwd=r).decode().split('\0') if p]
secrets=set();phones=set()
for path in [r/'telegram-chip/.env',r/'hermes/.env',r/'bitrix/sandbox.env',r/'control/token',r/'test-form/access-token']:
 if not path.exists():continue
 if path.name in ('token','access-token'):secrets.add(path.read_text().strip());continue
 for line in path.read_text().splitlines():
  if '=' not in line or line.startswith('#'):continue
  k,v=line.split('=',1)
  if re.search(r'hash|secret|token|password|api_key|webhook',k,re.I) and len(v.strip())>=12:secrets.add(v.strip())
def walk(x):
 if isinstance(x,dict):
  for k,v in x.items():
   if isinstance(v,str) and re.search(r'token|secret|password|api_key|api_hash',k,re.I) and len(v)>=20 and not v.startswith('/'):secrets.add(v)
   walk(v)
 elif isinstance(x,list):
  for v in x:walk(v)
for p in [r/'hermes/auth.json',r/'telegram-chip/agent/config.json',r/'max/auto_reply.json']:
 if not p.exists():continue
 d=json.loads(p.read_text());walk(d)
 for phone in re.findall(r'\+7\d{10}',json.dumps(d)):phones.add(phone)
flags=[]
for f in files:
 data=subprocess.check_output(['git','show',':'+f],cwd=r)
 for value in secrets:
  if value.encode() in data:flags.append((f,'known runtime credential'))
 text=data.decode('utf8',errors='replace')
 for phone in phones:
  if phone in text or phone[1:] in text:flags.append((f,'private runtime phone'))
 if re.search(r'gh[pousr]_[A-Za-z0-9]{25,}|sk-(?:proj-)?[A-Za-z0-9_-]{30,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',text):flags.append((f,'credential or private-key pattern'))
 if re.search(r'/rest/\d+/[a-zA-Z0-9]{12,}/',text):flags.append((f,'literal CRM webhook'))
 if any(part in f.split('/') for part in ('.venv','node_modules','session','sessions','state','migration-backup')):flags.append((f,'runtime directory'))
 if re.search(r'\.(?:sqlite\w*|session\w*|db)(?:-|$)|(?:^|/)auth.json$|(?:^|/)token$',f):flags.append((f,'runtime state filename'))
print(json.dumps({'staged_files':len(files),'findings':flags},indent=2))
if flags:sys.exit(1)
