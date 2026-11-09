"""LLM interpretation for owner text. Model has no access to sending tools."""
import importlib.util,json,re
from pathlib import Path
BASE=Path('/root/projects/esteem')

class Interpreter:
    def __init__(self,base=BASE):
        self.base=base
        cfg=json.loads((base/'telegram-chip/agent/config.json').read_text())
        self.owner_id=int(cfg.get('owner_id',0))
        cfg['memory_file']=str(base/'control/INTERPRETER.md')
        spec=importlib.util.spec_from_file_location('esteem_text_engine',base/'telegram-chip/agent/bridge.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        self.model=module.CodexChat(cfg)
    def interpret(self,text,pending):
        from profiles import get_profile
        context={'verified_sender_profile':get_profile('telegram',self.owner_id),
                 'canonical_business_instructions':(self.base/'AGENT.md').read_text(),
                 'pending_owner_messages':pending,'current_owner_message':text}
        raw=self.model.reply([],json.dumps(context,ensure_ascii=False))
        decision=json.loads(raw)
        return validate(decision,text,pending)

def validate(d,text,pending):
    if not isinstance(d,dict) or d.get('action') not in ('send','clarify','chat','cancel'):
        raise ValueError('Invalid interpreter decision')
    if d['action']=='send':
        if d.get('channel') not in ('telegram','whatsapp','max'):raise ValueError('Invalid channel')
        phone=d.get('phone');evidence=d.get('phone_evidence');body=d.get('message')
        if not isinstance(phone,str) or not re.fullmatch(r'\+\d{8,15}',phone):raise ValueError('Invalid international number')
        if not isinstance(evidence,str) or not evidence.strip():raise ValueError('Missing phone evidence')
        if not any(evidence in source for source in [*pending,text]):raise ValueError('Phone evidence not from owner')
        if re.sub(r'\D','',evidence)!=phone[1:]:raise ValueError('Phone digits changed')
        if not isinstance(body,str) or not body.strip() or len(body)>3000:raise ValueError('Invalid message')
    elif not isinstance(d.get('reply'),str) or not d['reply'].strip() or len(d['reply'])>3000:
        raise ValueError('Invalid clarification or chat reply')
    return d
