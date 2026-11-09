"""Bitrix client pinned to the sandbox. Never follows redirects."""
from pathlib import Path
from urllib.parse import urlsplit
import http.client,json
HOST='b24-9hav3x.bitrix24.ru'
class Client:
 def __init__(self,url):
  u=urlsplit(url)
  if u.scheme!='https' or u.hostname!=HOST or u.port not in (None,443) or u.username or u.password or u.query or u.fragment:
   raise PermissionError('Only the exact Esteem sandbox CRM host is allowed')
  if not u.path.startswith('/rest/') or not u.path.endswith('/'):raise ValueError('Invalid webhook base path')
  self.path=u.path
 def call(self,method,params=None):
  import re
  if not re.fullmatch(r'[a-z][a-z0-9_.]+',method):raise ValueError('Invalid API method')
  c=None
  for attempt in range(3):
   try:
    c=http.client.HTTPSConnection(HOST,timeout=10);c.connect();break
   except (OSError,TimeoutError):
    if c:c.close()
    if attempt==2:raise
  try:
   c.request('POST',self.path+method+'.json',json.dumps(params or {}),{'Content-Type':'application/json'})
   r=c.getresponse()
   if 300<=r.status<400:raise PermissionError('CRM redirects are forbidden')
   d=json.loads(r.read())
   if 'error' in d:raise RuntimeError(d['error']+': '+d.get('error_description',''))
   return d['result']
  finally:c.close()
 def from_env():
  lines=Path('/root/projects/esteem/bitrix/sandbox.env').read_text().splitlines()
  return Client(dict(line.split('=',1) for line in lines if '=' in line)['BITRIX_WEBHOOK_URL'])
