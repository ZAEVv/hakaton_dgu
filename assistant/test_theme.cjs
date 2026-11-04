// Run with: node --test assistant/test_theme.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { runInNewContext } = require('node:vm');
const source = readFileSync(`${__dirname}/static/theme.js`, 'utf8');

function setup({ stored = null, dark = false, blocked = false } = {}) {
  const events = {};
  const buttons = ['light', 'dark'].map(choice => ({
    dataset: { themeChoice: choice },
    setAttribute(name, value) { this[name] = value; },
    addEventListener(name, callback) { this[name] = callback; },
  }));
  const control = { hidden: true };
  const document = {
    documentElement: { dataset: {} },
    querySelectorAll: selector => selector === '.theme-switch' ? [control] : buttons,
    addEventListener: (name, callback) => { events[name] = callback; },
  };
  const system = { matches: dark, addEventListener: (name, callback) => { events.system = callback; } };
  runInNewContext(source, {
    document,
    window: { matchMedia: () => system, addEventListener: (name, callback) => { events[name] = callback; } },
    localStorage: {
      getItem() { if (blocked) throw Error('blocked'); return stored; },
      setItem(key, value) { if (blocked) throw Error('blocked'); stored = value; },
    },
  });
  events.DOMContentLoaded();
  return { document, buttons, control, events, system, stored: () => stored };
}

test('system theme, explicit choice, and accessible selected state', () => {
  const page = setup({ dark: true });
  assert.equal(page.document.documentElement.dataset.theme, 'dark');
  assert.equal(page.control.hidden, false);
  assert.equal(page.buttons[1]['aria-pressed'], 'true');
  page.buttons[0].click();
  assert.equal(page.stored(), 'light');
  assert.equal(page.buttons[0]['aria-pressed'], 'true');
  assert.equal(page.buttons[1]['aria-pressed'], 'false');
  page.events.system();
  assert.equal(page.document.documentElement.dataset.theme, 'light');
});

test('saved choice wins; invalid or absent choice follows system', () => {
  assert.equal(setup({ stored: 'light', dark: true }).document.documentElement.dataset.theme, 'light');
  const page = setup({ stored: 'invalid' });
  page.system.matches = true;
  page.events.system();
  assert.equal(page.document.documentElement.dataset.theme, 'dark');
});

test('blocked storage does not break controls', () => {
  const page = setup({ blocked: true });
  page.buttons[1].click();
  assert.equal(page.document.documentElement.dataset.theme, 'dark');
});

test('other tabs synchronize theme; clearing storage restores system preference', () => {
  const page = setup({ stored: 'light', dark: true });
  page.events.storage({ key: 'college-theme', newValue: 'dark' });
  assert.equal(page.buttons[1]['aria-pressed'], 'true');
  page.events.storage({ key: null, newValue: null });
  assert.equal(page.document.documentElement.dataset.theme, 'dark');
});
