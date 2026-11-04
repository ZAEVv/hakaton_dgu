import re
import tempfile
import unittest
import uuid
from pathlib import Path

from werkzeug.security import generate_password_hash
from main import app, db, init_db
from test_helpers import register_applicant


class TrackingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old = app.config.copy()
        app.config.update(TESTING=True, SECRET_KEY='test-secret', DATABASE=str(Path(self.temp.name) / 'db.sqlite'))
        init_db()
        with app.app_context():
            db().execute("INSERT INTO rooms VALUES (1,'Корпус А','101')")
            db().execute("INSERT INTO employees (login,password_hash,name,role) VALUES (?,?,?,'admin')", ('staff', generate_password_hash('password'), 'Работник'))
            db().commit()
        self.applicant = app.test_client()
        register_applicant(self.applicant)
        self.other_applicant = app.test_client()
        register_applicant(self.other_applicant, record_book='TEST-002', first_name='Пётр', last_name='Петров')
        self.staff = app.test_client()

    def tearDown(self):
        app.config.clear()
        app.config.update(self.old)
        self.temp.cleanup()

    def csrf(self, client):
        with client.session_transaction() as session:
            return session['csrf_token']

    def create(self, description, client=None):
        client = client or self.applicant
        client.get('/')
        return client.post('/', data={'csrf_token': self.csrf(client), 'request_key': str(uuid.uuid4()),
            'description': description, 'category': 'Электрика', 'building': 'Корпус А', 'room_id': '1'}).location

    def test_applicant_tracks_staff_updates_without_private_or_other_ticket_data(self):
        link = self.create('Сломана лампа <script>')
        other_link = self.create('Чужое описание', self.other_applicant)
        self.staff.get('/login')
        self.assertEqual(self.staff.post('/login', data={'csrf_token': self.csrf(self.staff), 'login': 'staff', 'password': 'password'}).status_code, 302)
        card = self.staff.get('/admin/tickets/1').get_data(as_text=True)
        version = re.search(r'name="version" value="(\d+)"', card).group(1)
        update = {'csrf_token': self.csrf(self.staff), 'version': version, 'status': 'В работе', 'assignee_id': '1', 'comment': 'Публичный комментарий', 'visibility': 'public'}
        self.assertEqual(self.staff.post('/admin/tickets/1', data=update).status_code, 302)
        update.update(version='1', status='Нужны уточнения', comment='Секретная внутренняя заметка', visibility='internal')
        self.assertEqual(self.staff.post('/admin/tickets/1', data=update).status_code, 302)
        page = self.applicant.get(link)
        text = page.get_data(as_text=True)
        self.assertEqual(page.status_code, 200)
        for expected in ('Заявка № 1', 'Сломана лампа &lt;script&gt;', 'Электрика', 'Корпус А', '101', 'Нужны уточнения', 'Новая → В работе', 'В работе → Нужны уточнения', 'Публичный комментарий', 'Заявка создана заявителем'):
            self.assertIn(expected, text)
        with app.app_context():
            date = db().execute('SELECT created_at FROM tickets WHERE id=1').fetchone()[0]
        self.assertIn(date, text)
        for forbidden in ('Секретная внутренняя заметка', 'Чужое описание', '<script>'):
            self.assertNotIn(forbidden, text)
        self.assertEqual(self.applicant.get(other_link).status_code, 404)
        self.assertNotIn('Сломана лампа', self.other_applicant.get(other_link).get_data(as_text=True))
        invalid = self.applicant.get('/account/tickets/999')
        self.assertEqual(invalid.status_code, 404)
        self.assertNotIn('Сломана лампа', invalid.get_data(as_text=True))
        self.assertEqual(page.headers['Cache-Control'], 'no-store')
        self.assertEqual(page.headers['Referrer-Policy'], 'no-referrer')
