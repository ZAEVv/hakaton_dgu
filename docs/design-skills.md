# Скиллы для редизайна

Установлены по запросу пользователя в `/home/zaev/.codex/skills`:

- Huashu Design: https://github.com/alchaincyf/huashu-design, commit b2460b031c33ff32d2bf3b97263527daa231e4de, папка huashu-design.
- Emil Kowalski: https://github.com/emilkowalski/skills, commit c8a79627b59d72d764d6ab6f2c87c09a48169833, skills/emil-design-eng.
- Impeccable: https://github.com/pbakaus/impeccable, commit 8a7c796a9feb2eb525a39f624132d19564b8e83c, .agents/skills/impeccable.
- Taste Skill уже установлен, имя design-taste-frontend, версия 2.5.0.

Прочитаны и применены к `design-demos/`. Полный перенос в production ожидает выбора из трёх вариантов по прямому правилу Huashu. Действующий React/Python проект работает отдельно и не заменён демонстрацией.

Проверка 6 ноября 2026: варианты 1 и 3 — выбор кабинета 317, отправка сообщения, локальное создание заявки, поиск с пустой выдачей, смена статуса, все 43 QR-изображения, reduced motion. Viewports 375,390,768,1024,1440, ошибок JS и горизонтального overflow нет. Вариант 2 проверен отдельным исполнителем: те же ширины, выбор317, сообщение, заявка, статус и комментарий, без ошибок JS/overflow. Страница сравнения и переключение desktop/mobile/admin проверены. Скриншоты просмотрены.

Ограничения: прототипы используют явные демонстрационные данные. Python-версия Huashu lint пропустила проверки из-за отсутствия Python Playwright; браузерная проверка выполнена Node Playwright + системный Chromium. Реальное мобильное устройство и экранная клавиатура в этой итерации не тестировались.
