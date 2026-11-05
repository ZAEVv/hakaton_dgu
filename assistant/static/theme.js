(() => {
  'use strict';

  const storageKey = 'college-theme';
  const media = window.matchMedia('(prefers-color-scheme: dark)');
  let choice = null;
  try {
    choice = localStorage.getItem(storageKey);
  } catch (_) {
    // A blocked storage must not prevent the page from using a theme.
  }

  function render() {
    const active = choice === 'light' || choice === 'dark'
      ? choice : (media.matches ? 'dark' : 'light');
    document.documentElement.dataset.theme = active;
    for (const element of document.querySelectorAll('[data-theme-choice]')) {
      element.setAttribute('aria-pressed', String(element.dataset.themeChoice === active));
    }
  }

  render();
  document.addEventListener('DOMContentLoaded', () => {
    for (const switcher of document.querySelectorAll('.theme-switch')) switcher.hidden = false;
    for (const element of document.querySelectorAll('[data-theme-choice]')) {
      element.addEventListener('click', () => {
        choice = element.dataset.themeChoice;
        try {
          localStorage.setItem(storageKey, choice);
        } catch (_) {
          // The selection remains active in this page.
        }
        render();
      });
    }
    render();
  });
  media.addEventListener('change', render);
  window.addEventListener('storage', event => {
    if (event.key !== storageKey && event.key !== null) return;
    choice = event.newValue;
    render();
  });
})();
