import { test, expect } from '@playwright/test';
const errors=[];
test.beforeEach(async({page})=>{page.on('pageerror',e=>errors.push(e.message));});
test('QR chat, photo, confirmation, staff resolution and public tracking',async({page,browser,request})=>{
 const login=await request.post('/api/auth/login',{data:{login:'admin',password:'Admin-e2e-testing-2026!'}});expect(login.ok()).toBeTruthy();
 const rooms=await (await request.get('/api/admin/locations')).json();const room=rooms.find(r=>r.room==='214');
 await page.setViewportSize({width:390,height:844});await page.goto('/chat?qr='+room.qr_key);
 await expect(page.getByRole('heading',{name:'Помощник УПК'})).toBeVisible();
 await expect(page.getByText('Главный корпус, кабинет 214')).toBeVisible();
 await page.screenshot({path:'test-results/mobile-chat.png',fullPage:true,animations:'disabled'});
 await page.getByLabel('Сообщение помощнику').fill('В кабинете 214 не работает проектор');await page.getByRole('button',{name:'Отправить сообщение',exact:true}).click();
 await expect(page.getByText('Принял проблему',{exact:true})).toBeVisible();
 await expect(page.locator('.ticket-offer')).toContainText('кабинет 214');
 await page.getByLabel('Прикрепить фото', {exact:true}).setInputFiles({name:'photo.png',mimeType:'image/png',buffer:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+afoIAAAAASUVORK5CYII=','base64')});
 await page.getByRole('button',{name:'Отправить сотруднику',exact:true}).click();
 await expect(page.getByText(/Готово\. Заявка/)).toBeVisible();
 await page.getByRole('button',{name:'Открыть обращение',exact:true}).click();
 await expect(page).toHaveURL(/\/track\/[a-f0-9]{64}$/);const tracking=page.url();
 await expect(page.locator('.status')).toHaveText('Новая');await page.screenshot({path:'test-results/mobile-tracking.png',fullPage:true,animations:'disabled'});
 const staff=await browser.newPage({viewport:{width:1440,height:1000}});await staff.goto('/admin');await staff.getByLabel('Логин',{exact:true}).fill('admin');await staff.getByLabel('Пароль',{exact:true}).fill('Admin-e2e-testing-2026!');await staff.getByRole('button',{name:'Войти в панель'}).click();await expect(staff.getByRole('heading',{name:'Обращения колледжа'})).toBeVisible();
 await staff.screenshot({path:'test-results/admin-overview.png',fullPage:true,animations:'disabled'});
 await staff.getByRole('link',{name:'Обращения',exact:true}).click();await staff.getByRole('button',{name:/УПК-00001/}).first().click();
 await staff.getByLabel('Статус',{exact:true}).selectOption('В работе');await staff.getByLabel('Исполнитель',{exact:true}).selectOption({label:'Сотрудник УПК'});await staff.getByLabel('Комментарий',{exact:true}).fill('Проверяем подключение');await staff.getByRole('button',{name:'Сохранить изменения'}).click();
 await expect(staff.getByRole('dialog')).not.toBeVisible();await staff.getByRole('button',{name:/УПК-00001/}).first().click();await staff.getByLabel('Статус',{exact:true}).selectOption('Решена');await staff.getByLabel('Результат или причина (обязательно)').fill('Заменён кабель, проектор работает.');await staff.getByRole('button',{name:'Сохранить изменения'}).click();await expect(staff.getByRole('dialog')).not.toBeVisible();
 await page.reload();await expect(page.locator('.status')).toHaveText('Решена');await expect(page.getByText('Заменён кабель, проектор работает.')).toBeVisible();
 await staff.getByRole('link',{name:'Кабинеты и QR'}).click();await expect(staff.getByRole('heading',{name:'Кабинеты и QR-коды'})).toBeVisible();await expect(staff.locator('.qr-card')).toHaveCount(43);await staff.getByRole('button',{name:/3 этаж/}).click();await expect(staff.locator('.qr-card')).toHaveCount(17);await expect.poll(()=>staff.locator('.qr-card img').evaluateAll(imgs=>imgs.filter(img=>img.getBoundingClientRect().top<innerHeight).every(img=>img.complete&&img.naturalWidth>0))).toBeTruthy();await staff.screenshot({path:'test-results/admin-qr.png',fullPage:false,animations:'disabled'});
 expect(errors).toEqual([]);await staff.close();
});
test('Responsive layouts, palettes, reduced motion and unknown QR',async({page})=>{
 for(const width of [1440,1024,820,768,390]){
  await page.setViewportSize({width,height:900});await page.goto('/');await expect(page.getByRole('heading',{name:'Помощник УПК',exact:true})).toBeVisible();
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);expect(overflow,`overflow at ${width}`).toBeFalsy();
  await page.screenshot({path:`test-results/chat-${width}.png`,fullPage:true,animations:'disabled'});
 }
 await page.setViewportSize({width:1440,height:1000});
 for(const theme of ['Сад','Ночь']){await page.locator('.messenger-sidebar').getByRole('button',{name:`Палитра «${theme}»`}).click();await page.screenshot({path:`test-results/theme-${theme==='Сад'?'garden':'night'}.png`,fullPage:true,animations:'disabled'});}
 await page.emulateMedia({reducedMotion:'reduce'});await page.getByRole('button',{name:'Не работает проектор'}).click();await expect(page.getByRole('button',{name:'Указать кабинет',exact:true})).toBeVisible();
 await page.goto('/chat?qr=unknown');await expect(page.getByText('Этот QR-код не найден. Выберите кабинет вручную.')).toBeVisible();
 expect(errors).toEqual([]);
});
test('Staff screens work on small phones and tablets',async({page})=>{
 await page.goto('/admin');await page.getByLabel('Логин',{exact:true}).fill('admin');await page.getByLabel('Пароль',{exact:true}).fill('Admin-e2e-testing-2026!');await page.getByRole('button',{name:'Войти в панель'}).click();await expect(page.getByRole('heading',{name:'Обращения колледжа'})).toBeVisible();
 for(const width of [375,768,820]){
  await page.setViewportSize({width,height:900});
  for(const [tab,heading] of [['overview','Обращения колледжа'],['tickets','Обращения'],['analytics','Аналитика'],['qr','Кабинеты и QR-коды'],['team','Сотрудники'],['settings','Настройки']]){
   await page.goto('/admin/'+tab);await expect(page.getByRole('heading',{name:heading,exact:true})).toBeVisible();
   expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),`${tab} at ${width}`).toBeFalsy();
  }
 }
 await page.setViewportSize({width:375,height:812});await page.goto('/admin/qr');await expect(page.locator('.qr-card')).toHaveCount(43);await expect.poll(()=>page.locator('.qr-card img').first().evaluate(img=>img.complete&&img.naturalWidth>0)).toBeTruthy();await page.screenshot({path:'test-results/admin-mobile-qr.png',fullPage:false,animations:'disabled'});
 expect(errors).toEqual([]);
});

test('Scanned QR sets the correct room in chat, answer and ticket draft',async({page,request})=>{
 await page.addInitScript(()=>Object.defineProperty(crypto,'randomUUID',{value:undefined}));
 await request.post('/api/auth/login',{data:{login:'admin',password:'Admin-e2e-testing-2026!'}});
 const rooms=await(await request.get('/api/admin/locations')).json();
 await page.setViewportSize({width:390,height:844});
 for(const number of ['101','214','317']){
  const room=rooms.find(r=>r.room===number);
  await page.goto('/chat?qr='+room.qr_key);
  await expect(page.getByRole('button',{name:'Выбрать кабинет',exact:true})).toContainText(number);
  await expect(page.getByText('Главный корпус, кабинет '+number,{exact:true})).toBeVisible();
  await page.getByLabel('Сообщение помощнику').fill('В каком я кабинете?');
  await page.getByRole('button',{name:'Отправить сообщение',exact:true}).click();
  await expect(page.getByText('По QR-коду выбран кабинет '+number,{exact:false})).toBeVisible();
  await page.getByLabel('Сообщение помощнику').fill('Не работает проектор');
  await page.getByRole('button',{name:'Отправить сообщение',exact:true}).click();
  await expect(page.locator('.ticket-offer')).toContainText('кабинет '+number);
  await expect(page.locator('.ticket-offer')).toContainText('Оборудование');
 }
 await page.getByRole('button',{name:'Выбрать цветовую тему'}).click();
 await page.getByRole('button',{name:'Тёмная',exact:true}).click();await page.reload();
 await expect(page.locator('html')).toHaveAttribute('data-theme','night');
 await expect(page.getByRole('button',{name:'Выбрать кабинет',exact:true})).toContainText('317');
 expect(errors).toEqual([]);
});
