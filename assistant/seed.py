"""Create demo data without deleting existing records. Run: python assistant/seed.py."""
import os
import secrets

from werkzeug.security import generate_password_hash

from main import app, db, init_db


def seed_demo():
    init_db()
    password = None
    with app.app_context():
        connection = db()
        try:
            connection.execute('BEGIN IMMEDIATE')
            connection.executemany(
                'INSERT OR IGNORE INTO rooms (building, name) VALUES (?, ?)',
                [('Главный корпус', 'Кабинет 101'), ('Главный корпус', 'Кабинет 102'),
                 ('Учебный корпус', 'Кабинет 201')],
            )
            employee = connection.execute('SELECT id FROM employees WHERE login = ?', ('demo',)).fetchone()
            if employee is None:
                password = os.environ.get('DEMO_PASSWORD') or secrets.token_urlsafe(18)
                employee_id = connection.execute(
                    "INSERT INTO employees (login, password_hash, name, role) VALUES (?, ?, ?, 'admin')",
                    ('demo', generate_password_hash(password), 'Демонстрационный сотрудник'),
                ).lastrowid
            else:
                employee_id = employee['id']
            room_id = connection.execute(
                'SELECT id FROM rooms WHERE building = ? AND name = ?',
                ('Главный корпус', 'Кабинет 101'),
            ).fetchone()['id']
            for description, category, status in (
                ('[ДЕМО] Не работает освещение в кабинете', 'Электрика', 'Новая'),
                ('[ДЕМО] Требуется ремонт учебного стола', 'Мебель', 'В работе'),
                ('[ДЕМО] Настроен учебный проектор', 'Оборудование', 'Решена'),
            ):
                if connection.execute('SELECT id FROM tickets WHERE description = ? AND room_id = ?', (description, room_id)).fetchone():
                    continue
                ticket_id = connection.execute(
                    'INSERT INTO tickets (description, category, room_id, status, assignee_id) VALUES (?, ?, ?, ?, ?)',
                    (description, category, room_id, status, employee_id),
                ).lastrowid
                connection.execute(
                    'INSERT INTO ticket_history (ticket_id, employee_id, change_description, comment, is_public) VALUES (?, ?, ?, ?, 1)',
                    (ticket_id, employee_id, 'Создана демонстрационная заявка', 'Пример публичного комментария'),
                )
                connection.execute(
                    'INSERT INTO ticket_history (ticket_id, employee_id, change_description, comment, is_public) VALUES (?, ?, ?, ?, 0)',
                    (ticket_id, employee_id, 'Назначен исполнитель', 'Пример внутреннего комментария'),
                )
            # These are examples, not confirmed college regulations.
            connection.executemany(
                'INSERT OR IGNORE INTO knowledge_base (question, answer, is_verified) VALUES (?, ?, 0)',
                [('Как подать заявку?', 'Выберите помещение и категорию, опишите проблему и отправьте форму.'),
                 ('Как приложить фотографию?', 'Выберите JPEG, PNG или WebP размером до 4 МБ в форме заявки.')],
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return password


if __name__ == '__main__':
    new_password = seed_demo()
    print('Демонстрационные данные подготовлены:', app.config['DATABASE'])
    if new_password:
        print('Создан сотрудник demo. Сохраните пароль (показывается один раз):', new_password)
    else:
        print('Сотрудник demo уже существует; пароль не изменён.')
