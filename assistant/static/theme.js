(() => {
  'use strict';
  const key = 'college-theme';
  const system = window.matchMedia('(prefers-color-scheme: dark)');
  const valid = value => value === 'light' || value === 'dark';
  let preference;
  try { preference = localStorage.getItem(key); } catch (_) { /* Storage may be blocked. */ }
  const apply = theme => {
    document.documentElement.dataset.theme = theme;
    document.querySelectorAll('[data-theme-choice]').forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.themeChoice === theme));
    });
  };
  const refresh = () => apply(valid(preference) ? preference : (system.matches ? 'dark' : 'light'));
  refresh();
  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.theme-switch').forEach(control => { control.hidden = false; });
    document.querySelectorAll('[data-theme-choice]').forEach(button => {
      button.addEventListener('click', () => {
        preference = button.dataset.themeChoice;
        try { localStorage.setItem(key, preference); } catch (_) { /* Keep the choice for this page. */ }
        refresh();
      });
    });
    refresh();
  });
  system.addEventListener('change', refresh);
  window.addEventListener('storage', event => {
    if (event.key === key || event.key === null) { preference = event.newValue; refresh(); }
  });
})();
