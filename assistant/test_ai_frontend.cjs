const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const script = fs.readFileSync(__dirname + '/static/ai-assistant.js', 'utf8');
class Element {
  constructor(value = '') { this.value=value; this.hidden=false; this.disabled=false; this.dataset={}; this.options=[]; this.listeners={}; this.children=[]; }
  addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); }
  async emit(name, event={}) { for (const fn of this.listeners[name] || []) await fn(event); }
  click() { if (!this.disabled) return this.emit('click'); }
  appendChild(child) { this.children.push(child); }
  scrollIntoView() {}
  dispatchEvent(event) { this.emit(event.type, event); }
  get selectedOptions() { return this.options.filter(o => o.value === this.value); }
}
function harness({qr='', store={}, response={type:'fault', category:'Электрика', draft:'Не горит свет'}}={}) {
  const ids={}; for (const id of ['ai-message','ai-send','chat-messages','chat-location','chat-room','chat-send-ticket','ticket-form','chat-new','chat-description','chat-category']) ids[id]=new Element();
  ids['chat-location'].hidden=true;
  const option=(value,text,building='')=>({value,text,dataset:{building}});
  ids['chat-room'].options=[option('','Выберите место'),option('1','Корпус А — 101','Корпус А'),option('2','Корпус Б — 202','Корпус Б')];
  ids['chat-category'].options=[option('','Выберите категорию'),option('Электрика','Электрика'),option('Другое','Другое')];
  const fields={csrf_token:new Element('csrf'),request_key:new Element('uuid'),building:new Element(),room_id:new Element(qr),category:new Element(),description:new Element()};
  ids['ticket-form'].elements=fields; ids['ticket-form'].action='/';
  const calls=[]; let ticketHandler=async()=>({ok:true,redirected:true,url:'http://localhost/account/tickets/1'}); let assistantHandler=async()=>({ok:true,json:async()=>response});
  const fetch=async(url,opts)=>{calls.push({url,opts}); return url==='/api/assistant' ? assistantHandler() : ticketHandler();};
  const storage={getItem:k=>store[k]||null,setItem:(k,v)=>{store[k]=v},removeItem:k=>delete store[k]};
  const document={getElementById:id=>ids[id],querySelector:()=>({dataset:{chatOwner:'1'}}),createElement:()=>new Element()};
  class FormData { constructor(form) { this.values=Object.fromEntries(Object.entries(form.elements).map(([k,v])=>[k,v.value])); } set(k,v) {this.values[k]=v} delete(k) {delete this.values[k]} }
  vm.runInNewContext(script,{document,fetch,sessionStorage:storage,window:{location:{origin:'http://localhost'}},FormData,Event:class {constructor(type){this.type=type}},URL,console});
  return {ids,fields,calls,store,setTicketHandler:fn=>ticketHandler=fn,setAssistantHandler:fn=>assistantHandler=fn};
}
async function message(h,text) { h.ids['ai-message'].value=text; await h.ids['ai-send'].click(); }
test('QR prepares a draft without creating a ticket', async()=>{
  const h=harness({qr:'1'}); await message(h,'Не горит свет');
  assert.equal(h.calls.filter(c=>c.url==='/').length,0);
  assert.equal(h.ids['chat-room'].value,'1');
  assert.equal(h.ids['chat-description'].value,'Не горит свет');
  assert.equal(h.ids['chat-category'].value,'Электрика');
});

test('typing a room only updates the draft; confirmation sends edited fields and csrf', async()=>{
  const h=harness(); await message(h,'Не горит свет'); await message(h,'Корпус А — 101');
  assert.equal(h.calls.filter(c=>c.url==='/').length,0);
  h.ids['chat-description'].value='Исправленное описание'; await h.ids['chat-description'].emit('input');
  h.ids['chat-category'].value='Другое'; await h.ids['chat-category'].emit('change');
  await h.ids['chat-send-ticket'].click();
  const request=h.calls.find(c=>c.url==='/');
  assert.deepEqual(request.opts.body.values,{csrf_token:'csrf',request_key:'uuid',building:'Корпус А',room_id:'1',category:'Другое',description:'Исправленное описание'});
  assert.equal(h.fields.description.value,'');
});
test('danger with QR and reload never creates a ticket without confirmation', async()=>{
  const store={}; const h=harness({qr:'1',store,response:{type:'danger',answer:'Отойдите'}});
  await message(h,'Искрит провод'); assert.equal(h.calls.filter(c=>c.url==='/').length,0);
  h.ids['chat-description'].value='Искрит розетка'; await h.ids['chat-description'].emit('input');
  const restored=harness({store});
  assert.equal(restored.calls.length,0); assert.equal(restored.ids['chat-description'].value,'Искрит розетка');
  assert.equal(restored.ids['chat-room'].value,'1');
});
test('double click during submission sends only once', async()=>{
  const h=harness({qr:'1'}); await message(h,'Не горит свет');
  let resolve; h.setTicketHandler(()=>new Promise(r=>resolve=r));
  const first=h.ids['chat-send-ticket'].click(); await h.ids['chat-send-ticket'].click();
  assert.equal(h.calls.filter(c=>c.url==='/').length,1);
  resolve({ok:true,redirected:true,url:'http://localhost/account/tickets/1'}); await first;
});
test('failed submission preserves draft and request key for explicit retry', async()=>{
  const h=harness({qr:'1'}); await message(h,'Не горит свет');
  h.setTicketHandler(async()=>{throw Error('сеть');}); await h.ids['chat-send-ticket'].click();
  assert.equal(h.calls.filter(c=>c.url==='/').length,1);
  assert.equal(h.ids['chat-description'].value,'Не горит свет');
  h.setTicketHandler(async()=>({ok:true,redirected:true,url:'http://localhost/account/tickets/2'}));
  await h.ids['chat-send-ticket'].click();
  const requests=h.calls.filter(c=>c.url==='/'); assert.equal(requests.length,2);
  assert.equal(requests[0].opts.body.values.request_key,requests[1].opts.body.values.request_key);
});
test('missing description or location does not submit', async()=>{
  const h=harness(); await message(h,'Не горит свет'); await h.ids['chat-send-ticket'].click();
  h.ids['chat-room'].value='1'; h.ids['chat-description'].value='  '; await h.ids['chat-send-ticket'].click();
  assert.equal(h.calls.filter(c=>c.url==='/').length,0);
});

test('assistant API error leaves manual form available and does not create a ticket', async()=>{
  const h=harness({qr:'1'}); h.setAssistantHandler(async()=>{throw Error('сеть');});
  await message(h,'Не горит свет');
  assert.equal(h.calls.filter(c=>c.url==='/').length,0);
  assert.equal(h.ids['ticket-form'].hidden,false);
  assert.equal(h.ids['ai-send'].disabled,false);
});


test('new emergency during an open draft is assessed without replacing it', async()=>{
  const h=harness({qr:'1'}); await message(h,'Не горит свет');
  h.ids['chat-description'].value='Мой черновик'; await h.ids['chat-description'].emit('input');
  h.ids['chat-room'].value='2'; await h.ids['chat-room'].emit('change');
  h.setAssistantHandler(async()=>({ok:true,json:async()=>({type:'danger',answer:'Покиньте помещение и звоните 112'})}));
  await message(h,'Пожар и дым');
  const calls=h.calls.filter(c=>c.url==='/api/assistant');
  assert.equal(calls.length,2); assert.match(JSON.parse(calls[1].opts.body).message,/Пожар и дым/);
  assert.ok(h.ids['chat-messages'].children.some(c=>/112/.test(c.textContent)));
  assert.equal(h.ids['chat-description'].value,'Мой черновик\nПожар и дым');
  assert.equal(h.ids['chat-room'].value,'2');
  assert.equal(h.calls.filter(c=>c.url==='/').length,0);
  await h.ids['chat-send-ticket'].click();
  assert.match(h.calls.find(c=>c.url==='/').opts.body.values.description,/Пожар и дым/);
});

test('an API failure while a draft is open warns instead of silently discarding the message', async()=>{
  const h=harness(); await message(h,'Не горит свет');
  h.setAssistantHandler(async()=>{throw Error('сеть')});
  await message(h,'Пожар и дым');
  assert.equal(h.calls.filter(c=>c.url==='/api/assistant').length,2);
  assert.ok(h.ids['chat-messages'].children.some(c=>/112/.test(c.textContent)));
  assert.equal(h.ids['chat-description'].value,'Не горит свет\nПожар и дым');
  assert.equal(h.calls.filter(c=>c.url==='/').length,0);
});


test('notify after an emergency response preserves the original incident', async()=>{
  const h=harness({response:{type:'question',answer:'Отойдите'}});
  await message(h,'Искрит провод'); await message(h,'Сообщите сотрудникам');
  assert.equal(h.ids['chat-description'].value,'Искрит провод');
  assert.equal(h.ids['chat-location'].hidden,false);
  assert.equal(h.calls.filter(c=>c.url==='/').length,0);
});

test('initial emergency with unavailable API gives safety guidance', async()=>{
  const h=harness(); h.setAssistantHandler(async()=>{throw Error('сеть')});
  await message(h,'Пожар и дым');
  assert.ok(h.ids['chat-messages'].children.some(c=>/112/.test(c.textContent)));
});

test('additional message is added to the draft without changing QR room', async()=>{
  const h=harness({qr:'1'}); await message(h,'Не горит свет');
  await message(h,'Также пахнет газом');
  assert.equal(h.calls.filter(c=>c.url==='/api/assistant').length,2);
  assert.ok(h.ids['chat-messages'].children.some(c=>/проверьте/i.test(c.textContent)));
  assert.equal(h.ids['chat-room'].value,'1');
  assert.equal(h.ids['chat-description'].value,'Не горит свет\nТакже пахнет газом');
  assert.equal(h.calls.filter(c=>c.url==='/').length,0);
});


test('malformed assistant reply is not treated as a successful safety check', async()=>{
  const h=harness(); await message(h,'Не горит свет');
  h.setAssistantHandler(async()=>({ok:true,json:async()=>({})}));
  await message(h,'Пожар и дым');
  assert.ok(h.ids['chat-messages'].children.some(c=>/не удалось проверить/i.test(c.textContent) && /112/.test(c.textContent)));
  assert.equal(h.ids['chat-description'].value,'Не горит свет\nПожар и дым');
});


test('legitimate unclear response is displayed without a false API failure', async()=>{
  const h=harness({response:{type:'unclear',question:'Уточните проблему'}});
  await message(h,'Что случилось');
  assert.ok(h.ids['chat-messages'].children.some(c=>c.textContent==='Уточните проблему'));
  assert.ok(!h.ids['chat-messages'].children.some(c=>/не удалось проверить/i.test(c.textContent)));
});

test('overflow preserves the message and blocks submission until description is edited, even after reload', async()=>{
  const store={}; const h=harness({qr:'1',store}); await message(h,'Не горит свет');
  h.ids['chat-description'].value='x'.repeat(4995); await h.ids['chat-description'].emit('input');
  await message(h,'Пожар и дым');
  assert.equal(h.ids['chat-description'].value.length,4995);
  assert.ok(h.ids['chat-messages'].children.some(c=>/не поместилось/i.test(c.textContent)));
  const restored=harness({store}); await restored.ids['chat-send-ticket'].click();
  assert.equal(restored.calls.filter(c=>c.url==='/').length,0);
  restored.ids['chat-description'].value='Пожар и дым'; await restored.ids['chat-description'].emit('input');
  await restored.ids['chat-send-ticket'].click();
  assert.equal(restored.calls.filter(c=>c.url==='/').length,1);
});

test('room and notification commands do not become problem text; mixed details do', async()=>{
  const h=harness(); await message(h,'Не горит свет');
  await message(h,'Корпус А — 101'); await message(h,'Сообщи администратору');
  assert.equal(h.ids['chat-description'].value,'Не горит свет');
  assert.equal(h.ids['chat-room'].value,'1');
  await message(h,'Сообщи администратору, пожар и дым');
  assert.match(h.ids['chat-description'].value,/пожар и дым/i);
  assert.equal(h.calls.filter(c=>c.url==='/').length,0);
});

test('repeated identical addition is not duplicated', async()=>{
  const h=harness(); await message(h,'Не горит свет');
  await message(h,'Пожар и дым'); await message(h,'Пожар и дым');
  assert.equal(h.ids['chat-description'].value,'Не горит свет\nПожар и дым');
});
