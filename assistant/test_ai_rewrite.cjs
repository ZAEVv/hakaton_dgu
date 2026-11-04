const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
// Reuse only the existing DOM fixture, never register or alter the shared tests.
const fixture = fs.readFileSync(path.join(__dirname, 'test_ai_frontend.cjs'), 'utf8').split("test('QR prepares")[0];
const ctx = {require, __dirname, console, URL};
vm.runInNewContext(fixture + '\nthis.harness = harness; this.message = message;', ctx);
const {harness, message} = ctx;

test('unsent text survives reload', async () => {
  const store = {}; const h = harness({store});
  h.ids['ai-message'].value = 'Незаконченное сообщение';
  await h.ids['ai-message'].emit('input');
  assert.equal(harness({store}).ids['ai-message'].value, 'Незаконченное сообщение');
});
test('removed room cannot be sent even with a stale selected value', async () => {
  const h = harness({qr:'1'}); await message(h, 'Не горит свет');
  h.ids['chat-room'].options.splice(1,1);
  await h.ids['chat-send-ticket'].emit('click');
  assert.equal(h.calls.filter(c=>c.url==='/').length, 0);
});
test('disabled room cannot be sent', async () => {
  const h = harness({qr:'1'}); await message(h, 'Не горит свет');
  h.ids['chat-room'].options[1].disabled = true;
  await h.ids['chat-send-ticket'].emit('click');
  assert.equal(h.calls.filter(c=>c.url==='/').length, 0);
});
test('invalid ticket redirect preserves retry state', async () => {
  const h = harness({qr:'1'}); await message(h, 'Не горит свет');
  h.setTicketHandler(async()=>({ok:true,redirected:true,url:'http://localhost/login'}));
  await h.ids['chat-send-ticket'].click();
  assert.equal(h.ids['chat-description'].value, 'Не горит свет');
  assert.equal(JSON.parse(h.store['college-chat-1']).requestKey, 'uuid');
});
test('assistant request includes csrf and same-origin credentials', async () => {
  const h = harness(); await message(h,'Не горит свет');
  const request = h.calls.find(c=>c.url==='/api/assistant');
  assert.equal(request.opts.headers['X-CSRF-Token'], 'csrf');
  assert.equal(request.opts.credentials, 'same-origin');
});


test('disabled room selector blocks submission', async () => {
  const h = harness({qr:'1'}); await message(h,'Не горит свет');
  h.ids['chat-room'].disabled = true;
  await h.ids['chat-send-ticket'].emit('click');
  assert.equal(h.calls.filter(c=>c.url==='/').length, 0);
});
test('failed assistant check retains draft and urgent details after reload', async () => {
  const store={}; const h=harness({qr:'1',store}); await message(h,'Не горит свет');
  h.setAssistantHandler(async()=>{throw Error('offline')}); await message(h,'Пожар и дым');
  const restored=harness({store});
  assert.equal(restored.ids['chat-description'].value,'Не горит свет\nПожар и дым');
  assert.equal(restored.ids['chat-room'].value,'1');
  assert.ok(restored.ids['chat-messages'].children.some(c=>/112/.test(c.textContent)));
  assert.equal(restored.calls.length,0);
});
test('unsent composer stays local and storage warning is visible', async () => {
  const h=harness(); h.ids['ai-message'].value='Частный текст';
  await h.ids['ai-message'].emit('input');
  assert.equal(h.calls.length,0);
  assert.ok(h.ids['chat-messages'].children.some(c=>/вкладк/.test(c.textContent) && /сохраняют/.test(c.textContent)));
});


test('storage write failure warns visibly without blocking ticket submission', async () => {
  const store = new Proxy({}, {set() { throw Error('quota'); }});
  const h = harness({qr:'1',store}); await message(h,'Не горит свет');
  assert.ok(h.ids['chat-messages'].children.some(c=>/черновик/i.test(c.textContent) && /неотправленн/i.test(c.textContent) && /не восстанов/i.test(c.textContent)));
  await h.ids['chat-send-ticket'].click();
  assert.equal(h.calls.filter(c=>c.url==='/').length,1);
});

test('oversized legacy transcript restores the draft and unsent text', async () => {
  const transcript=Array.from({length:1001},(_,i)=>({who:'user',text:`сообщение ${i}`}));
  const store={'college-chat-1':JSON.stringify({transcript, messages:['история'], requestKey:'old-key', room:'1', composer:'ещё текст', draft:{type:'fault',category:'Электрика',draft:'важный черновик'}})};
  const restored=harness({store});
  assert.equal(restored.ids['chat-description'].value,'важный черновик');
  assert.equal(restored.ids['ai-message'].value,'ещё текст');
  assert.equal(restored.fields.request_key.value,'old-key');
  await restored.ids['ai-message'].emit('input');
  assert.ok(JSON.parse(store['college-chat-1']).transcript.length <= 1000);
});


test('history trimming retains earlier emergency context for a later notification', async () => {
  const transcript=[{who:'user',text:'Искрит провод'},...Array.from({length:1001},(_,i)=>({who:'assistant',text:`ответ ${i}`}))];
  const store={'college-chat-1':JSON.stringify({transcript,messages:[],requestKey:'uuid'})};
  const h=harness({store,response:{type:'question',answer:'Хорошо'}});
  h.ids['ai-message'].value='ожидание'; await h.ids['ai-message'].emit('input');
  const restored=harness({store,response:{type:'question',answer:'Хорошо'}});
  await message(restored,'Сообщите сотрудникам');
  assert.equal(restored.ids['chat-description'].value,'Искрит провод');
});

test('storage read failure warns immediately', () => {
  const store=new Proxy({}, {get() { throw Error('denied'); }});
  const h=harness({store});
  assert.ok(h.ids['chat-messages'].children.some(c=>/черновик/i.test(c.textContent) && /неотправленн/i.test(c.textContent) && /не восстанов/i.test(c.textContent)));
});


test('old overflow detail remains available after history compaction and reload', async () => {
  const transcript=[{who:'assistant',text:'Дополнение не поместилось в описание и осталось в переписке.'},{who:'user',text:'Важное дополнение'},...Array.from({length:1001},(_,i)=>({who:'assistant',text:`ответ ${i}`}))];
  const store={'college-chat-1':JSON.stringify({transcript,messages:[],requestKey:'uuid',draft:{type:'fault',category:'Электрика',draft:'описание',overflow:true}})};
  const h=harness({store}); h.ids['ai-message'].value='новый текст'; await h.ids['ai-message'].emit('input');
  const restored=harness({store});
  assert.ok(restored.ids['chat-messages'].children.some(c=>c.textContent==='Важное дополнение'));
  await restored.ids['chat-send-ticket'].click();
  assert.equal(restored.calls.filter(c=>c.url==='/').length,0);
});


test('more than 1000 overflow context messages do not prevent saving the edited draft', async () => {
  const transcript=Array.from({length:1001},(_,i)=>({who:'user',text:`деталь ${i}`}));
  const store={'college-chat-1':JSON.stringify({transcript,messages:[],requestKey:'uuid',draft:{type:'fault',category:'Электрика',draft:'старый',overflow:true}})};
  const h=harness({store}); h.ids['ai-message'].value='новый текст'; await h.ids['ai-message'].emit('input');
  const restored=harness({store});
  assert.equal(restored.ids['ai-message'].value,'новый текст');
  assert.ok(restored.ids['chat-messages'].children.some(c=>c.textContent==='деталь 0'));
  assert.ok(JSON.parse(store['college-chat-1']).transcript.length<=1000);
});


test('history compaction warns that older messages will not all return', async () => {
  const transcript=Array.from({length:1001},(_,i)=>({who:'assistant',text:`ответ ${i}`}));
  const store={'college-chat-1':JSON.stringify({transcript,requestKey:'uuid'})};
  const h=harness({store}); await h.ids['ai-message'].emit('input');
  assert.ok(h.ids['chat-messages'].children.some(c=>/старые сообщения/i.test(c.textContent) && /не восстанов/i.test(c.textContent)));
});
