const form = document.getElementById('ticket-form');
if (form) {
  const building = form.elements.building;
  const room = form.elements.room_id;
  const button = document.getElementById('submit-ticket');
  const options = Array.from(room.options).slice(1);
  const hasRooms = options.length > 0;
  let submitting = false;

  function updateRooms() {
    const selected = room.value;
    room.replaceChildren(new Option('Выберите помещение', ''));
    options.filter(option => option.dataset.building === building.value)
      .forEach(option => room.add(option));
    room.value = Array.from(room.options).some(option => option.value === selected) ? selected : '';
    room.disabled = !building.value;
  }
  building.addEventListener('change', updateRooms);
  updateRooms();

  form.addEventListener('submit', event => {
    if (submitting) {
      event.preventDefault();
      return;
    }
    submitting = true;
    button.disabled = true;
    button.textContent = 'Отправляем заявку…';
    form.setAttribute('aria-busy', 'true');
  });
  window.addEventListener('pageshow', () => {
    submitting = false;
    button.disabled = !hasRooms;
    button.textContent = 'Отправить заявку';
    form.removeAttribute('aria-busy');
    updateRooms();
  });
  document.getElementById('form-error')?.focus();
}

const copyButton = document.getElementById('copy-link');
if (copyButton) {
  copyButton.addEventListener('click', async () => {
    const input = document.getElementById('secret-link');
    const status = document.getElementById('copy-status');
    try {
      await navigator.clipboard.writeText(input.value);
      status.textContent = 'Ссылка скопирована.';
    } catch {
      input.focus();
      input.select();
      status.textContent = 'Скопируйте выделенную ссылку вручную.';
    }
  });
}
