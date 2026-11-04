// Run with: node --test assistant/test_ticket_form.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { runInNewContext } = require('node:vm');
const source = readFileSync(`${__dirname}/static/ticket-form.js`, 'utf8');

function setup({ building = 'A', room = '1', empty = false, error = false } = {}) {
  const events = {};
  const windowEvents = {};
  const attributes = {};
  const choices = empty ? [] : [
    { value: '1', dataset: { building: 'A' } },
    { value: '2', dataset: { building: 'B' } },
    { value: '3', dataset: { building: 'A' } },
  ];
  const campus = { value: building, addEventListener: (name, fn) => { events[name] = fn; } };
  let selected = room;
  const rooms = {
    options: [{ value: '', dataset: {} }, ...choices], disabled: false,
    get value() { return selected; },
    set value(value) { selected = this.options.some(option => option.value === value) ? value : ''; },
    replaceChildren(option) { this.options = [option]; selected = option.value; },
    add(option) { this.options.push(option); },
  };
  const button = { disabled: empty, textContent: 'Отправить заявку' };
  const errorNode = { focused: false, focus() { this.focused = true; } };
  const ticket = {
    elements: { building: campus, room_id: rooms },
    addEventListener: (name, fn) => { events[name] = fn; },
    setAttribute: (name, value) => { attributes[name] = value; },
    removeAttribute: name => { delete attributes[name]; },
  };
  const document = { getElementById: id => ({ 'ticket-form': ticket, 'submit-ticket': button, 'form-error': error ? errorNode : null })[id] };
  function Option(text, value) { this.text = text; this.value = value; this.dataset = {}; }
  runInNewContext(source, { document, window: { addEventListener: (name, fn) => { windowEvents[name] = fn; } }, Option });
  const submit = () => { const event = { prevented: false, preventDefault() { this.prevented = true; } }; events.submit(event); return event; };
  return { campus, rooms, button, attributes, errorNode, events, windowEvents, submit };
}

test('QR-selected room survives initialization and other buildings are filtered', () => {
  const page = setup();
  assert.equal(page.rooms.value, '1');
  assert.deepEqual(Array.from(page.rooms.options, o => o.value), ['', '1', '3']);
  assert.equal(page.rooms.disabled, false);
});

test('changing buildings clears the old room and restores its available options', () => {
  const page = setup();
  page.campus.value = 'B'; page.events.change();
  assert.equal(page.rooms.value, '');
  assert.deepEqual(Array.from(page.rooms.options, o => o.value), ['', '2']);
  page.rooms.value = '2';
  page.campus.value = 'A'; page.events.change();
  assert.equal(page.rooms.value, '');
  assert.deepEqual(Array.from(page.rooms.options, o => o.value), ['', '1', '3']);
  page.campus.value = ''; page.events.change();
  assert.equal(page.rooms.disabled, true);
});

test('programmatic submit event is allowed once and repeat is blocked until pageshow', () => {
  const page = setup();
  assert.equal(page.submit().prevented, false);
  assert.equal(page.button.disabled, true);
  assert.equal(page.attributes['aria-busy'], 'true');
  assert.equal(page.submit().prevented, true);
  page.windowEvents.pageshow();
  assert.equal(page.button.disabled, false);
  assert.equal(page.attributes['aria-busy'], undefined);
  assert.equal(page.rooms.value, '1');
  assert.equal(page.submit().prevented, false);
});

test('pageshow does not enable submission when no rooms exist', () => {
  const page = setup({ building: '', room: '', empty: true });
  page.windowEvents.pageshow();
  assert.equal(page.button.disabled, true);
  assert.equal(page.rooms.disabled, true);
});

test('server error receives focus and prefilled room remains available', () => {
  const page = setup({ error: true });
  assert.equal(page.errorNode.focused, true);
  assert.equal(page.rooms.value, '1');
});
