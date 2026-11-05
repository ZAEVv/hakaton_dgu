const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const fixture = fs.readFileSync(path.join(__dirname, 'test_ai_frontend.cjs'), 'utf8').split("test('QR prepares")[0];
const ctx = {require, __dirname, console, URL};
vm.runInNewContext(fixture + '\nthis.harness = harness; this.message = message;', ctx);
const {harness, message} = ctx;

test('privacy notice is visible before entry and described by composer', () => {
  const html = fs.readFileSync(path.join(__dirname, 'tameplates/ai_assistant.html'), 'utf8');
  assert.match(html, /<p id="chat-privacy"[^>]*>[^<]*sessionStorage/);
  assert.match(html, /<textarea id="ai-message"[^>]*aria-describedby="[^"]*chat-privacy/);
});

test('draft fields cannot be edited while ticket submission is pending', async () => {
  const h = harness({qr:'1'}); await message(h, 'Не горит свет');
  let resolve; h.setTicketHandler(() => new Promise(r => resolve = r));
  const pending = h.ids['chat-send-ticket'].click();
  assert.equal(h.ids['chat-description'].disabled, true);
  assert.equal(h.ids['chat-category'].disabled, true);
  assert.equal(h.ids['chat-room'].disabled, true);
  resolve({ok:false,redirected:false,url:'http://localhost/'}); await pending;
  assert.equal(h.ids['chat-description'].disabled, false);
});
