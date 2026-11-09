"""Owner-maintained profiles bound to verified platform IDs, never model-written."""
import json
from pathlib import Path
ROOT=Path('/root/projects/esteem/profiles')
def get_profile(channel,user_id,root=ROOT):
    if channel not in ('telegram','whatsapp','max'):raise ValueError('Unknown platform')
    identifier=str(user_id)
    if not identifier.isdigit():raise ValueError('Invalid verified user ID')
    path=Path(root)/channel/(identifier+'.json')
    if not path.exists():return {'platform':channel,'user_id':identifier,'role':'contact','permissions':[]}
    p=json.loads(path.read_text())
    if p.get('platform')!=channel or str(p.get('user_id'))!=identifier:raise ValueError('Profile identity mismatch')
    return p

def is_owner(user_id,root=ROOT):
    p=get_profile('telegram',user_id,root)
    return p.get('role')=='owner' and 'start_conversation' in p.get('permissions',[])
