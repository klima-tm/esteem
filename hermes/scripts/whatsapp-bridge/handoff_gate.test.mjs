import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { AsyncLocalStorage } from 'node:async_hooks';

function setup({allowed=true,permit=true}={}) {
  const full=fs.readFileSync(new URL('./bridge.js',import.meta.url),'utf8');
  const source=full.slice(full.indexOf('const esteemSendContext'),full.indexOf('function formatOutgoingMessage'));
  const sent=[],requests=[];
  const box={AsyncLocalStorage,process:{env:{ESTEEM_HANDOFF_ENABLED:'true'}},
    readFileSync:()=> 'test-token',setTimeout,clearTimeout,AbortSignal,
    SEND_TIMEOUT_MS:1000,enqueueSend:fn=>fn(),
    sock:{sendMessage:async (...args)=>{sent.push(args);return {id:1};}},
    fetch:async (url,options)=>{
      const payload=JSON.parse(options.body);requests.push({url,payload});
      return {ok:true,json:async()=>url.endsWith('/state')?{allowed,mode:allowed?'active':'human'}:
        url.endsWith('/begin-send')?{allowed:permit,token:'test-lease'}:{ok:true}};
    }};
  vm.runInNewContext(source+';globalThis.api={sendWithTimeout,esteemDispatched,esteemSendContext}',box);
  return {api:box.api,sent,requests};
}
test('takeover blocks WhatsApp AI sends before reaching Baileys',async()=>{
  const {api,sent}=setup({allowed:false});
  await assert.rejects(api.sendWithTimeout('chat',{text:'AI reply'}),/paused/);
  assert.equal(sent.length,0);
});
test('takeover between preliminary check and final permit still blocks',async()=>{
  const {api,sent}=setup({permit:false});
  await assert.rejects(api.sendWithTimeout('chat',{text:'AI reply'}),/paused/);
  assert.equal(sent.length,0);
});
test('approved manager answer can be sent during takeover',async()=>{
  const {api,sent}=setup({allowed:false});
  await api.esteemSendContext.run(true,()=>api.sendWithTimeout('chat',{text:'Manager reply'}));
  assert.equal(sent.length,1);
});
test('AI delivery carries original request stamp and releases its permit',async()=>{
  const {api,sent,requests}=setup();
  api.esteemDispatched.set('chat',{mid:'customer-id',stamp:123});
  await api.sendWithTimeout('chat',{text:'AI reply'});
  assert.equal(sent.length,1);
  const begin=requests.find(r=>r.url.endsWith('/begin-send'));
  assert.equal(begin.payload.stamp,123);assert.equal(begin.payload.source,'customer-id');
  assert.ok(requests.some(r=>r.url.endsWith('/end-send')));
});
