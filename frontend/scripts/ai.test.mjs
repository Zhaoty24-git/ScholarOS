import test from 'node:test';
import assert from 'node:assert/strict';
import { ChatController, MODEL, PROVIDERS, DEFAULT_PROVIDER, safeError, questionWithContext } from '../src/ai/model.ts';

function fixture() {
  const calls = [], cancellations = [];
  let resolve, reject;
  const ready = { available: true, configured: true, persistent: false, provider: 'agnes-cn' };
  const transport = {
    async status() { return ready; },
    async configure(key, persist, provider) { return { ...ready, persistent: persist, provider }; },
    async remove() { return { ...ready, configured: false }; },
    send(id, messages, stream) { calls.push({ id, messages, stream }); return new Promise((a,b) => { resolve = a; reject = b; }); },
    async cancel(id) { cancellations.push(id); }, async chunks() { return () => {}; },
  };
  const controller = new ChatController(transport);
  return { controller, transport, calls, cancellations, answer: text => resolve({ content: text, truncated: false }), fail: code => reject({ code, message: 'synthetic private provider body' }) };
}
async function enabled() { const f=fixture(); await f.controller.refresh(); f.controller.consent(true); return f; }
test('default is verified domestic Agnes model and distinct /v1 bases', () => {
  assert.equal(MODEL,'agnes-3.0-flash'); assert.equal(DEFAULT_PROVIDER,'agnes-cn');
  assert.equal(PROVIDERS['agnes-cn'].baseUrl+'/chat/completions','https://api.agnes-ai.cn/v1/chat/completions');
  assert.equal(PROVIDERS['agnes-international'].baseUrl+'/chat/completions','https://apihub.agnes-ai.com/v1/chat/completions');
});
test('no consent means no call', async () => {const f=fixture();await f.controller.refresh();assert.equal(await f.controller.send('hello',null,false),false);assert.equal(f.calls.length,0);});
test('no key means no call', async () => {const f=await enabled();await f.controller.removeKey();assert.equal(await f.controller.send('hello',null,false),false);assert.equal(f.calls.length,0);});
test('no automatic attachment or fabricated sources', () => {assert.equal(questionWithContext(' explain ',null),'explain');});
test('chosen synthetic context is explicitly identified', () => {const s=questionWithContext('解释',{provenance:'synthetic_demo',label:'合成课程',text:'潮流计算'});assert.match(s,/不是真实课程/);assert.match(s,/没有检索文档/);});
test('user information is distinguished from demo', () => {assert.match(questionWithContext('解释',{provenance:'user_supplied',label:'笔记',text:'用户内容'}),/用户主动提供/);});
test('oversized questions fail before network', async () => {const f=await enabled();assert.equal(await f.controller.send('x'.repeat(6001),null,false),false);assert.equal(f.calls.length,0);});
test('successful multi-turn uses only complete history', async () => {const f=await enabled();const p=f.controller.send('问题1',null,false);f.answer('回答1');assert.equal(await p,true);const q=f.controller.send('问题2',null,true);assert.deepEqual(f.calls[1].messages,[{role:'user',content:'问题1'},{role:'assistant',content:'回答1'},{role:'user',content:'问题2'}]);assert.equal(f.calls[1].stream,true);f.answer('回答2');await q;});
test('pending requests cannot be submitted twice', async () => {const f=await enabled();const p=f.controller.send('one',null,false);assert.equal(await f.controller.send('two',null,false),false);assert.equal(f.calls.length,1);f.answer('answer');await p;});
test('stream chunks remain scoped to the active request', async () => {const f=await enabled();const p=f.controller.send('hello',null,true);f.controller.chunk('wrong','unsafe');f.controller.chunk(f.calls[0].id,'片段');assert.equal(f.controller.snapshot().sessions[0].visible[1].text,'片段');f.answer('完整回答');await p;assert.equal(f.controller.snapshot().sessions[0].history[1].content,'完整回答');});
test('cancel discards late completion and history', async () => {const f=await enabled();const p=f.controller.send('one',null,true);f.controller.chunk(f.calls[0].id,'partial');f.controller.cancel();f.answer('obsolete');assert.equal(await p,false);assert.equal(f.cancellations.length,1);assert.equal(f.controller.snapshot().sessions[0].history.length,0);assert.equal(f.controller.snapshot().sessions[0].visible[1].state,'incomplete');});
test('new sessions cancel and isolate context', async () => {const f=await enabled();const p=f.controller.send('old',null,false);f.controller.newSession();f.answer('obsolete');await p;assert.equal(f.controller.snapshot().sessions.length,2);assert.equal(f.controller.snapshot().sessions[1].visible.length,0);});
test('session switching restores only selected history', async () => {const f=await enabled();const first=f.controller.snapshot().selected;const p=f.controller.send('first',null,false);f.answer('answer');await p;f.controller.newSession();f.controller.select(first);assert.equal(f.controller.snapshot().sessions.find(s=>s.id===first).history.length,2);});
test('clear conversation removes completed and pending history', async () => {const f=await enabled();const p=f.controller.send('one',null,false);f.controller.clearSession();f.answer('late');await p;assert.equal(f.controller.snapshot().sessions[0].visible.length,0);});
test('delete key cancels requests, clears sessions and blocks later sends', async () => {const f=await enabled();const p=f.controller.send('one',null,false);await f.controller.removeKey();f.answer('late');await p;assert.equal(f.controller.snapshot().status.configured,false);assert.equal(f.controller.snapshot().sessions[0].history.length,0);assert.equal(await f.controller.send('two',null,false),false);});
test('changing provider/key resets previous conversation', async () => {const f=await enabled();const p=f.controller.send('one',null,false);f.answer('answer');await p;await f.controller.configure('synthetic-only-value',true,'agnes-international');assert.equal(f.controller.snapshot().sessions[0].history.length,0);assert.equal(f.controller.snapshot().status.provider,'agnes-international');});
for (const code of ['UNAUTHORIZED','RATE_LIMIT','SERVER','NETWORK','TIMEOUT','FORMAT','REDIRECT','STORAGE']) test(code+' is mapped without private body', async()=>{const f=await enabled();const p=f.controller.send('q',null,false);f.fail(code);assert.equal(await p,false);assert.ok(f.controller.snapshot().error);assert.doesNotMatch(f.controller.snapshot().error,/synthetic private/);assert.equal(f.controller.snapshot().sessions[0].history.length,0);});
test('unknown errors cannot echo keys or provider diagnostics',()=>assert.doesNotMatch(safeError({code:'OTHER',message:'private data'}),/private data/));
test('malformed successful responses are rejected',async()=>{const f=await enabled();const p=f.controller.send('q',null,false);f.answer('');assert.equal(await p,false);assert.equal(f.controller.snapshot().sessions[0].history.length,0);});
test('session memory is bounded', async()=>{const f=await enabled();for(let i=0;i<20;i++)f.controller.newSession();assert.equal(f.controller.snapshot().sessions.length,5);});
