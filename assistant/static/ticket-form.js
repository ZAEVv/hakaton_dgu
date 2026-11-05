(() => {
  'use strict';

  const ticket = document.getElementById('ticket-form');
  if (!ticket) return;

  const campus = ticket.elements.building;
  const rooms = ticket.elements.room_id;
  const send = document.getElementById('submit-ticket');
  const available = Array.from(rooms.options).slice(1);
  let pending = false;

  function showRooms() {
    const previous = rooms.value;
    const matching = available.filter(item => item.dataset.building === campus.value);
    rooms.replaceChildren(new Option('Выберите помещение', ''));
    for (const item of matching) rooms.add(item);
    rooms.value = Array.from(rooms.options).some(item => item.value === previous) ? previous : '';
    rooms.disabled = !campus.value;
  }

  campus.addEventListener('change', showRooms);
  showRooms();
  ticket.addEventListener('submit', event => {
    if (pending) {
      event.preventDefault();
      return;
    }
    pending = true;
    send.disabled = true;
    send.textContent = 'Отправляем заявку…';
    ticket.setAttribute('aria-busy', 'true');
  });
  window.addEventListener('pageshow', () => {
    pending = false;
    send.disabled = available.length === 0;
    send.textContent = 'Отправить заявку';
    ticket.removeAttribute('aria-busy');
    showRooms();
  });
  document.getElementById('form-error')?.focus();
})();
