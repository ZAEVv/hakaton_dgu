(() => {
  const input = document.getElementById('ai-message');
  const send = document.getElementById('ai-send');
  const log = document.getElementById('chat-messages');
  const locationBox = document.getElementById('chat-location');
  const location = document.getElementById('chat-room');
  const submit = document.getElementById('chat-send-ticket');
  const form = document.getElementById('ticket-form');
  if (!input || !send || !log || !form) return;
  const csrf = form.elements.csrf_token.value;
  let messages = [], draft = null, busy = false, pending = false;
  function say(text, who = 'assistant') {
    const p = document.createElement('p');
    p.className = `chat-bubble ${who}-bubble`;
    p.textContent = text;
    log.appendChild(p);
    p.scrollIntoView({block: 'nearest'});
  }
  async function createTicket() {
    if (!draft || busy || pending) return;
    if (!location.value) { say('Выберите место из списка, чтобы я смог отправить заявку.'); return; }
    const selected = location.selectedOptions[0];
    form.elements.building.value = selected.dataset.building;
    form.elements.building.dispatchEvent(new Event('change'));
    form.elements.room_id.value = location.value;
    form.elements.category.value = draft.category || 'Другое';
    form.elements.description.value = draft.draft;
    const body = new FormData(form);
    busy = true; pending = true; send.disabled = submit.disabled = true;
    say('Отправляю заявку сотрудникам…');
    try {
      const response = await fetch(form.action || '/', {method:'POST', body, credentials:'same-origin'});
      if (!response.ok || !response.redirected || !new URL(response.url).pathname.startsWith('/account/tickets/')) throw new Error('Не удалось отправить заявку. Проверьте данные и попробуйте ещё раз.');
      const link = document.createElement('a');
      link.href = response.url; link.textContent = 'Открыть заявку и переписку';
      say('Заявка отправлена. Сотрудник увидит её в своей панели.');
      log.appendChild(link);
      draft = null; messages = []; locationBox.hidden = true;
      // A new key is required for a different request; reload gives a new key.
      send.disabled = true; input.disabled = true;
      say('Чтобы создать ещё одну заявку, обновите страницу.');
    } catch (error) {
      pending = false;
      say(error.message || 'Ошибка отправки. Попробуйте ещё раз.');
      send.disabled = false;
    } finally { busy = false; submit.disabled = false; }
  }
  send.addEventListener('click', async () => {
    const text = input.value.trim();
    if (!text || busy || pending) return;
    say(text, 'user'); input.value = ''; messages.push(text);
    const combined = messages.join('\n').slice(-2000);
    busy = true; send.disabled = true;
    try {
      const response = await fetch('/api/assistant', {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json','X-CSRF-Token':csrf}, body:JSON.stringify({message:combined})});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Помощник временно недоступен.');
      if (data.answer) say(data.answer);
      if (data.question) say(data.question);
      if (data.source) say(`Источник: ${data.source}`);
      if (data.type === 'danger') { draft = null; messages = []; locationBox.hidden = true; }
      if (data.type === 'question') messages = [];
      if (data.type === 'fault' && data.draft) {
        draft = data;
        const qrRoom = form.elements.room_id.value;
        if (qrRoom && Array.from(location.options).some(o => o.value === qrRoom)) location.value = qrRoom;
        locationBox.hidden = false;
        if (!location.value) say('Где возникла проблема? Выберите корпус и помещение из списка.');
      }
    } catch (error) { say(error.message || 'Помощник недоступен. Можно заполнить заявку вручную ниже.'); }
    finally { busy = false; send.disabled = false; }
    if (draft && location.value) await createTicket();
  });
  submit.addEventListener('click', createTicket);
})();
