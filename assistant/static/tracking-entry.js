(() => {
  const token = window.location.hash.slice(1);
  const input = document.getElementById('link-token');
  if (input && /^[0-9a-f]{64}$/.test(token)) {
    input.value = token;
    // Fragments are never sent in HTTP requests; avoid keeping it in history.
    history.replaceState(null, '', window.location.pathname + window.location.search);
  }
  const code = document.getElementById('code');
  if (code && input && /^[0-9a-f]{64}$/.test(input.value)) {
    code.inputMode = 'numeric';
    code.maxLength = 3;
    code.pattern = '[0-9]{3}';
  }
})();
