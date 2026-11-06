# Общий бриф визуальных вариантов

Рабочий продукт, не рекламный лендинг. Режим Impeccable: Operate. Русский цифровой помощник УПК, веб React + Python backend. User rejected existing same-card SaaS composition. Stage: design alternatives, not final production replacement. Huashu direction choice pending. No change to src/ before userchoice.

Унифицированные размеры: desktop 1440×900; mobile 390×844 и 375×812. Первичный экран — уже начавшийся диалог после QR кабинета 214, 2 этаж. Реальный диапазон кабинетов: 101–110, 201–216, 301–317. Никаких придуманных планов помещения.

Контент диалога: помощник «Здравствуйте! Что случилось в кабинете 214?»; пользователь «Не работает проектор. На экране нет изображения.»; ответ «Проверьте, выбран ли на проекторе вход HDMI. Если изображение не появится, помогу передать заявку сотруднику.»; действия «Как переключить вход?» и «Создать заявку». Без фейкового online/verified. База знаний до DeepSeek ключа. QR связывает кабинет с диалогом.

Действия: переключение Помощник / Сотруднику (видимые как режимы в узкой отдельной панели прототипа), отправка локального сообщения и ответ с явным статусом демонстрации; кнопка выбора комнаты с диапазонами этажей; просмотр/подтверждение локального черновика. Реальных API writes не делать. Label in prototype toolbar «Дизайн-концепт · демонстрационные данные». Внутри интерфейса не расписывать разработку/API.

Экран сотрудника: очередь заявок (демоданные: УПК-024 проектор 214 Новый; УПК-023 уборка 107 В работе; УПК-022 Wi-Fi 305 Решено), поиск/фильтр, открытие деталей и смена статуса локально. Отдельная QR-галерея если успеваете, реальные QRизображения доступны artifacts/qr/ с кириллическим текстом. Главное — убедительная композиция очереди, не декоративные большие KPI.

Один самостоятельный HTML на вариант; inline CSS/JS, библиотека stroke SVG icons consistent, no networkdependencies. Body16 mobile/15desktop minimum14; labels>=12. Clicktargets>=44; visiblefocus; reducedmotion; buttons pressedscale .97, transitions140–220ms custom easeout; no fullpagefade/staggers. Input16px. Flexminheight0, dynamic100dvh, no horizontaloverflow. HTMLlang ru.

Use skills as combined workflow: Huashu governs prototype selection, Impeccable Operate + craft floor governs precision, Taste system/spacing/equaledges/realUI not landingkits, Emil interaction. Conflicting landing-only/template mandates are inapplicable to product UI.
