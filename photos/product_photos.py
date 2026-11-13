"""Read-only Dropbox tag search and prepared native photo replies. No recipient API."""
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

STATE = Path('/root/projects/esteem/photos/state')
ROOT = '/Products Esteem'
PREFIX = '\x1eESTEEM_PHOTOS_V1:'
PRODUCTS = set('mats bag suitcase suitbag trunk trunkbox luggage keycase watchcase pillow seatscape wallet notebook statuette shoehorn beltplugs nametag pets booster seat shell painting helmet keybox template iphonecase backpack other'.split())
MODELS = set('lusso corsa corsamini corsapro martello diamante elegantemini elegante monte laptop business cosmetic shoebag 2d 3d'.split())
MATERIALS = set('leather alcantara wool velour carbon exotic'.split())
COLORS = set('red black blue purple yellow white grey green orange brown pink'.split())
EXCLUDED = {'ai', 'before', 'china', 'design', 'template'}
GUIDANCE = '''Product photos are available from the existing Dropbox tags, not from web search.
Only request photos when the customer asks to see products/examples/photos or accepts an offer to see them; use the conversation to resolve follow-ups. Do not send photos for unrelated questions, image-input tests, or a refusal.
Use all explicit product constraints from the request/context; never silently drop a requested model, make, material or color. At least one product tag is required. If the product is unclear, ask a concise question instead of searching.
Product tags: mats=коврики, bag=сумки, suitcase=чемоданы, suitbag=сумка для костюма, trunk=коврик в багажник, trunkbox=органайзер, luggage=комплект органайзеров, keycase=чехол на автоключ, keybox=кейс для ключей, watchcase, pillow, seatscape, wallet, notebook, statuette, shoehorn, beltplugs, nametag, pets, booster, seat=автокресло, shell=защита спинок, painting, helmet, iphonecase, backpack, other.
Bag models: lusso, corsa, corsamini, corsapro, martello, diamante, elegantemini, elegante, monte, laptop, business, cosmetic, shoebag. Mats: 2d, 3d.
Materials: leather (covers both natural AND eco-leather, do not claim which), alcantara, wool, velour, carbon, exotic. Colors: red, black, blue (all blue shades), purple, yellow, white, grey (not gray), green, orange, brown, pink; these describe MAIN material colors, not stitching/lining/small accents.
Car makes/models use lowercase joined names: bmw, mercedes, audi, landrover, lamborghini, porsche, rollsroyce, bentley, x5, 7series, gls, gclass, landcruiser, etc. custom means no car branding, not any custom order. Optional content preference: studio, life, prof.
Tags are exact AND filters, without #. Do not invent a year tag or treat a car make/model tag as fitment confirmation. If the request depends on unrepresented details (exact shade, stitching, dimensions, year fitment, natural versus eco-leather), clarify or explicitly say they need confirmation; tagged examples are not verified exact matches for these details.
Only real finished Esteem product photos are sent: AI renders, before pictures, China products and design projects are excluded. One tagged hero image per unique product is the intended selection. Never assume every photo in a folder shows the same product.
Tags are company metadata, not independent visual verification. A black tag does not mean solid black or no other colors; present tagged examples without claiming an exact shade, all-black design, or unseen details.
'''


class PhotoError(RuntimeError):
    pass


def clean_tags(tags):
    if not isinstance(tags, list) or not 1 <= len(tags) <= 12:
        raise PhotoError('Supply 1–12 exact tags')
    if any(not isinstance(t, str) or not re.fullmatch('[a-z0-9]{1,40}', t) for t in tags):
        raise PhotoError('Invalid tag')
    tags = list(dict.fromkeys(tags))
    if not PRODUCTS.intersection(tags) or EXCLUDED.intersection(tags):
        raise PhotoError('A supported finished-product tag is required')
    return tags


def in_root(path):
    return isinstance(path, str) and path.lower().startswith(ROOT.lower() + '/')


class DropboxPhotos:
    def __init__(self, state=None, opener=urlopen):
        state = state or STATE
        self.state, self.opener = Path(state), opener
        self.cache = self.state/'photo-cache'

    def token(self):
        with (self.state/'dropbox-token.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            path = self.state/'dropbox-token.json'
            token = json.loads(path.read_text())
            if token.get('root_path') != ROOT:
                raise PhotoError('Unexpected Dropbox root')
            if token.get('expires_at', 0) < time.time() + 120:
                req = Request('https://api.dropboxapi.com/oauth2/token', data=urlencode({
                    'grant_type':'refresh_token', 'client_id':token['client_id'],
                    'refresh_token':token['refresh_token']}).encode(),
                    headers={'Content-Type':'application/x-www-form-urlencoded'})
                try:
                    with self.opener(req, timeout=30) as r: fresh = json.load(r)
                except Exception:
                    raise PhotoError('Dropbox authorization unavailable') from None
                token.update(fresh)
                token['expires_at'] = time.time() + fresh['expires_in']
                tmp = path.with_suffix('.tmp')
                tmp.write_text(json.dumps(token)); tmp.chmod(0o600); tmp.replace(path)
            return token['access_token']

    def rpc(self, route, payload):
        if route not in {'files/search_v2','files/search/continue_v2','files/tags/get','files/get_metadata'}:
            raise PhotoError('Unsupported Dropbox operation')
        req = Request('https://api.dropboxapi.com/2/'+route, data=json.dumps(payload).encode(),
                      headers={'Authorization':'Bearer '+self.token(), 'Content-Type':'application/json'})
        try:
            with self.opener(req, timeout=35) as r: return json.load(r)
        except Exception:
            raise PhotoError('Dropbox search unavailable') from None

    def tags_for(self, files):
        paths = [f['path_display'] for f in files if in_root(f.get('path_display'))]
        if not paths: return {}
        data = self.rpc('files/tags/get', {'paths':paths})
        return {row['path'].lower():{x['tag_text'] for x in row.get('tags',[]) if x.get('.tag')=='user_generated_tag'}
                for row in data['paths_to_tags']}

    def search(self, tags, count=3, exclude_ids=()):
        tags = clean_tags(tags)
        if type(count) is not int or not 1 <= count <= 5: raise PhotoError('Select 1–5 photos')
        excluded = set(exclude_ids)
        # Search one selective tag, then verify every required tag. Dropbox multi-tag search can be OR.
        primary = next((t for t in tags if t in MODELS), None)
        primary = primary or next((t for t in tags if t not in PRODUCTS|MATERIALS|COLORS|{'studio','life','prof'}), tags[0])
        data = self.rpc('files/search_v2', {'query':'#'+primary, 'options':{'path':ROOT,'max_results':100}})
        seen, found, pages = set(), [], 0
        while True:
            pages += 1
            files = []
            for match in data.get('matches',[]):
                m = match.get('metadata',{}); m = m.get('metadata',m)
                if (m.get('.tag') == 'file' and in_root(m.get('path_display')) and m.get('id') not in seen
                        and Path(m.get('name','')).suffix.lower() in {'.jpg','.jpeg','.png','.webp','.heic','.heif','.dng'}
                        and m.get('id') not in excluded and m.get('is_downloadable',True)):
                    seen.add(m['id']); files.append(m)
            actual = self.tags_for(files)
            for m in files:
                present = actual.get(m['path_display'].lower(),set())
                if set(tags).issubset(present) and not EXCLUDED.intersection(present):
                    found.append({**m,'tags':sorted(present)})
            enough = len(found) >= count
            if enough or not data.get('has_more'): break
            if pages >= 10:
                raise PhotoError('Photo search limit reached before completing selection')
            data = self.rpc('files/search/continue_v2', {'cursor':data['cursor']})
        found.sort(key=lambda m: ('studio' not in m['tags'], 'prof' not in m['tags'], m['path_display']))
        # Prefer distinct product folders rather than multiple angles of the same example.
        selected, folders = [], set()
        for m in found:
            folder = str(Path(m['path_display']).parent)
            if folder not in folders:
                selected.append(m); folders.add(folder)
            if len(selected) == count: break
        # If fewer distinct folders exist, fill the batch with other tagged photos.
        selected_ids={m['id'] for m in selected}
        for m in found:
            if len(selected)==count: break
            if m['id'] not in selected_ids:
                selected.append(m);selected_ids.add(m['id'])
        return selected

    def content(self, route, payload):
        req = Request('https://content.dropboxapi.com/2/'+route, data=b'', headers={
            'Authorization':'Bearer '+self.token(), 'Dropbox-API-Arg':json.dumps(payload,ensure_ascii=True)})
        try:
            with self.opener(req, timeout=60) as r: data = r.read(8*1024*1024+1)
        except Exception:
            raise PhotoError('Photo download unavailable') from None
        if not 0 < len(data) <= 8*1024*1024: raise PhotoError('Photo exceeds delivery size limit')
        return data

    def download(self, asset, required_tags):
        fresh = self.rpc('files/get_metadata', {'path':asset['id']})
        if fresh.get('.tag') != 'file' or not in_root(fresh.get('path_display')):
            raise PhotoError('Photo is outside the authorized library')
        tags = self.tags_for([fresh]).get(fresh['path_display'].lower(),set())
        if not set(required_tags).issubset(tags) or EXCLUDED.intersection(tags):
            raise PhotoError('Photo tags changed')
        key = hashlib.sha256((fresh['id']+fresh.get('rev','')+'photo-v1').encode()).hexdigest()
        self.cache.mkdir(mode=0o700, parents=True, exist_ok=True)
        with (self.state/'photo-cache.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            for suffix in ('.jpg','.png'):
                dest = self.cache/(key+suffix)
                if dest.is_file():
                    os.utime(dest,None)
                    return str(dest)
            try:
                data = self.content('files/get_thumbnail_v2', {'resource':{'.tag':'path','path':fresh['id']},
                    'format':'jpeg','size':'w1024h768','mode':'fitone_bestfit'})
            except PhotoError:
                if Path(fresh['name']).suffix.lower() not in {'.jpg','.jpeg','.png'} or fresh.get('size',0)>8*1024*1024:
                    raise
                data = self.content('files/download', {'path':fresh['id']})
            suffix = '.jpg' if data.startswith(b'\xff\xd8\xff') else '.png' if data.startswith(b'\x89PNG\r\n\x1a\n') else None
            if suffix is None: raise PhotoError('Dropbox did not return a supported image')
            existing = list(self.cache.glob('*'))
            total = sum(p.stat().st_size for p in existing if p.is_file())
            for old in sorted(existing, key=lambda p:p.stat().st_mtime):
                if total+len(data) <= 512*1024*1024: break
                if old.is_file() and time.time()-old.stat().st_mtime>86400:
                    total-=old.stat().st_size; old.unlink()
            if total+len(data)>512*1024*1024: raise PhotoError('Photo cache capacity reached')
            dest=self.cache/(key+suffix);tmp=dest.with_suffix('.tmp')
            tmp.write_bytes(data);tmp.chmod(0o600);tmp.replace(dest)
            return str(dest)

    def prepare(self, tags, count=3, exclude_ids=()):
        tags=clean_tags(tags)
        excluded=set(exclude_ids);ready=[];attempts=0;failed=False
        if type(count) is not int or not 1<=count<=5: raise PhotoError('Select 1–5 photos')
        while len(ready)<count and attempts<count*3:
            matches=self.search(tags,count-len(ready),exclude_ids=excluded)
            if not matches: break
            for asset in matches:
                excluded.add(asset['id']);attempts+=1
                try:
                    path=self.download(asset,tags)
                    ready.append({'id':asset['id'],'path':path,'tags':asset['tags']})
                except PhotoError:
                    failed=True
        if not ready and failed: raise PhotoError('Matching photos could not be downloaded')
        return ready


def pack_reply(text, photos, search_tags=None):
    if not photos: return text
    if len(text)>1000: text=text[:997]+'…'
    data={'text':text,'photos':photos}
    if search_tags is not None: data['search_tags']=clean_tags(search_tags)
    return PREFIX+json.dumps(data,ensure_ascii=False)


def unpack_reply(reply, state=None):
    state = state or STATE
    if not isinstance(reply,str) or not reply.startswith(PREFIX): return reply, []
    data=json.loads(reply[len(PREFIX):])
    if not isinstance(data.get('text'),str) or not isinstance(data.get('photos'),list) or not 1<=len(data['photos'])<=5:
        raise PhotoError('Invalid prepared photo reply')
    photos=data['photos']
    for photo in photos:
        path=Path(photo['path'])
        if path.parent.resolve() != (Path(state)/'photo-cache').resolve() or not re.fullmatch(r'[a-f0-9]{64}\.(jpg|png)',path.name):
            raise PhotoError('Invalid prepared photo path')
        if not path.is_file(): raise PhotoError('Prepared photo no longer available')
    return data['text'],photos


def history_text(reply):
    if not isinstance(reply,str) or not reply.startswith(PREFIX): return reply
    data=json.loads(reply[len(PREFIX):])
    return data['text']+'\n[Product photos attached: '+ '; '.join(', '.join(p['tags']) for p in data['photos'])+']'


def selection_context(replies):
    """Recover per-chat selections from durable jobs, independently of summaries/cache."""
    excluded=set();last_tags=[]
    for reply in replies:
        if not isinstance(reply,str) or not reply.startswith(PREFIX): continue
        data=json.loads(reply[len(PREFIX):])
        excluded.update(p['id'] for p in data['photos'] if isinstance(p.get('id'),str))
        if data.get('search_tags'): last_tags=clean_tags(data['search_tags'])
    return {'exclude_ids':sorted(excluded),'last_search_tags':last_tags}
