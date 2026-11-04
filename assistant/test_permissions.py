import sqlite3
import tempfile
import unittest
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash
from main import app, db, init_db
from test_helpers import register_applicant


class PermissionsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old = app.config.copy()
        app.config.update(TESTING=True, SECRET_KEY='test-secret', DATABASE=str(Path(self.temp.name) / 'db.sqlite'),
                          UPLOAD_DIR=str(Path(self.temp.name) / 'uploads'))
        init_db()
        with app.app_context():
            for login, role in [('admin', 'admin'), ('worker', 'employee'), ('other', 'employee')]:
                db().execute('INSERT INTO employees (login,name,password_hash,role) VALUES (?,?,?,?)',
                             (login, login, generate_password_hash('test-password'), role))
            db().execute("INSERT INTO rooms VALUES (1,'А','101')")
            db().execute("INSERT INTO tickets (description,category,room_id) VALUES ('Сломана ЛАМПА','Электрика',1)")
            db().execute("INSERT INTO ticket_access VALUES (1,'secret-token','request-key')")
            db().commit()
        self.admin = self.login('admin')
        self.worker = self.login('worker')
        self.other = self.login('other')
        self.applicant = app.test_client()
        applicant_id = register_applicant(self.applicant)
        with app.app_context():
            db().execute('UPDATE tickets SET applicant_id=? WHERE id=1', (applicant_id,))
            db().commit()

    def tearDown(self):
        app.config.clear()
        app.config.update(self.old)
        self.temp.cleanup()

    def login(self, login):
        client = app.test_client()
        client.get('/login')
        self.assertEqual(self.post(client, '/login', login=login, password='test-password').status_code, 302)
        return client

    def post(self, client, path, **data):
        with client.session_transaction() as sess:
            data.setdefault('csrf_token', sess['csrf_token'])
        return client.post(path, data=data)

    def update(self, client, **changes):
        with app.app_context():
            item = db().execute('SELECT * FROM tickets WHERE id=1').fetchone()
        data = dict(version=str(item['version']), status=item['status'], assignee_id=str(item['assignee_id'] or ''),
                    comment='Комментарий', visibility='internal')
        data.update(changes)
        return self.post(client, '/admin/tickets/1', **data)

    def test_worker_reads_all_but_cannot_modify_others_or_manage_staff(self):
        self.assertEqual(self.worker.get('/admin').status_code, 200)
        self.assertEqual(self.worker.get('/admin/tickets/1').status_code, 200)
        self.assertEqual(self.update(self.worker).status_code, 403)
        self.assertEqual(self.worker.get('/admin/employees').status_code, 403)
        self.assertEqual(self.post(self.worker, '/admin/employees', action='block', employee_id='1').status_code, 403)
        self.assertEqual(self.post(self.worker, '/admin/employees', action='create', login='evil', name='evil', password='test-password', role='admin').status_code, 403)

    def test_claim_and_own_updates_cannot_reassign(self):
        self.assertEqual(self.worker.post('/admin/tickets/1/claim').status_code, 400)
        self.assertEqual(self.post(self.worker, '/admin/tickets/1/claim').status_code, 302)
        self.assertEqual(self.post(self.other, '/admin/tickets/1/claim').status_code, 409)
        self.assertEqual(self.update(self.other).status_code, 403)
        self.assertEqual(self.update(self.worker, assignee_id='3').status_code, 403)
        self.assertEqual(self.update(self.worker, status='В работе').status_code, 302)
        with app.app_context():
            self.assertEqual(db().execute('SELECT assignee_id FROM tickets').fetchone()[0], 2)
            self.assertEqual(db().execute('SELECT COUNT(*) FROM ticket_history').fetchone()[0], 2)

    def test_concurrent_claims_have_one_winner_and_one_history_entry(self):
        barrier = Barrier(2)

        def claim(client):
            barrier.wait(timeout=5)
            return self.post(client, '/admin/tickets/1/claim').status_code

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(claim, [self.worker, self.other]))
        self.assertEqual(sorted(results), [302, 409])
        with app.app_context():
            self.assertEqual(db().execute('SELECT COUNT(*) FROM ticket_history').fetchone()[0], 1)
            self.assertEqual(db().execute('SELECT version FROM tickets').fetchone()[0], 1)

    def test_resolution_and_rejection_require_public_nonblank_result_and_allow_reopen(self):
        self.post(self.worker, '/admin/tickets/1/claim')
        for status in ('Решена', 'Отклонена'):
            self.assertEqual(self.update(self.worker, status=status, comment='  ', visibility='public').status_code, 400)
            self.assertEqual(self.update(self.worker, status=status, visibility='internal').status_code, 400)
            self.assertEqual(self.update(self.worker, status=status, comment='Публичный итог', visibility='public').status_code, 302)
            self.assertEqual(self.update(self.worker, status='В работе').status_code, 302)
        page = self.applicant.get('/account/tickets/1').get_data(as_text=True)
        self.assertIn('Публичный итог', page)

    def test_create_employee_hash_duplicate_and_no_role_escalation(self):
        self.assertEqual(self.post(self.admin, '/admin/employees', action='create', login='new', name='Новый', password='long-password', role='admin').status_code, 302)
        with app.app_context():
            employee = db().execute("SELECT * FROM employees WHERE login='new'").fetchone()
            self.assertEqual(employee['role'], 'employee')
            self.assertNotEqual(employee['password_hash'], 'long-password')
            self.assertTrue(check_password_hash(employee['password_hash'], 'long-password'))
        self.assertEqual(self.post(self.admin, '/admin/employees', action='create', login='new', name='Новый', password='long-password').status_code, 400)
        self.assertEqual(self.post(self.admin, '/admin/employees', action='create', login='short', name='Новый', password='123').status_code, 400)
        self.assertIn('Создана учётная запись'.encode(), self.admin.get('/admin/employees').data)

    def test_admin_reassignment_immediately_removes_previous_workers_write_access(self):
        self.post(self.worker, '/admin/tickets/1/claim')
        self.assertEqual(self.update(self.admin, assignee_id='3').status_code, 302)
        self.assertEqual(self.update(self.worker, status='В работе').status_code, 403)
        self.assertEqual(self.update(self.other, status='В работе').status_code, 302)
        self.post(self.admin, '/admin/employees', action='block', employee_id='2')
        self.assertEqual(self.update(self.admin, assignee_id='2').status_code, 400)
        with app.app_context():
            self.assertEqual(db().execute('SELECT assignee_id FROM tickets').fetchone()[0], 3)

    def test_block_revokes_session_releases_open_tickets_and_preserves_history(self):
        self.post(self.worker, '/admin/tickets/1/claim')
        with app.app_context():
            db().execute("INSERT INTO tickets (description,category,room_id,status,assignee_id) VALUES ('Готово','Другое',1,'Решена',2)")
            db().commit()
        self.assertEqual(self.post(self.admin, '/admin/employees', action='block', employee_id='2').status_code, 302)
        self.assertEqual(self.worker.get('/admin').status_code, 302)
        self.assertEqual(self.worker.get('/admin/attachments/1').status_code, 302)
        with app.app_context():
            rows = db().execute('SELECT assignee_id FROM tickets ORDER BY id').fetchall()
            self.assertIsNone(rows[0][0])
            self.assertEqual(rows[1][0], 2)
            self.assertIn('блокировка', db().execute('SELECT change_description FROM ticket_history ORDER BY id DESC').fetchone()[0])
        self.worker.get('/login')
        self.assertEqual(self.post(self.worker, '/login', login='worker', password='test-password').status_code, 401)
        self.assertEqual(self.post(self.admin, '/admin/employees', action='unblock', employee_id='2').status_code, 302)
        self.assertEqual(self.post(self.worker, '/login', login='worker', password='test-password').status_code, 302)
        self.assertEqual(self.post(self.other, '/admin/tickets/1/claim').status_code, 302)
        self.assertEqual(self.post(self.admin, '/admin/employees', action='block', employee_id='1').status_code, 400)

    def test_password_reset_revokes_sessions(self):
        self.assertEqual(self.post(self.admin, '/admin/employees', action='reset_password', employee_id='2', password='replacement-password').status_code, 302)
        self.assertEqual(self.worker.get('/admin').status_code, 302)
        self.worker.get('/login')
        self.assertEqual(self.post(self.worker, '/login', login='worker', password='test-password').status_code, 401)
        self.assertEqual(self.post(self.worker, '/login', login='worker', password='replacement-password').status_code, 302)

    def test_audit_failure_rolls_back_block_and_reassignment(self):
        self.post(self.worker, '/admin/tickets/1/claim')
        with app.app_context():
            db().execute("CREATE TRIGGER fail_audit BEFORE INSERT ON employee_history BEGIN SELECT RAISE(ABORT, 'test'); END")
            db().commit()
        with patch.object(app.logger, 'exception'):
            self.assertEqual(self.post(self.admin, '/admin/employees', action='block', employee_id='2').status_code, 503)
        self.assertEqual(self.worker.get('/admin').status_code, 200)
        with app.app_context():
            self.assertEqual(db().execute('SELECT assignee_id FROM tickets').fetchone()[0], 2)
            self.assertEqual(db().execute('SELECT is_active FROM employees WHERE id=2').fetchone()[0], 1)
            self.assertEqual(db().execute('SELECT COUNT(*) FROM ticket_history').fetchone()[0], 1)

    def test_applicant_replies_validation_csrf_and_automatic_status(self):
        client = self.applicant
        client.get('/account/tickets/1')
        self.assertEqual(client.post('/account/tickets/1', data={'comment': 'Ответ'}).status_code, 400)
        for comment in (' ', 'a' * 5001):
            self.assertEqual(self.post(client, '/account/tickets/1', comment=comment).status_code, 400)
        self.assertEqual(self.update(self.admin, status='Нужны уточнения', comment='Приватно').status_code, 302)
        self.assertEqual(self.post(client, '/account/tickets/1', comment='<script>Ответ</script>').status_code, 302)
        page = client.get('/account/tickets/1').get_data(as_text=True)
        self.assertIn('&lt;script&gt;Ответ&lt;/script&gt;', page)
        self.assertNotIn('Приватно', page)
        with app.app_context():
            item = db().execute('SELECT status,version FROM tickets WHERE id=1').fetchone()
            self.assertEqual(tuple(item), ('В работе', 2))
            history = db().execute('SELECT * FROM ticket_history ORDER BY id DESC').fetchone()
            self.assertIsNone(history['employee_id'])
            self.assertEqual(history['is_public'], 1)
        self.assertEqual(self.post(client, '/account/tickets/999', comment='Ответ').status_code, 404)
        self.assertEqual(self.update(self.admin, status='Решена', visibility='public').status_code, 302)
        self.assertEqual(self.post(client, '/account/tickets/1', comment='Поздно').status_code, 409)

    def test_applicant_reply_invalidates_staff_card_and_search_handles_cyrillic(self):
        client = self.applicant
        client.get('/account/tickets/1')
        self.post(client, '/account/tickets/1', comment='Дополнение')
        self.assertEqual(self.update(self.admin, version='0').status_code, 409)
        self.assertIn('Сломана ЛАМПА'.encode(), self.worker.get('/admin?q=лампа').data)

    def test_legacy_employee_migration_is_idempotent(self):
        legacy = Path(self.temp.name) / 'legacy.sqlite'
        with closing(sqlite3.connect(legacy)) as connection:
            with connection:
                connection.execute('CREATE TABLE employees (id INTEGER PRIMARY KEY, login TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, name TEXT NOT NULL)')
                connection.execute("INSERT INTO employees VALUES (1,'old','existing-hash','Старый')")
        app.config['DATABASE'] = str(legacy)
        init_db()
        init_db()
        with app.app_context():
            employee = db().execute('SELECT * FROM employees').fetchone()
            self.assertEqual(employee['role'], 'admin')
            self.assertEqual(employee['is_active'], 1)
            self.assertEqual(employee['password_hash'], 'existing-hash')
            db().execute("INSERT INTO employees (login,password_hash,name) VALUES ('new','hash','Новый')")
            self.assertEqual(db().execute("SELECT role FROM employees WHERE login='new'").fetchone()[0], 'employee')

    def test_worker_can_download_photos_of_unassigned_and_other_tickets(self):
        folder = Path(app.config['UPLOAD_DIR'])
        folder.mkdir()
        image = folder / 'photo.png'
        image.write_bytes(b'photo-content')
        with app.app_context():
            db().execute('INSERT INTO attachments (ticket_id,file_path) VALUES (1,?)', (str(image),))
            db().commit()
        self.assertEqual(app.test_client().get('/admin/attachments/1').status_code, 302)
        with self.worker.get('/admin/attachments/1') as response:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, b'photo-content')
        self.post(self.other, '/admin/tickets/1/claim')
        with self.worker.get('/admin/attachments/1') as response:
            self.assertEqual(response.status_code, 200)

    def test_unauthed_writes_do_not_change_ticket(self):
        client = app.test_client()
        self.assertEqual(client.post('/admin/tickets/1/claim').status_code, 302)
        self.assertEqual(client.post('/admin/tickets/1', data={'status': 'Решена'}).status_code, 302)
        self.assertEqual(client.post('/admin/employees', data={'action': 'block', 'employee_id': '1'}).status_code, 302)
        with app.app_context():
            self.assertEqual(tuple(db().execute('SELECT status,assignee_id,version FROM tickets').fetchone()), ('Новая', None, 0))

    def test_create_admin_command(self):
        result = app.test_cli_runner().invoke(args=['create-admin', '--login', 'root', '--name', 'Админ', '--password', 'strong-password'])
        self.assertEqual(result.exit_code, 0, result.output)
        with app.app_context():
            self.assertEqual(db().execute("SELECT role FROM employees WHERE login='root'").fetchone()[0], 'admin')
        duplicate = app.test_cli_runner().invoke(args=['create-admin', '--login', 'root', '--name', 'Админ', '--password', 'strong-password'])
        self.assertNotEqual(duplicate.exit_code, 0)
