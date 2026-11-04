(() => {
  const message = document.getElementById('ai-message');
  const send = document.getElementById('ai-send');
  const result = document.getElementById('ai-result');
  if (!message || !send || !result) return;
  const answer = document.getElementById('ai-answer');
  const question = document.getElementById('ai-question');
  const source = document.getElementById('ai-source');
  const use = document.getElementById('ai-use');
  let draft = null;
  send.addEventListener('click', async () => {
    const text = message.value.trim();
    result.hidden = false;
    question.textContent = '';
    source.textContent = '';
    use.hidden = true;
    draft = null;
    if (!text) { answer.textContent = 'Введите вопрос или опишите проблему.'; return; }
    const csrf = document.querySelector('#ticket-form input[name="csrf_token"]');
    if (!csrf) { answer.textContent = 'Не удалось проверить форму. Обновите страницу.'; return; }
    send.disabled = true;
    answer.textContent = 'Помощник обрабатывает запрос…';
    try {
      const response = await fetch('/api/assistant', {
        method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf.value},
        body: JSON.stringify({message: text})
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Помощник временно недоступен. Вы можете заполнить заявку вручную.');
      answer.textContent = data.answer || '';
      question.textContent = data.question || '';
      source.textContent = data.source ? `Источник: ${data.source}` : '';
      if (data.type === 'fault' && data.draft) { draft = data; use.hidden = false; }
    } catch (error) {
      answer.textContent = error.message || 'Помощник временно недоступен. Вы можете заполнить заявку вручную.';
    } finally { send.disabled = false; }
  });
  use.addEventListener('click', () => {
    if (!draft) return;
    const description = document.getElementById('description');
    const category = document.getElementById('category');
    if (description) description.value = draft.draft;
    if (category && draft.category && Array.from(category.options).some(option => option.value === draft.category)) category.value = draft.category;
    if (description) description.focus();
    use.hidden = true;
  });
})();
