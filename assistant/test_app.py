import io
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image
from werkzeug.security import check_password_hash
from flask.testing import FlaskClient


class FormClient(FlaskClient):
    def post(self, *args, **kwargs):
        if args and args[0] == '/':
            with self.session_transaction() as session:
                token = session.get('csrf_token')
            if not token:
                with self.session_transaction() as session:
                    session['csrf_token'] = 'test-csrf-token'
                    token = session['csrf_token']
            kwargs['data'] = {**kwargs.get('data', {}), 'csrf_token': token}
        return super().post(*args, **kwargs)

from main import app, db, init_db
from seed import seed_demo
from test_helpers import register_applicant


class HelpdeskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_config = app.config.copy()
        self.old_client_class = app.test_client_class
        app.test_client_class = FormClient
        app.config.update(TESTING=True, SECRET_KEY='test-only-secret', DATABASE=str(Path(self.temp.name) / 'test.sqlite3'),
                          UPLOAD_DIR=str(Path(self.temp.name) / 'uploads'))
        init_db()
        with app.app_context():
            db().execute("INSERT INTO rooms (building, name) VALUES ('Тестовый', '101')")
            db().commit()
        self.client = app.test_client()
        register_applicant(self.client)

    def tearDown(self):
        app.test_client_class = self.old_client_class
        app.config.clear()
        app.config.update(self.old_config)
        self.temp.cleanup()

    def form_data(self):
        return dict(request_key=str(uuid.uuid4()), description='Сломана лампа', category='Электрика', building='Тестовый', room_id='1')

    def test_form_validation(self):
        self.assertEqual(self.client.get('/').status_code, 200)
        for changes in ({'description': ' '}, {'description': 'x' * 5001}, {'category': 'invalid'}, {'building': ''}, {'building': 'Другой'}, {'room_id': '999'}, {'request_key': 'invalid'}):
            data = self.form_data()
            data.update(changes)
            response = self.client.post('/', data=data)
            self.assertEqual(response.status_code, 400)
            self.assertIn('Проверьте'.encode(), response.data)
        with app.app_context():
            self.assertEqual(db().execute('SELECT count(*) FROM tickets').fetchone()[0], 0)

    def test_create_photo_history_and_retry(self):
        photo = io.BytesIO()
        Image.new('RGB', (2, 2)).save(photo, format='PNG')
        photo.seek(0)
        data = self.form_data()
        response = self.client.post('/', data={**data, 'photo': (photo, 'photo.png')})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get(response.location).status_code, 200)
        confirmation = self.client.get(response.location)
        self.assertIn('Заявка № 1'.encode(), confirmation.data)
        self.assertEqual(response.location, '/account/tickets/1')
        self.assertNotIn(b'/ticket/', confirmation.data)
        self.assertEqual(confirmation.headers['Cache-Control'], 'no-store')
        self.assertEqual(confirmation.headers['Referrer-Policy'], 'no-referrer')
        self.assertEqual(self.client.post('/', data=data).location, response.location)
        self.assertEqual(self.client.get('/ticket/unknown').status_code, 410)
        with app.app_context():
            self.assertEqual(db().execute('SELECT count(*) FROM tickets').fetchone()[0], 1)
            history = db().execute('SELECT * FROM ticket_history').fetchall()
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]['is_public'], 1)
            self.assertIsNone(history[0]['employee_id'])
            self.assertEqual(history[0]['applicant_id'], 1)
            self.assertEqual(db().execute('SELECT applicant_id FROM tickets').fetchone()[0], 1)
            attachment = db().execute('SELECT file_path FROM attachments').fetchone()
            self.assertTrue(Path(attachment['file_path']).is_file())

    def test_reject_non_image(self):
        response = self.client.post('/', data={**self.form_data(), 'photo': (io.BytesIO(b'not a photo'), 'photo.png')})
        self.assertIn('Фото должно быть'.encode(), response.data)
        with app.app_context():
            self.assertEqual(db().execute('SELECT count(*) FROM tickets').fetchone()[0], 0)

    def test_photo_formats_and_limits(self):
        for image_format in ('JPEG', 'PNG', 'WEBP'):
            photo = io.BytesIO()
            Image.new('RGB', (2, 2)).save(photo, format=image_format)
            photo.seek(0)
            response = self.client.post('/', data={**self.form_data(), 'photo': (photo, '../../fake.exe')})
            self.assertEqual(response.status_code, 302)
        for contents in (b'x' * (4 * 1024 * 1024 + 1), b'GIF89a', b'<svg></svg>'):
            response = self.client.post('/', data={**self.form_data(), 'photo': (io.BytesIO(contents), 'image.jpg')})
            self.assertEqual(response.status_code, 400)
        response = self.client.post('/', data={**self.form_data(), 'photo': (io.BytesIO(b'x' * (5 * 1024 * 1024)), 'big.png')})
        self.assertEqual(response.status_code, 413)
        with app.app_context():
            self.assertEqual(db().execute('SELECT count(*) FROM tickets').fetchone()[0], 3)

    def test_without_photo(self):
        self.assertEqual(self.client.post('/', data=self.form_data()).status_code, 302)
        with app.app_context():
            self.assertEqual(db().execute('SELECT count(*) FROM attachments').fetchone()[0], 0)

    def test_file_failure_rolls_back(self):
        upload_path = Path(app.config['UPLOAD_DIR'])
        upload_path.write_text('Cannot create directory here')
        photo = io.BytesIO()
        Image.new('RGB', (2, 2)).save(photo, format='PNG')
        photo.seek(0)
        with self.assertLogs(app.logger, level='ERROR'):
            response = self.client.post('/', data={**self.form_data(), 'photo': (photo, 'photo.png')})
        self.assertEqual(response.status_code, 503)
        self.assertIn('Не удалось сохранить заявку'.encode(), response.data)
        self.assertNotIn('Заявка №'.encode(), response.data)
        with app.app_context():
            for table in ('tickets', 'ticket_access', 'ticket_history', 'attachments'):
                self.assertEqual(db().execute(f'SELECT count(*) FROM {table}').fetchone()[0], 0)

    def test_database_failure_removes_photo_and_allows_retry(self):
        with app.app_context():
            db().executescript("CREATE TRIGGER fail_attachment BEFORE INSERT ON attachments BEGIN SELECT RAISE(ABORT, 'Test failure'); END;")
        data = self.form_data()
        photo = io.BytesIO()
        Image.new('RGB', (2, 2)).save(photo, format='PNG')
        photo.seek(0)
        with self.assertLogs(app.logger, level='ERROR'):
            response = self.client.post('/', data={**data, 'photo': (photo, 'photo.png')})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(list(Path(app.config['UPLOAD_DIR']).iterdir()), [])
        with app.app_context():
            for table in ('tickets', 'ticket_access', 'ticket_history', 'attachments'):
                self.assertEqual(db().execute(f'SELECT count(*) FROM {table}').fetchone()[0], 0)
            db().execute('DROP TRIGGER fail_attachment')
            db().commit()
        self.assertEqual(self.client.post('/', data=data).status_code, 302)

    def test_unavailable_database_does_not_show_success(self):
        app.config['DATABASE'] = str(Path(self.temp.name) / 'missing' / 'db.sqlite3')
        with self.assertLogs(app.logger, level='ERROR'):
            response = self.client.post('/', data=self.form_data())
        self.assertEqual(response.status_code, 503)
        self.assertIn('Не удалось подтвердить'.encode(), response.data)

    def test_concurrent_duplicate(self):
        data = self.form_data()
        cookie = self.client.get_cookie('session').value

        def submit(_):
            with app.test_client() as client:
                client.set_cookie('session', cookie)
                response = client.post('/', data=data)
                return response.status_code, response.location

        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = list(pool.map(submit, range(2)))
        self.assertEqual(first[0], 302)
        self.assertEqual(first, second)
        with app.app_context():
            self.assertEqual(db().execute('SELECT count(*) FROM tickets').fetchone()[0], 1)
            self.assertEqual(db().execute('SELECT count(*) FROM ticket_access').fetchone()[0], 1)

    def test_empty_rooms(self):
        with app.app_context():
            db().execute('DELETE FROM rooms')
            db().commit()
        response = self.client.get('/')
        self.assertIn('Нет доступных помещений'.encode(), response.data)
        self.assertIn(b'id="submit-ticket" disabled', response.data)

    def test_untrusted_host_is_rejected(self):
        response = self.client.get('/', headers={'Host': 'attacker.invalid'})
        self.assertEqual(response.status_code, 400)

    def test_seed_is_repeatable(self):
        password = seed_demo()
        self.assertTrue(password)
        self.assertIsNone(seed_demo())
        with app.app_context():
            employee = db().execute("SELECT * FROM employees WHERE login = 'demo'").fetchone()
            self.assertNotEqual(employee['password_hash'], password)
            self.assertTrue(check_password_hash(employee['password_hash'], password))
            self.assertEqual(db().execute('SELECT count(*) FROM tickets').fetchone()[0], 3)
            self.assertEqual(db().execute("SELECT count(*) FROM tickets WHERE status='Решена'").fetchone()[0], 1)
            self.assertEqual(db().execute('SELECT count(*) FROM ticket_history').fetchone()[0], 6)
            self.assertEqual(db().execute('SELECT count(*) FROM knowledge_base').fetchone()[0], 2)
            self.assertEqual(db().execute('SELECT count(*) FROM knowledge_base WHERE is_verified = 1').fetchone()[0], 0)
            self.assertEqual(db().execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_upgrade_existing_knowledge_base(self):
        with app.app_context():
            db().executescript('DROP TABLE knowledge_base; CREATE TABLE knowledge_base (id INTEGER PRIMARY KEY, question TEXT NOT NULL UNIQUE, answer TEXT NOT NULL);')
            db().execute("INSERT INTO knowledge_base (question, answer) VALUES ('Вопрос', 'Ответ')")
            db().commit()
        init_db()
        init_db()
        with app.app_context():
            row = db().execute('SELECT * FROM knowledge_base').fetchone()
            self.assertEqual(row['answer'], 'Ответ')
            self.assertEqual(row['is_verified'], 0)


if __name__ == '__main__':
    unittest.main()
