import hashlib
import io
import sqlite3
import tempfile
import unittest
import uuid
from contextlib import closing
from pathlib import Path

from PIL import Image
from werkzeug.security import check_password_hash, generate_password_hash
from main import app, db, init_db
from test_helpers import register_applicant


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old = app.config.copy()
        app.config.update(TESTING=True, SECRET_KEY='account-test-secret',
                          DATABASE=str(Path(self.temp.name) / 'db.sqlite'),
                          UPLOAD_DIR=str(Path(self.temp.name) / 'uploads'))
        init_db()
        self.owner = app.test_client()
        self.owner_id = register_applicant(self.owner, record_book='СТ-001')
        self.other = app.test_client()
        self.other_id = register_applicant(self.other, record_book='СТ-002', first_name='Пётр', last_name='Петров')
        with app.app_context():
            db().execute("INSERT INTO rooms VALUES (1,'Корпус','101')")
            db().execute("INSERT INTO employees (login,name,password_hash,role) VALUES ('staff','Сотрудник',?,'admin')", (generate_password_hash('staff-password'),))
            db().commit()
        self.staff = app.test_client()
        self.staff.get('/login')
        self.assertEqual(self.post(self.staff, '/login', login='staff', password='staff-password').status_code, 302)

    def tearDown(self):
        app.config.clear()
        app.config.update(self.old)
        self.temp.cleanup()

    def post(self, client, path, **data):
        with client.session_transaction() as sess:
            data.setdefault('csrf_token', sess['csrf_token'])
        return client.post(path, data=data)

    def create(self, client=None, **changes):
        client = client or self.owner
        data = dict(request_key=str(uuid.uuid4()), description='Личная заявка', category='Электрика', building='Корпус', room_id='1')
        data.update(changes)
        return self.post(client, '/', **data)

    def test_registration_hashes_password_and_never_creates_staff(self):
        with app.app_context():
            row = db().execute('SELECT * FROM applicants WHERE id=?', (self.owner_id,)).fetchone()
            self.assertTrue(check_password_hash(row['password_hash'], 'student-password'))
            self.assertNotEqual(row['password_hash'], 'student-password')
            self.assertEqual(row['record_book'], 'СТ-001')
            self.assertEqual(db().execute('SELECT COUNT(*) FROM employees').fetchone()[0], 1)
        self.assertEqual(self.owner.get('/admin').location, '/login')
        self.assertEqual(self.owner.get('/admin/employees').status_code, 302)
        self.assertEqual(self.owner.get('/account').status_code, 200)

    def test_registration_validation_confirmation_and_duplicate_normalization(self):
        client = app.test_client()
        client.get('/account/register')
        valid = dict(first_name='Анна', last_name='Петрова', record_book='TEST-003', password='long-password', password_confirm='long-password')
        for changes in (dict(first_name=' '), dict(last_name='x' * 81), dict(record_book=''), dict(record_book='a' * 41),
                        dict(record_book='abc<script>'), dict(password='short'), dict(password_confirm='different'),
                        dict(record_book=' ст-001 ')):
            with self.subTest(changes=changes):
                self.assertEqual(self.post(client, '/account/register', **(valid | changes)).status_code, 400)
        self.assertEqual(client.post('/account/register', data=valid).status_code, 400)
        self.assertEqual(self.post(client, '/account/register', **(valid | dict(record_book=' test-003 '))).status_code, 302)
        self.assertEqual(client.get('/account').status_code, 200)
        with app.app_context():
            self.assertEqual(db().execute("SELECT record_book FROM applicants WHERE first_name='Анна'").fetchone()[0], 'TEST-003')

    def test_login_by_record_book_password_and_session_rotation(self):
        cookie = self.owner.get_cookie('session').value
        with self.owner.session_transaction() as sess:
            old_hash = hashlib.sha256(sess['applicant_auth_token'].encode()).hexdigest()
        self.owner.get('/account/login')
        self.assertEqual(self.post(self.owner, '/account/login', record_book='СТ-001', password='wrong').status_code, 401)
        self.assertEqual(self.post(self.owner, '/account/login', record_book=' ст-001 ', password='student-password').location, '/account')
        old = app.test_client()
        old.set_cookie('session', cookie)
        self.assertEqual(old.get('/account').location, '/account/login')
        with app.app_context():
            self.assertIsNone(db().execute('SELECT 1 FROM applicant_sessions WHERE token_hash=?', (old_hash,)).fetchone())
        self.assertEqual(self.owner.get('/account').status_code, 200)

    def test_logout_csrf_and_copied_cookie_revocation(self):
        cookie = self.owner.get_cookie('session').value
        self.assertEqual(self.owner.post('/account/logout').status_code, 400)
        self.assertEqual(self.post(self.owner, '/account/logout').location, '/account/login')
        client = app.test_client()
        client.set_cookie('session', cookie)
        self.assertEqual(client.get('/account').status_code, 302)

    def test_session_expiry_and_server_revocation(self):
        with app.app_context():
            db().execute("UPDATE applicant_sessions SET created_at=datetime('now','-13 hours') WHERE applicant_id=?", (self.owner_id,))
            db().execute('DELETE FROM applicant_sessions WHERE applicant_id=?', (self.other_id,))
            db().commit()
        self.assertEqual(self.owner.get('/account').location, '/account/login')
        self.assertEqual(self.other.get('/account').location, '/account/login')

    def test_anonymous_access_requires_login_and_legacy_links_are_disabled(self):
        client = app.test_client()
        for path in ('/', '/account', '/account/tickets/1', '/account/attachments/1'):
            self.assertEqual(client.get(path).location, '/account/login')
        self.assertEqual(client.post('/', data={'description': 'Анонимно'}).location, '/account/login')
        for client in (client, self.owner, self.staff):
            self.assertEqual(client.get('/ticket/old-secret').status_code, 410)
            self.assertEqual(client.post('/ticket/old-secret', data={'comment': 'Обход'}).status_code, 410)

    def test_account_isolation_owner_cannot_be_forged_and_retry_is_scoped(self):
        key = str(uuid.uuid4())
        response = self.create(request_key=key, applicant_id=str(self.other_id))
        self.assertEqual(response.location, '/account/tickets/1')
        self.assertEqual(self.create(request_key=key).location, response.location)
        self.assertEqual(self.create(self.other, request_key=key).status_code, 409)
        self.assertEqual(self.other.get(response.location).status_code, 404)
        self.assertEqual(self.post(self.other, response.location, comment='Чужой ответ').status_code, 404)
        self.assertNotIn('Личная заявка', self.other.get('/account').get_data(as_text=True))
        self.assertIn('Личная заявка', self.owner.get('/account').get_data(as_text=True))
        with app.app_context():
            self.assertEqual(db().execute('SELECT applicant_id FROM tickets').fetchone()[0], self.owner_id)
            self.assertEqual(db().execute('SELECT applicant_id FROM ticket_history').fetchone()[0], self.owner_id)
            token = db().execute('SELECT token FROM ticket_access').fetchone()[0]
        self.assertEqual(self.other.get('/ticket/' + token).status_code, 410)
        self.assertNotIn(token, self.owner.get(response.location).get_data(as_text=True))

    def test_own_photo_only_and_path_boundary(self):
        photo = io.BytesIO()
        Image.new('RGB', (2, 2)).save(photo, format='PNG')
        photo.seek(0)
        self.assertEqual(self.create(photo=(photo, 'photo.png')).status_code, 302)
        with self.owner.get('/account/attachments/1') as response:
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.data.startswith(b'\x89PNG'))
        self.assertEqual(self.other.get('/account/attachments/1').status_code, 404)
        self.assertEqual(self.owner.get('/admin/attachments/1').status_code, 302)
        with self.staff.get('/admin/attachments/1') as response:
            self.assertEqual(response.status_code, 200)
        with app.app_context():
            db().execute('UPDATE attachments SET file_path=?', (app.config['DATABASE'],))
            db().commit()
        self.assertEqual(self.owner.get('/account/attachments/1').status_code, 404)

    def test_staff_sees_account_and_searches_owner_without_password_leak(self):
        self.create()
        for path in ('/admin', '/admin/tickets/1', f'/admin/applicants/{self.owner_id}'):
            page = self.staff.get(path)
            self.assertEqual(page.status_code, 200)
            text = page.get_data(as_text=True)
            self.assertIn('Иванов', text)
            self.assertIn('СТ-001', text)
            self.assertNotIn('student-password', text)
            self.assertNotIn('scrypt:', text)
        self.assertIn('Личная заявка', self.staff.get('/admin?q=иванов').get_data(as_text=True))
        self.assertIn('Личная заявка', self.staff.get('/admin?q=ст-001').get_data(as_text=True))
        self.assertEqual(self.owner.get(f'/admin/applicants/{self.other_id}').status_code, 302)

    def test_reply_records_account_and_cannot_modify_status_or_owner(self):
        response = self.create()
        self.assertEqual(self.post(self.owner, response.location, comment='Ответ', status='Решена', applicant_id=str(self.other_id)).status_code, 302)
        with app.app_context():
            ticket = db().execute('SELECT status,applicant_id FROM tickets').fetchone()
            self.assertEqual(tuple(ticket), ('Новая', self.owner_id))
            self.assertEqual(db().execute('SELECT applicant_id FROM ticket_history ORDER BY id DESC').fetchone()[0], self.owner_id)
        self.assertIn('Иванов Иван', self.staff.get('/admin/tickets/1').get_data(as_text=True))

    def test_legacy_ticket_migration_does_not_claim_old_data(self):
        legacy = Path(self.temp.name) / 'legacy.sqlite'
        with closing(sqlite3.connect(legacy)) as connection:
            with connection:
                connection.executescript('''
                    CREATE TABLE rooms (id INTEGER PRIMARY KEY,building TEXT NOT NULL,name TEXT NOT NULL,UNIQUE(building,name));
                    INSERT INTO rooms VALUES (1,'А','101');
                    CREATE TABLE tickets (id INTEGER PRIMARY KEY,description TEXT NOT NULL,category TEXT NOT NULL,
                        room_id INTEGER REFERENCES rooms(id),status TEXT NOT NULL DEFAULT 'Новая',
                        created_at TEXT NOT NULL DEFAULT (datetime('now')),assignee_id INTEGER,version INTEGER NOT NULL DEFAULT 0);
                    INSERT INTO tickets (description,category,room_id) VALUES ('Старая приватная','Другое',1);
                    CREATE TABLE ticket_history (id INTEGER PRIMARY KEY,ticket_id INTEGER,employee_id INTEGER,
                        created_at TEXT NOT NULL DEFAULT (datetime('now')),change_description TEXT NOT NULL,comment TEXT,is_public INTEGER DEFAULT 0);
                    INSERT INTO ticket_history (ticket_id,change_description,comment) VALUES (1,'Заметка','Секрет');
                ''')
        app.config['DATABASE'] = str(legacy)
        init_db()
        init_db()
        client = app.test_client()
        register_applicant(client)
        self.assertEqual(client.get('/account/tickets/1').status_code, 404)
        self.assertNotIn('Старая приватная', client.get('/account').get_data(as_text=True))
        with app.app_context():
            self.assertIsNone(db().execute('SELECT applicant_id FROM tickets').fetchone()[0])
            self.assertIsNone(db().execute('SELECT applicant_id FROM ticket_history').fetchone()[0])
            self.assertEqual(db().execute('SELECT comment FROM ticket_history').fetchone()[0], 'Секрет')
            self.assertEqual(db().execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_switching_between_staff_and_applicant_revokes_previous_session(self):
        old_cookie = self.owner.get_cookie('session').value
        self.owner.get('/login')
        self.assertEqual(self.post(self.owner, '/login', login='staff', password='staff-password').status_code, 302)
        copied = app.test_client()
        copied.set_cookie('session', old_cookie)
        self.assertEqual(copied.get('/account').status_code, 302)
        staff_cookie = self.owner.get_cookie('session').value
        self.owner.get('/account/login')
        self.assertEqual(self.post(self.owner, '/account/login', record_book='СТ-001', password='student-password').status_code, 302)
        copied.set_cookie('session', staff_cookie)
        self.assertEqual(copied.get('/admin').status_code, 302)
