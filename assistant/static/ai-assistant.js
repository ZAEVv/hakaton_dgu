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
  const photo = form.elements.photo;
  const attach = document.getElementById('chat-attach');
  const attachment = document.getElementById('chat-attachment');
  const attachmentName = document.getElementById('chat-attachment-name');
  const removeAttachment = document.getElementById('chat-attachment-remove');
  function updateAttachment() {
    const selected = photo.files && photo.files[0];
    attachment.hidden = !selected;
    attachmentName.textContent = selected ? `Фото к заявке: ${selected.name}` : '';
  }
  attach.addEventListener('click', () => photo.click());
  photo.addEventListener('change', updateAttachment);
  removeAttachment.addEventListener('click', () => { photo.value = ''; updateAttachment(); });
  updateAttachment();
  const knownLocation = document.getElementById('chat-known-location');
  function showLocation(option) {
    if (knownLocation && option && option.value) knownLocation.textContent = `Место обращения: ${option.text}. Помощник уже знает это место.`;
  }
  if (form.elements.room_id.value) {
    location.value = form.elements.room_id.value;
    showLocation(location.selectedOptions[0]);
  }
  form.elements.room_id.addEventListener('change', () => {
    location.value = form.elements.room_id.value;
    if (location.value) showLocation(location.selectedOptions[0]);
    else if (knownLocation) knownLocation.textContent = 'Место обращения ещё не выбрано.';
  });
  const reset = document.getElementById('chat-new');
  document.querySelector('.mobile-form-shortcut')?.addEventListener('click', () => {
    const manual = document.getElementById('manual-form');
    if (manual) manual.open = true;
  });
  const owner = document.querySelector('.ai-assistant').dataset.chatOwner;
  const storageKey = `college-chat-${owner}`;
  // A newly scanned QR must never reuse a previous room or submitted chat.
  if (new URLSearchParams(window.location.search).has('room')) {
    try { sessionStorage.removeItem(storageKey); } catch (_) { /* Continue without browser storage. */ }
  }
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
    busy = true; pending = true; send.disabled = submit.disabled = attach.disabled = removeAttachment.disabled = true;
    if (draft.type === 'danger' && !draft.summarized) {
      try {
        const response = await fetch('/api/assistant', {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json','X-CSRF-Token':csrf}, body:JSON.stringify({message:draft.draft,room_id:location.value,summarize_danger:true})});
        if (response.ok) {
          const result = await response.json();
          if (typeof result.draft === 'string' && result.draft.trim()) draft.draft = result.draft;
        }
      } catch (_) { /* Retain the user's problem if summarization is unavailable. */ }
      draft.summarized = true; save();
    }
    const selected = location.selectedOptions[0];
    form.elements.building.value = selected.dataset.building;
    form.elements.building.dispatchEvent(new Event('change'));
    form.elements.room_id.value = location.value;
    form.elements.category.value = draft.category || 'Другое';
    form.elements.description.value = draft.draft;
    const hadPhoto = !!(photo.files && photo.files.length);
    const body = new FormData(form);
    say('Отправляю заявку сотрудникам…');
    try {
      const response = await fetch(form.action || '/', {method:'POST', body, credentials:'same-origin'});
      const pathname = new URL(response.url).pathname;
      if (!response.ok || !response.redirected || !(pathname.startsWith('/account/tickets/') || pathname === '/track/view')) throw new Error('Не удалось отправить заявку. Проверьте данные и фото (JPEG, PNG или WebP до 4 МБ) и попробуйте ещё раз.');
      const page = new DOMParser().parseFromString(await response.text(), 'text/html');
      const number = page.querySelector('#ticket-number')?.dataset.number;
      if (!number || !/^\d+$/.test(number)) throw new Error('Не удалось подтвердить сохранение заявки. Повторите отправку.');
      const code = page.querySelector('#tracking-code')?.textContent.trim();
      const secretLink = page.querySelector('#tracking-link')?.href;
      if (pathname === '/track/view' && (!code || !( /^[0-9]{3}$/.test(code) && secretLink || /^[0-9a-f]{64}$/.test(code)))) throw new Error('Не удалось получить код. Повторите отправку.');
      const link = document.createElement('a');
      link.href = response.url; link.textContent = 'Открыть заявку и переписку';
      say(`Обращение № ${number} направлено сотрудникам. Статус: новая.`);
      if (hadPhoto) say('Фото приложено к заявке.');
      if (code) say(`Код отслеживания: ${code}. Сохраните его${secretLink ? ' и секретную ссылку ниже' : ''}, не передавайте посторонним. При потере восстановить доступ нельзя.`);
      link.className = 'chat-link';
      log.appendChild(link);
      if (secretLink) {
        const secret = document.createElement('a'); secret.href = secretLink; secret.textContent = 'Сохранить секретную ссылку для отслеживания'; secret.className = 'chat-link'; log.appendChild(secret);
      }
      draft = null; messages = []; locationBox.hidden = true;
      submittedUrl = response.url; reset.hidden = false; save();
      photo.value = ''; updateAttachment();
      // A new key is required for a different request; reload gives a new key.
      send.disabled = true; input.disabled = true;
      say('Чтобы создать ещё одну заявку, нажмите «Начать новое обращение».');
    } catch (error) {
      pending = false;
      say(error.message || 'Ошибка отправки. Попробуйте ещё раз.');
      send.disabled = false;
    } finally { busy = false; submit.disabled = false; attach.disabled = pending; removeAttachment.disabled = pending; }
  }
  send.addEventListener('click', async () => {
    const text = input.value.trim();
    if (!text || busy || pending) return;
    // If the applicant asks us to notify staff after an emergency warning, keep the
    // original problem instead of treating the instruction as a new incident.
    const notifyIntent = /(?:сообщ|отправ|переда|администратор|сотрудник)/i.test(text);
    if (!draft && notifyIntent) {
      const previous = [...transcript].reverse().find(entry => entry.who === 'user' && /искр|дым|гар[ьи]|горит|пожар|провод|удар.*ток/i.test(entry.text));
      if (previous) draft = {type:'danger', category:'Другое', draft:previous.text};
    }
    if (draft && !locationBox.hidden) {
      say(text, 'user'); input.value = '';
      const cleaned = text.trim().toLocaleLowerCase('ru-RU');
      const matches = Array.from(location.options).filter(option => option.value && (option.text.toLocaleLowerCase('ru-RU') === cleaned || option.text.toLocaleLowerCase('ru-RU').includes(cleaned)));
      if (matches.length === 1) {
        location.value = matches[0].value; save();
        await createTicket();
      } else {
        say('Укажите место, выбрав его из списка. Затем нажмите «Отправить обращение администратору».');
      }
      return;
    }
    if (draft && notifyIntent) {
      say(text, 'user'); input.value = ''; locationBox.hidden = false; save();
      say('Конечно, передам обращение администратору. Сначала выберите место из списка.');
      return;
    }
    draft = null; locationBox.hidden = true;
    say(text, 'user'); input.value = ''; messages.push(text); save();
    const combined = messages.join('\n').slice(-2000);
    busy = true; send.disabled = true;
    try {
      const response = await fetch('/api/assistant', {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json','X-CSRF-Token':csrf}, body:JSON.stringify({message:combined,room_id:location.value || form.elements.room_id.value})});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Помощник временно недоступен.');
      if (data.answer) say(data.answer);
      if (data.question) say(data.question);
      if (data.source) say(`Источник: ${data.source}`);
      if (data.type === 'danger') {
        draft = {type:'danger', category:'Другое', draft:combined};
        const qrRoom = form.elements.room_id.value;
        if (qrRoom && Array.from(location.options).some(o => o.value === qrRoom)) location.value = qrRoom;
        locationBox.hidden = false;
        if (!location.value) say('Чтобы я направил обращение администратору, выберите место из списка. Пока не подходите к оборудованию.');
        save();
      }
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
  location.addEventListener('change', () => { showLocation(location.selectedOptions[0]); save(); });
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
      if (!form.elements.room_id.value && state.room && Array.from(location.options).some(option => option.value === state.room)) location.value = state.room;
      showLocation(location.selectedOptions[0]);
      if (submittedUrl) {
        const url = new URL(submittedUrl, window.location.origin);
        if (url.origin === window.location.origin && (url.pathname.startsWith('/account/tickets/') || url.pathname === '/track/view')) {
          const link = document.createElement('a'); link.href = url.href; link.className = 'chat-link'; link.textContent = 'Открыть заявку и переписку'; log.appendChild(link);
          input.disabled = send.disabled = attach.disabled = removeAttachment.disabled = true; reset.hidden = false;
        }
      } else if (draft) locationBox.hidden = false;
      save();
    }
  } catch (_) { /* Ignore unavailable or corrupt browser storage. */ }
})();
