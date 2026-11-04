import tempfile
import unittest
from pathlib import Path
from werkzeug.security import generate_password_hash
from main import app, db, init_db
from test_helpers import register_applicant


class FreshStaffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = app.config.copy()
        app.config.update(TESTING=True, SECRET_KEY='fresh-test', DATABASE=str(Path(self.tmp.name) / 'db.sqlite'), UPLOAD_DIR=str(Path(self.tmp.name) / 'uploads'))
        init_db()
        with app.app_context():
            for login, role in [('admin', 'admin'), ('worker', 'employee')]:
                db().execute('INSERT INTO employees(login,name,password_hash,role) VALUES (?,?,?,?)', (login, login, generate_password_hash('test-password'), role))
            db().execute("INSERT INTO rooms VALUES (1,'Корпус','101')")
            db().execute("INSERT INTO tickets(description,category,room_id) VALUES ('Проверка','Электрика',1)")
            db().commit()
        self.client = app.test_client()

    def tearDown(self):
        app.config.clear()
        app.config.update(self.old)
        self.tmp.cleanup()

    def token(self, client):
        with client.session_transaction() as session:
            return session['csrf_token']

    def login(self, login):
        client = app.test_client()
        client.get('/login')
        self.assertEqual(client.post('/login', data={'csrf_token': self.token(client), 'login': login, 'password': 'test-password'}).status_code, 302)
        return client

    def test_fresh_login_shell_and_accessible_queue(self):
        login = self.client.get('/login').get_data(as_text=True)
        self.assertNotIn('staff.css', login)
        self.assertIn('class="auth-form"', login)
        self.assertIn('name="csrf_token"', login)
        admin = self.login('admin')
        queue = admin.get('/admin').get_data(as_text=True)
        for text in ('role="region" aria-label="Таблица заявок" tabindex="0" aria-describedby="table-scroll-help"', 'id="table-scroll-help"', 'name="room_id"', 'Проверка'):
            self.assertIn(text, queue)

    def test_roles_and_management_pages(self):
        worker = self.login('worker')
        admin = self.login('admin')
        for path in ('/admin/categories', '/admin/employees', '/admin/qr'):
            self.assertEqual(self.client.get(path).status_code, 302)
            self.assertEqual(worker.get(path).status_code, 403)
            page = admin.get(path)
            self.assertEqual(page.status_code, 200)
            self.assertIn('name="csrf_token"', page.get_data(as_text=True))
        self.assertNotIn('Категории</a>', worker.get('/admin').get_data(as_text=True))
        self.assertIn('Категории</a>', admin.get('/admin').get_data(as_text=True))

    def test_ticket_claim_edit_validation_and_logout(self):
        worker = self.login('worker')
        page = worker.get('/admin/tickets/1').get_data(as_text=True)
        self.assertIn('Взять заявку себе', page)
        self.assertNotIn('name="version"', page)
        self.assertEqual(worker.post('/admin/tickets/1/claim', data={'csrf_token': self.token(worker)}).status_code, 302)
        page = worker.get('/admin/tickets/1').get_data(as_text=True)
        self.assertIn('name="version" value="1"', page)
        data = {'csrf_token': self.token(worker), 'version': '1', 'status': 'Решена', 'assignee_id': '2', 'comment': '', 'visibility': 'public'}
        response = worker.post('/admin/tickets/1', data=data)
        self.assertEqual(response.status_code, 400)
        self.assertIn('role="alert"', response.get_data(as_text=True))
        data['comment'] = 'Готово'
        self.assertEqual(worker.post('/admin/tickets/1', data=data).status_code, 302)
        self.assertIn('Готово', worker.get('/admin/tickets/1').get_data(as_text=True))
        self.assertEqual(worker.post('/logout', data={'csrf_token': self.token(worker)}).status_code, 302)
        self.assertEqual(worker.get('/admin').status_code, 302)

    def test_applicant_page_and_filter_state(self):
        applicant = app.test_client()
        applicant_id = register_applicant(applicant)
        with app.app_context():
            db().execute('UPDATE tickets SET applicant_id=? WHERE id=1', (applicant_id,))
            db().commit()
        admin = self.login('admin')
        page = admin.get('/admin/applicants/%s' % applicant_id)
        self.assertEqual(page.status_code, 200)
        self.assertIn('Иванов', page.get_data(as_text=True))
        queue = admin.get('/admin', query_string={'q':'Проверка', 'room_id':'1'}).get_data(as_text=True)
        self.assertIn('value="Проверка"', queue)
        self.assertIn('Проверка', queue)
