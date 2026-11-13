"""Esteem-only Hermes tool; the gateway delivers photos to the current conversation."""
import json
import os
from pathlib import Path
import re
import sys
import threading
import time

_pending = {}
_lock = threading.Lock()


def library():
    folder=os.environ.get('ESTEEM_PHOTOS_ROOT','/root/projects/esteem/photos')
    if folder not in sys.path:sys.path.insert(0,folder)
    import product_photos
    return product_photos


def origin():
    from gateway.session_context import get_session_env
    platform=get_session_env('HERMES_SESSION_PLATFORM')
    chat=get_session_env('HERMES_SESSION_CHAT_ID')
    message=get_session_env('HERMES_SESSION_MESSAGE_ID')
    if platform!='whatsapp' or not chat or not message:
        raise RuntimeError('Photos require an active WhatsApp message')
    return (chat,message)


def product_photos(args, **kwargs):
    try:
        key=origin()
        photos=library().DropboxPhotos().prepare(args.get('tags'),args.get('count',3))
        with _lock:
            for expired in [k for k,v in _pending.items() if time.time()-v[0]>900]:
                del _pending[expired]
            # The most recent search is the chosen set, not an accumulation of repeated tool calls.
            _pending[key]=(time.time(),photos)
        return json.dumps({'prepared':len(photos),'photos':[{'tags':p['tags']} for p in photos],
                           'delivery':'Prepared images will be attached to your final reply in this WhatsApp conversation. '
                                      'Write a short caption; do not claim delivery/read confirmation. '
                                      'If prepared is zero, explain that no matching deliverable photos were found; '
                                      'do not silently drop constraints or promise an attachment.'},ensure_ascii=False)
    except Exception:
        if 'key' in locals():
            with _lock:
                _pending.pop(key,None)
        return json.dumps({'prepared':0,'error':'Photo lookup unavailable or unsupported tag request. No photos prepared.'})


def finalize(response_text, **kwargs):
    try:
        key=origin()
    except RuntimeError:
        return None
    with _lock:
        item=_pending.pop(key,None)
    # Only paths returned by this turn's trusted tool can become attachments.
    had_media='MEDIA:' in response_text
    clean=re.sub(r'MEDIA:[^\s]+', '', response_text).strip()
    if item and item[1] and time.time()-item[0]<900:
        prepared=item[1]
        try:
            _,checked=library().unpack_reply(library().pack_reply('',prepared))
        except Exception:
            return 'Не удалось подготовить фото к отправке. Пожалуйста, попробуйте ещё раз.'
        clean=clean.replace('[[as_document]]','').replace('[[audio_as_voice]]','').strip()
        return clean+'\n'+'\n'.join('MEDIA:'+p['path'] for p in checked)
    if had_media:
        return clean or 'Не удалось подготовить фото к отправке. Пожалуйста, попробуйте ещё раз.'
    return None


def register(ctx):
    schema={'name':'esteem_product_photos','description':library().GUIDANCE+'\nSearch and prepare up to three actual product photos for the current WhatsApp conversation.',
            'parameters':{'type':'object','properties':{'tags':{'type':'array','items':{'type':'string'},'minItems':1,'maxItems':12},
                'count':{'type':'integer','minimum':1,'maximum':3,'default':3}},'required':['tags'],'additionalProperties':False}}
    ctx.register_tool(name='esteem_product_photos',toolset='esteem_photos',schema=schema,handler=product_photos)
    ctx.register_hook('transform_llm_output',finalize)
