import json,sys
from pathlib import Path
from urllib.error import HTTPError
ROOT=Path('/root/projects/esteem')
sys.path.insert(0,str(ROOT/'control'))
import server
server.TOKEN=(ROOT/'control/token').read_text().strip()
from errors import Unavailable,Uncertain

def attempt(channel,phone,text,key):
    if channel=='telegram':
        r=server.call('http://127.0.0.1:8080/funnel/contact',{'phone':phone,'message':text,'request_id':key},timeout=100)
        if r['status']=='unavailable':raise Unavailable(r.get('reason','Telegram unavailable'))
        if r['status']!='sent':raise Uncertain(r.get('reason','Telegram send uncertain'))
        return str(r['message_id'])
    if channel=='whatsapp':
        r=server.call('http://127.0.0.1:3011/funnel/resolve',{'phone':phone},timeout=30)
        if r.get('exists') is False:raise Unavailable('Phone not registered on WhatsApp')
        if r.get('exists') is not True:raise Uncertain('WhatsApp lookup uncertain')
    if channel=='max':
        r=server.call('http://127.0.0.1:3012/resolve',{'phone':phone},server.TOKEN,timeout=30)
        if r.get('exists') is False:raise Unavailable('Phone not registered on MAX')
        if r.get('exists') is not True:raise Uncertain('MAX lookup uncertain')
    return str(server.send({'channel':channel,'phone':phone,'message':text},key))
