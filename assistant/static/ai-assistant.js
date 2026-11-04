(() => {
  const input = document.getElementById('ai-message');
  const send = document.getElementById('ai-send');
  const log = document.getElementById('chat-messages');
  const locationBox = document.getElementById('chat-location');
  const location = document.getElementById('chat-room');
  const submit = document.getElementById('chat-send-ticket');
  const description = document.getElementById('chat-description');
  const category = document.getElementById('chat-category');
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
  function showDraft() {
    description.value = draft.draft || '';
    category.value = draft.category || 'Другое';
    locationBox.hidden = false;
  }
  function updateDraft() {
    if (!draft) return;
    draft.draft = description.value;
    draft.category = category.value;
    save();
  }
  async function createTicket() {
    if (!draft || busy || pending) return;
    if (draft.overflow) { say('Не всё сообщение поместилось в описание. Отредактируйте описание, добавьте важные сведения и проверьте его перед отправкой.'); return; }
    if (!location.value) { say('Выберите место из списка, чтобы я смог отправить заявку.'); return; }
    if (!description.value.trim() || !category.value) { say('Укажите описание и категорию заявки.'); return; }
    updateDraft();
    busy = true; pending = true; send.disabled = submit.disabled = true;
    const selected = location.selectedOptions[0];
    const body = new FormData(form);
    body.set('building', selected.dataset.building);
    body.set('room_id', location.value);
    body.set('category', category.value);
    body.set('description', description.value);
    body.delete('photo');
    say('Отправляю заявку сотрудникам…');
    try {
      const response = await fetch(form.action || '/', {method:'POST', body, credentials:'same-origin'});
      if (!response.ok || !response.redirected || !new URL(response.url).pathname.startsWith('/account/tickets/')) throw new Error('Не удалось отправить заявку. Проверьте данные и попробуйте ещё раз.');
      const link = document.createElement('a');
      link.href = response.url; link.textContent = 'Открыть заявку и переписку';
      const number = new URL(response.url).pathname.split('/').pop();
      say(`Обращение № ${number} направлено администратору. Статус: новая. После принятия в работу вы увидите ответ и новый статус в профиле.`);
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
    // If the applicant asks us to notify staff after an emergency warning, keep the
    // original problem instead of treating the instruction as a new incident.
    const notifyIntent = /(?:сообщ|отправ|переда|администратор|сотрудник)/i.test(text);
    if (!draft && notifyIntent) {
      const previous = [...transcript].reverse().find(entry => entry.who === 'user' && /искр|дым|гар[ьи]|горит|пожар|провод|удар.*ток/i.test(entry.text));
      if (previous) { draft = {type:'danger', category:'Другое', draft:previous.text}; showDraft(); }
    }
    if (draft) {
      // Every new message must be assessed before interpreting it as a room.
      // Keep the existing editable draft and selected room independent of the reply.
      updateDraft();
      const cleaned = text.toLocaleLowerCase('ru-RU');
      const matches = Array.from(location.options).filter(option => option.value && option.text.toLocaleLowerCase('ru-RU') === cleaned);
      const notifyOnly = /^(?:пожалуйста[,\s]+)?(?:сообщите|сообщи|передайте|передай|отправьте|отправь)\s+(?:(?:об этом|это)\s+)?(?:администратору|сотрудникам|сотруднику)[.!\s]*$/i.test(text);
      if (!matches.length && !notifyOnly && !description.value.split('\n').includes(text)) {
        const combined = description.value ? `${description.value}\n${text}` : text;
        const limit = description.maxLength > 0 ? description.maxLength : 5000;
        if (combined.length <= limit) {
          description.value = combined; updateDraft();
        } else {
          draft.overflow = true; save();
          say('Дополнение не поместилось в описание и осталось в переписке. Сократите описание и вручную добавьте важные сведения; затем проверьте его перед отправкой.');
        }
      }
      say(text, 'user'); input.value = '';
      busy = true; send.disabled = submit.disabled = true;
      try {
        const response = await fetch('/api/assistant', {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json','X-CSRF-Token':csrf}, body:JSON.stringify({message:text})});
        const data = await response.json();
        if (!response.ok || !data || !['danger', 'fault', 'question', 'unclear'].includes(data.type)) throw new Error('Помощник недоступен');
        if (data.answer) say(data.answer);
        if (data.question) say(data.question);
        if (data.source) say(`Источник: ${data.source}`);
        if (data.type === 'danger') {
          if (!data.answer) say('При непосредственной опасности отойдите в безопасное место и звоните 112.');
          say('Проверьте описание и подтвердите отправку кнопкой.');
        } else {
          if (matches.length === 1) {
            location.value = matches[0].value; save();
            say('Место выбрано. Проверьте черновик и подтвердите отправку кнопкой.');
          } else {
            say('Проверьте описание и выберите место из списка. Отправка — только по кнопке.');
          }
        }
      } catch (_) {
        say('Не удалось проверить новое сообщение. Если есть непосредственная опасность, отойдите в безопасное место и звоните 112. Черновик сохранён; проверьте его перед отправкой.');
      } finally { busy = false; send.disabled = submit.disabled = false; save(); }
      return;
    }
    draft = null; locationBox.hidden = true;
    say(text, 'user'); input.value = ''; messages.push(text); save();
    const combined = messages.join('\n').slice(-2000);
    busy = true; send.disabled = true;
    try {
      const response = await fetch('/api/assistant', {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json','X-CSRF-Token':csrf}, body:JSON.stringify({message:combined})});
      const data = await response.json();
      if (!response.ok || !data || !['danger', 'fault', 'question', 'unclear'].includes(data.type)) throw new Error('Помощник временно недоступен.');
      if (data.answer) say(data.answer);
      if (data.question) say(data.question);
      if (data.source) say(`Источник: ${data.source}`);
      if (data.type === 'danger') {
        draft = {type:'danger', category:'Другое', draft:combined};
        const qrRoom = form.elements.room_id.value;
        if (qrRoom && Array.from(location.options).some(o => o.value === qrRoom)) location.value = qrRoom;
        showDraft();
        if (!location.value) say('Чтобы я направил обращение администратору, выберите место из списка. Пока не подходите к оборудованию.');
        save();
      }
      if (data.type === 'question') messages = [];
      if (data.type === 'fault' && data.draft) {
        draft = data;
        const qrRoom = form.elements.room_id.value;
        if (qrRoom && Array.from(location.options).some(o => o.value === qrRoom)) location.value = qrRoom;
        showDraft();
        save();
        if (!location.value) say('Где возникла проблема? Выберите корпус и помещение из списка.');
      }
    } catch (_) { say('Не удалось проверить сообщение. Если есть непосредственная опасность, отойдите в безопасное место и звоните 112. Можно заполнить заявку вручную ниже.'); }
    finally { busy = false; send.disabled = false; save(); }
  });
  input.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault(); send.click();
    }
  });
  location.addEventListener('change', save);
  description.addEventListener('input', () => { if (draft) draft.overflow = false; updateDraft(); });
  category.addEventListener('change', updateDraft);
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
      } else if (draft) showDraft();
      save();
    }
  } catch (_) { /* Ignore unavailable or corrupt browser storage. */ }
})();
