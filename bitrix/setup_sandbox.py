from pathlib import Path
import json,os
from sandbox_client import Client
os.umask(0o077)
root=Path('/root/projects/esteem/bitrix');client=Client.from_env()
fields=client.call('crm.deal.userfield.list')
spec=[('UF_CRM_ESTEEM_TEST_PHONE','Esteem AI — тестовый телефон'),('UF_CRM_ESTEEM_TEST_INQUIRY','Esteem AI — текст заявки'),('UF_CRM_ESTEEM_AI_STATUS','Esteem AI — статус агента')]
saved={}
for name,label in spec:
 matches=[f for f in fields if f['FIELD_NAME']==name]
 if matches:saved[name]=int(matches[0]['ID']);continue
 saved[name]=int(client.call('crm.deal.userfield.add',{'fields':{'FIELD_NAME':name,'USER_TYPE_ID':'string','XML_ID':name,'MULTIPLE':'N','MANDATORY':'N','SORT':990,'EDIT_FORM_LABEL':{'ru':label,'en':label},'LIST_COLUMN_LABEL':{'ru':label,'en':label},'SETTINGS':{'ROWS':4 if 'INQUIRY' in name else 1}}}))
readback=client.call('crm.deal.userfield.list');byname={f['FIELD_NAME']:int(f['ID']) for f in readback}
assert all(byname[n]==i for n,i in saved.items())
config={'crm_host':'b24-9hav3x.bitrix24.ru','category_id':0,'form_id':None,'enabled':False,'fields':saved}
(root/'sandbox-config.json').write_text(json.dumps(config,indent=2)+'\n')
print(json.dumps(config,ensure_ascii=False))
