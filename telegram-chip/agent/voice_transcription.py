"""OpenAI voice-note transcription. No messaging operations or secret-bearing errors."""
from pathlib import Path
import json
import secrets
from urllib.request import Request,urlopen

MAX_BYTES=25_000_000
MAX_TEXT_CHARS=40_000
ENDPOINT='https://api.openai.com/v1/audio/transcriptions'

class VoiceUnavailable(RuntimeError):
    pass


def transcribe(path,key_file,model='gpt-transcribe',opener=urlopen):
    path=Path(path)
    if not path.is_file() or not 0<path.stat().st_size<=MAX_BYTES:
        raise VoiceUnavailable('Voice note exceeds transcription size limit')
    try:key=Path(key_file).read_text().strip()
    except Exception:raise VoiceUnavailable('Transcription credentials unavailable') from None
    if not key or '\n' in key:raise VoiceUnavailable('Transcription credentials unavailable')
    boundary='esteem-'+secrets.token_hex(16)
    fields={'model':model,'response_format':'json'}
    parts=[]
    for name,value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    mime={'.ogg':'audio/ogg','.wav':'audio/wav','.mp3':'audio/mpeg','.m4a':'audio/mp4','.webm':'audio/webm'}.get(path.suffix.lower())
    if not mime:raise VoiceUnavailable('Unsupported voice-note format')
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="voice{path.suffix.lower()}"\r\nContent-Type: {mime}\r\n\r\n'.encode())
    parts.extend([path.read_bytes(),f'\r\n--{boundary}--\r\n'.encode()])
    req=Request(ENDPOINT,data=b''.join(parts),headers={'Authorization':'Bearer '+key,
                'Content-Type':'multipart/form-data; boundary='+boundary})
    try:
        with opener(req,timeout=180) as response:
            data=json.loads(response.read(1_000_001))
    except Exception:
        raise VoiceUnavailable('OpenAI transcription unavailable') from None
    text=data.get('text') if isinstance(data,dict) else None
    if not isinstance(text,str) or not text.strip() or len(text)>MAX_TEXT_CHARS:
        raise VoiceUnavailable('No usable speech transcription')
    return text.strip()
