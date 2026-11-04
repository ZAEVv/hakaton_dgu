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
  const reset = document.getElementById('chat-new');
  const owner = document.querySelector('.ai-assistant').dataset.chatOwner;
  const storageKey = `college-chat-${owner}`;
  let messages = [], draft = null, busy = false, pending = false, transcript = [], submittedUrl = null;
  function save() {
    try { sessionStorage.setItem(storageKey, JSON.stringify({messages, draft, transcript, submittedUrl, room:location.value, requestKey:form.elements.request_key.value})); } catch (_) { /* Continue without browser storage. */ }
  }
  function say(text, who = 'assistant') {
    const p = document.createElement('p');
    p.className = `chat-bubble ${who}-bubble`;
    p.textContent = text;
    log.appendChild(p);
    transcript.push({text, who});
    save();
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
      const number = new URL(response.url).pathname.split('/').pop();
      say(`Заявка № ${number} отправлена. Сотрудник увидит её в своей панели.`);
      link.className = 'chat-link';
      log.appendChild(link);
      draft = null; messages = []; locationBox.hidden = true;
      submittedUrl = response.url; reset.hidden = false; save();
      // A new key is required for a different request; reload gives a new key.
      send.disabled = true; input.disabled = true;
      say('Чтобы создать ещё одну заявку, нажмите «Начать новое обращение».');
    } catch (error) {
      pending = false;
      say(error.message || 'Ошибка отправки. Попробуйте ещё раз.');
      send.disabled = false;
    } finally { busy = false; submit.disabled = false; }
  }
  send.addEventListener('click', async () => {
    const text = input.value.trim();
    if (!text || busy || pending) return;
    draft = null; locationBox.hidden = true;
    say(text, 'user'); input.value = ''; messages.push(text); save();
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
        save();
        if (!location.value) say('Где возникла проблема? Выберите корпус и помещение из списка.');
      }
    } catch (error) { say(error.message || 'Помощник недоступен. Можно заполнить заявку вручную ниже.'); }
    finally { busy = false; send.disabled = false; save(); }
    if (draft && location.value) await createTicket();
  });
  input.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault(); send.click();
    }
  });
  location.addEventListener('change', save);
  submit.addEventListener('click', createTicket);
  reset.addEventListener('click', () => { sessionStorage.removeItem(storageKey); window.location.href = '/'; });
  try {
    const state = JSON.parse(sessionStorage.getItem(storageKey) || 'null');
    if (state && Array.isArray(state.transcript) && state.transcript.length <= 100 && typeof state.requestKey === 'string') {
      messages = Array.isArray(state.messages) ? state.messages : [];
      draft = state.draft || null;
      submittedUrl = state.submittedUrl || null;
      form.elements.request_key.value = state.requestKey;
      transcript = [];
      for (const entry of state.transcript) if (typeof entry.text === 'string') say(entry.text, entry.who === 'user' ? 'user' : 'assistant');
      if (state.room && Array.from(location.options).some(option => option.value === state.room)) location.value = state.room;
      if (submittedUrl) {
        const url = new URL(submittedUrl, window.location.origin);
        if (url.origin === window.location.origin && url.pathname.startsWith('/account/tickets/')) {
          const link = document.createElement('a'); link.href = url.href; link.className = 'chat-link'; link.textContent = 'Открыть заявку и переписку'; log.appendChild(link);
          input.disabled = send.disabled = true; reset.hidden = false;
        }
      } else if (draft) locationBox.hidden = false;
      save();
    }
  } catch (_) { /* Ignore unavailable or corrupt browser storage. */ }
})();
