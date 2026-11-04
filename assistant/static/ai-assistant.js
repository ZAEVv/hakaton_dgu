(() => {
  'use strict';
  const byId = id => document.getElementById(id);
  const ui = {
    composer: byId('ai-message'), send: byId('ai-send'), log: byId('chat-messages'),
    panel: byId('chat-location'), room: byId('chat-room'), confirm: byId('chat-send-ticket'),
    description: byId('chat-description'), category: byId('chat-category'),
    form: byId('ticket-form'), reset: byId('chat-new')
  };
  if (Object.values(ui).some(element => !element)) return;
  const owner = document.querySelector('.ai-assistant');
  if (!owner || !owner.dataset.chatOwner || !ui.form.elements.csrf_token || !ui.form.elements.request_key) return;
  const key = `college-chat-${owner.dataset.chatOwner}`;
  const state = {messages: [], draft: null, transcript: [], submittedUrl: null, busy: false};
  const options = select => Array.from(select.options || []);
  const usable = (select, value) => !select.disabled && value && options(select).find(option =>
    option.value === value && !option.disabled && !(option.parentElement && option.parentElement.disabled));
  const roomOption = () => usable(ui.room, ui.room.value);
  const validCategory = value => !!usable(ui.category, value);
  const ticketUrl = value => {
    try {
      const url = new URL(value, window.location.origin);
      return url.origin === window.location.origin && /^\/account\/tickets\/\d+\/?$/.test(url.pathname) ? url : null;
    } catch (_) { return null; }
  };
  let storageWarning;
  function warnStorage() {
    if (storageWarning) return;
    storageWarning = document.createElement('p');
    if (storageWarning.setAttribute) storageWarning.setAttribute('role', 'alert');
    storageWarning.textContent = 'Не удалось сохранить данные в этой вкладке. Черновик и неотправленный текст могут не восстановиться после обновления страницы. Скопируйте важный текст в безопасное место.';
    ui.log.appendChild(storageWarning);
  }
  const emergency = text => /искр|дым|гар[ьи]|горит|пожар|провод|удар.*ток/i.test(text);
  function savedTranscript() {
    const history = state.transcript;
    const transcript = history.slice(-1000);
    const older = history.slice(0, -1000);
    // Overflowed details are not in the draft; preserve older user messages separately.
    const overflowContext = state.draft && state.draft.overflow ? older.filter(entry => entry.who === 'user') : [];
    const critical = [...older].reverse().find(entry => entry.who === 'user' && emergency(entry.text));
    if (critical && !overflowContext.includes(critical) && !transcript.some(entry => entry.who === 'user' && emergency(entry.text))) {
      transcript.splice(0, 1, critical);
    }
    return {transcript, overflowContext};
  }
  let historyWarning;
  function persist() {
    try {
      const history = savedTranscript();
      if (!historyWarning && history.transcript.length + history.overflowContext.length < state.transcript.length) {
        historyWarning = document.createElement('p');
        historyWarning.textContent = 'Некоторые старые сообщения переписки не восстановятся после обновления страницы. Скопируйте важные сведения в безопасное место.';
        ui.log.appendChild(historyWarning);
      }
      sessionStorage.setItem(key, JSON.stringify({messages: state.messages, draft: state.draft,
        transcript: history.transcript, overflowContext: history.overflowContext, submittedUrl: state.submittedUrl, room: ui.room.value,
        requestKey: ui.form.elements.request_key.value, composer: ui.composer.value}));
    } catch (_) { warnStorage(); }
  }
  function bubble(text, who = 'assistant', record = true) {
    if (typeof text !== 'string' || !text) return;
    const node = document.createElement('p');
    node.className = `chat-bubble ${who}-bubble`;
    node.textContent = text;
    ui.log.appendChild(node);
    if (record) { state.transcript.push({text, who}); persist(); }
    if (node.scrollIntoView) node.scrollIntoView({block: 'nearest'});
  }
  function showLink(url) {
    const link = document.createElement('a');
    link.href = url.href; link.textContent = 'Открыть заявку и переписку'; link.className = 'chat-link';
    ui.log.appendChild(link);
  }
  function showDraft() {
    if (!state.draft) return;
    ui.description.value = typeof state.draft.draft === 'string' ? state.draft.draft : '';
    if (state.draft.type === 'danger' && !state.draft.categoryChosen) state.draft.category = '';
    ui.category.value = validCategory(state.draft.category) ? state.draft.category : '';
    ui.panel.hidden = false;
  }
  function captureDraft() {
    if (!state.draft) return;
    state.draft.draft = ui.description.value;
    state.draft.category = ui.category.value;
    persist();
  }
  function setBusy(value) {
    state.busy = value;
    ui.send.disabled = value || !!state.submittedUrl;
    ui.confirm.disabled = value;
  }
  function restore() {
    let saved;
    let raw;
    try { raw = sessionStorage.getItem(key); } catch (_) { warnStorage(); return; }
    try { saved = JSON.parse(raw || 'null'); } catch (_) { return; }
    if (!saved || !Array.isArray(saved.transcript) || typeof saved.requestKey !== 'string') return;
    state.messages = Array.isArray(saved.messages) ? saved.messages.filter(x => typeof x === 'string') : [];
    state.draft = saved.draft && typeof saved.draft === 'object' ? saved.draft : null;
    const overflowContext = state.draft && state.draft.overflow && Array.isArray(saved.overflowContext) ? saved.overflowContext : [];
    state.transcript = [...overflowContext, ...saved.transcript].filter(x => x && typeof x.text === 'string').map(x => ({text:x.text, who:x.who === 'user' ? 'user' : 'assistant'}));
    ui.form.elements.request_key.value = saved.requestKey;
    ui.composer.value = typeof saved.composer === 'string' ? saved.composer : '';
    for (const item of state.transcript) bubble(item.text, item.who, false);
    if (usable(ui.room, saved.room)) ui.room.value = saved.room;
    const url = saved.submittedUrl && ticketUrl(saved.submittedUrl);
    if (url) {
      state.submittedUrl = url.href; showLink(url); ui.composer.disabled = ui.send.disabled = true; ui.reset.hidden = false;
    } else if (state.draft) showDraft();
  }
  function selectQrRoom() {
    const field = ui.form.elements.room_id;
    if (field && usable(ui.room, field.value)) ui.room.value = field.value;
  }
  function displayReply(data) {
    if (data.answer) bubble(data.answer);
    if (data.question) bubble(data.question);
    if (data.source) bubble(`Источник: ${data.source}`);
  }
  async function assess(text) {
    const response = await fetch('/api/assistant', {method:'POST', credentials:'same-origin',
      headers:{'Content-Type':'application/json', 'X-CSRF-Token':ui.form.elements.csrf_token.value},
      body:JSON.stringify({message:text})});
    const data = await response.json();
    if (!response.ok || !data || !['danger','fault','question','unclear'].includes(data.type)) throw new Error('assistant unavailable');
    return data;
  }
  function appendDetail(text, matches) {
    const command = /^(?:пожалуйста[,\s]+)?(?:сообщите|сообщи|передайте|передай|отправьте|отправь)\s+(?:(?:об этом|это)\s+)?(?:администратору|сотрудникам|сотруднику)[.!\s]*$/i.test(text);
    if (matches.length || command || ui.description.value.split('\n').includes(text)) return;
    const combined = ui.description.value ? `${ui.description.value}\n${text}` : text;
    const limit = ui.description.maxLength > 0 ? ui.description.maxLength : 5000;
    if (combined.length <= limit) { ui.description.value = combined; captureDraft(); }
    else {
      state.draft.overflow = true; persist();
      bubble('Дополнение не поместилось в описание и осталось в переписке. Сократите описание и вручную добавьте важные сведения; затем проверьте его перед отправкой.');
    }
  }
  async function sendMessage() {
    const text = ui.composer.value.trim();
    if (!text || state.busy || state.submittedUrl) return;
    if (!state.draft && /(?:сообщ|отправ|переда|администратор|сотрудник)/i.test(text)) {
      const previous = [...state.transcript].reverse().find(entry => entry.who === 'user' && emergency(entry.text));
      if (previous) { state.draft = {type:'danger', category:'', draft:previous.text}; showDraft(); }
    }
    const openDraft = !!state.draft;
    let matches = [];
    if (openDraft) {
      captureDraft();
      matches = options(ui.room).filter(option => usable(ui.room, option.value) === option && option.text.toLocaleLowerCase('ru-RU') === text.toLocaleLowerCase('ru-RU'));
      appendDetail(text, matches);
    } else state.messages.push(text);
    ui.composer.value = '';
    bubble(text, 'user'); persist();
    setBusy(true);
    try {
      const combined = openDraft ? text : state.messages.join('\n').slice(-2000);
      const data = await assess(combined);
      displayReply(data);
      if (openDraft) {
        if (data.type === 'danger') {
          if (!data.answer) bubble('При непосредственной опасности отойдите в безопасное место и звоните 112.');
          bubble('Проверьте описание и подтвердите отправку кнопкой.');
        } else if (matches.length === 1 && usable(ui.room, matches[0].value) === matches[0]) {
          ui.room.value = matches[0].value;
          bubble('Место выбрано. Проверьте черновик и подтвердите отправку кнопкой.');
        } else bubble('Проверьте описание и выберите место из списка. Отправка — только по кнопке.');
      } else if (data.type === 'danger' || (data.type === 'fault' && data.draft)) {
        state.draft = data.type === 'danger' ? {type:'danger', category:'', draft:combined} : {type:'fault', category:data.category, draft:data.draft};
        selectQrRoom(); showDraft();
        if (!roomOption()) bubble(data.type === 'danger' ? 'Чтобы я направил обращение администратору, выберите место из списка. Пока не подходите к оборудованию.' : 'Где возникла проблема? Выберите корпус и помещение из списка.');
      } else if (data.type === 'question') state.messages = [];
    } catch (_) {
      bubble(openDraft ? 'Не удалось проверить новое сообщение. Если есть непосредственная опасность, отойдите в безопасное место и звоните 112. Черновик сохранён; проверьте его перед отправкой.' : 'Не удалось проверить сообщение. Если есть непосредственная опасность, отойдите в безопасное место и звоните 112. Можно заполнить заявку вручную в форме на этой странице.');
    } finally { setBusy(false); persist(); }
  }
  async function submitDraft() {
    if (!state.draft || state.busy || state.submittedUrl) return;
    if (state.draft.overflow) { bubble('Не всё сообщение поместилось в описание. Отредактируйте описание, добавьте важные сведения и проверьте его перед отправкой.'); return; }
    const room = roomOption();
    if (!room || !room.dataset || !room.dataset.building) { bubble('Выберите место из списка, чтобы я смог отправить заявку.'); return; }
    if (!ui.description.value.trim() || !validCategory(ui.category.value)) { bubble('Укажите описание и категорию заявки.'); return; }
    captureDraft();
    setBusy(true);
    const locked = [ui.description, ui.category, ui.room, ui.composer].map(element => [element, element.disabled]);
    locked.forEach(([element]) => { element.disabled = true; });
    const body = new FormData(ui.form);
    body.set('building', room.dataset.building); body.set('room_id', room.value);
    body.set('category', ui.category.value); body.set('description', ui.description.value); body.delete('photo');
    bubble('Отправляю заявку сотрудникам…');
    try {
      const response = await fetch(ui.form.action || '/', {method:'POST', body, credentials:'same-origin'});
      const url = ticketUrl(response.url);
      if (!response.ok || !response.redirected || !url) throw new Error('Не удалось отправить заявку. Проверьте данные и попробуйте ещё раз.');
      state.submittedUrl = url.href;
      const number = url.pathname.replace(/\/$/, '').split('/').pop();
      bubble(`Обращение № ${number} направлено администратору. Статус: новая. После принятия в работу вы увидите ответ и новый статус в профиле.`);
      showLink(url);
      state.draft = null; state.messages = []; ui.panel.hidden = true; ui.reset.hidden = false; ui.composer.disabled = true;
      bubble('Чтобы создать ещё одну заявку, нажмите «Начать новое обращение».');
    } catch (_) { bubble('Не удалось отправить заявку. Проверьте данные и попробуйте ещё раз.'); }
    finally { locked.forEach(([element, disabled]) => { element.disabled = element === ui.composer && state.submittedUrl ? true : disabled; }); setBusy(false); persist(); }
  }
  ui.send.addEventListener('click', sendMessage);
  ui.confirm.addEventListener('click', submitDraft);
  ui.composer.addEventListener('input', persist);
  ui.composer.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); ui.send.click(); }
  });
  ui.room.addEventListener('change', persist);
  ui.description.addEventListener('input', () => { if (state.draft) state.draft.overflow = false; captureDraft(); });
  ui.category.addEventListener('change', () => { if (state.draft) state.draft.categoryChosen = validCategory(ui.category.value); captureDraft(); });
  ui.reset.addEventListener('click', () => { try { sessionStorage.removeItem(key); } catch (_) {} window.location.href = '/'; });
  restore();
  const privacy = document.createElement('p');
  privacy.textContent = 'Текст и черновик сохраняются в sessionStorage этой вкладки и могут восстановиться после перезапуска браузера. На общем устройстве не вводите конфиденциальные сведения и пароли.';
  ui.log.appendChild(privacy);
})();
