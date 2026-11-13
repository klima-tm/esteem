"""Authenticated local handoff client. No recipient chosen by the model."""
import json
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path('/root/projects/esteem')

def call(route, payload):
    token=(ROOT/'control/token').read_text().strip()
    req=Request('http://127.0.0.1:3014'+route, data=json.dumps(payload).encode(),
                headers={'Content-Type':'application/json','Authorization':'Bearer '+token})
    with urlopen(req,timeout=90) as response:
        result=json.load(response)
    if result.get('error'):raise RuntimeError(result['error'])
    return result

def state(channel, chat, stamp=None):
    return call('/state',{'channel':channel,'chat':str(chat),'stamp':stamp})

def event(channel, chat, mid, text, outgoing=False, stamp=None):
    return call('/event',{'channel':channel,'chat':str(chat),'mid':str(mid),
                         'text':text,'outgoing':outgoing,'stamp':stamp})
