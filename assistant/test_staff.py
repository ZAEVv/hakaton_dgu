import tempfile
import unittest
from pathlib import Path
from werkzeug.security import generate_password_hash
from main import app, db, init_db
from test_helpers import register_applicant


class StaffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old = app.config.copy()
        app.config.update(TESTING=True, SECRET_KEY='test-only-secret', DATABASE=str(Path(self.temp.name) / 'db.sqlite'), UPLOAD_DIR=str(Path(self.temp.name) / 'uploads'))
        init_db()
        with app.app_context():
            db().execute("INSERT INTO employees (login,password_hash,name,role) VALUES (?,?,?,'admin')", ('staff', generate_password_hash('password'), 'Сотрудник'))
            db().commit()
        self.client = app.test_client()

    def tearDown(self):
        app.config.clear()
        app.config.update(self.old)
        self.temp.cleanup()

    def csrf(self):
        with self.client.session_transaction() as session:
            return session['csrf_token']

    def login(self):
        self.client.get('/login')
        return self.client.post('/login', data={'login': 'staff', 'password': 'password', 'csrf_token': self.csrf()})

    def test_statistics_count_all_tickets_even_when_filtered(self):
        with app.app_context():
            db().execute("INSERT INTO rooms VALUES (1,'Корпус','101')")
            db().executemany("INSERT INTO tickets (description,category,room_id,status) VALUES (?,?,1,?)", [
                ('Открытая', 'Другое', 'Новая'), ('Решённая', 'Другое', 'Решена'),
                ('Отклонённая', 'Другое', 'Отклонена')])
            db().commit()
        self.login()
        page = self.client.get('/admin?status=Новая').get_data(as_text=True)
        self.assertIn('Всего: <strong>3</strong>', page)
        self.assertIn('Открыто: <strong>1</strong>', page)
        self.assertIn('Решено: <strong>1</strong>', page)

    def test_excess_login_attempts_are_limited(self):
        self.client.get('/login')
        for _ in range(15):
            response = self.client.post('/login', data={'login': 'unknown', 'password': 'bad', 'csrf_token': self.csrf()})
            self.assertEqual(response.status_code, 401)
        response = self.client.post('/login', data={'login': 'staff', 'password': 'bad', 'csrf_token': self.csrf()})
        self.assertEqual(response.status_code, 429)

    def test_login_csrf_and_logout(self):
        self.client.get('/login')
        self.assertEqual(self.client.post('/login', data={'login': 'staff', 'password': 'password'}).status_code, 400)
        self.assertEqual(self.client.post('/login', data={'login': 'staff', 'password': 'wrong', 'csrf_token': self.csrf()}).status_code, 401)
        self.assertEqual(self.login().status_code, 302)
        self.assertEqual(self.client.get('/admin').status_code, 200)
        self.assertEqual(self.client.post('/logout').status_code, 400)
        self.assertEqual(self.client.post('/logout', data={'csrf_token': self.csrf()}).status_code, 302)
        self.assertEqual(self.client.get('/admin').status_code, 302)

    def test_accept_in_work_sends_public_message(self):
        with app.app_context():
            db().execute("INSERT INTO rooms VALUES (1,'Корпус','101')")
            db().execute("INSERT INTO tickets (description,category,room_id) VALUES ('Проектор','Оборудование',1)")
            db().commit()
        self.login()
        page = self.client.get('/admin/tickets/1').get_data(as_text=True)
        self.assertIn('Принять в работу и сообщить заявителю', page)
        response = self.client.post('/admin/tickets/1', data={'csrf_token': self.csrf(), 'version': '0',
            'status': 'В работе', 'assignee_id': '', 'comment': 'Заявка принята, приступаем к работе.', 'visibility': 'public'})
        self.assertEqual(response.status_code, 302)
        with app.app_context():
            self.assertEqual(db().execute('SELECT status FROM tickets WHERE id=1').fetchone()[0], 'В работе')
            history = db().execute('SELECT comment,is_public FROM ticket_history WHERE ticket_id=1').fetchone()
            self.assertEqual(tuple(history), ('Заявка принята, приступаем к работе.', 1))

    def test_staff_ticket_workflow(self):
        with app.app_context():
            db().execute("INSERT INTO rooms VALUES (1,'Корпус','101')")
            db().execute("INSERT INTO tickets (description,category,room_id) VALUES ('Лампа','Электрика',1)")
            db().commit()
        self.assertEqual(self.client.get('/admin/tickets/1').status_code, 302)
        self.assertEqual(self.client.get('/admin/attachments/1').status_code, 302)
        self.login()
        self.assertIn('Лампа'.encode(), self.client.get('/admin?q=Лампа&status=Новая').data)
        self.assertEqual(self.client.get('/admin/tickets/1').status_code, 200)
        self.assertEqual(self.client.post('/admin/tickets/1', data={'status': 'Решена'}).status_code, 400)
        data = {'csrf_token': self.csrf(), 'version': '0', 'status': 'Решена', 'assignee_id': '1', 'comment': '', 'visibility': 'public'}
        self.assertEqual(self.client.post('/admin/tickets/1', data=data).status_code, 400)
        data['comment'] = 'Заменена лампа'
        self.assertEqual(self.client.post('/admin/tickets/1', data=data).status_code, 302)
        self.assertIn('Заменена лампа'.encode(), self.client.get('/admin/tickets/1').data)
        with app.app_context():
            ticket = db().execute('SELECT * FROM tickets WHERE id=1').fetchone()
            self.assertEqual(ticket['status'], 'Решена')
            self.assertEqual(ticket['assignee_id'], 1)
            self.assertTrue(db().execute("SELECT 1 FROM ticket_history WHERE employee_id=1 AND comment='Заменена лампа'").fetchone())

    def test_all_seven_statuses_can_be_selected_and_saved(self):
        statuses = ('Новая', 'На рассмотрении', 'Назначен исполнитель', 'В работе', 'Нужны уточнения', 'Решена', 'Отклонена')
        with app.app_context():
            db().execute("INSERT INTO rooms VALUES (1,'Корпус','101')")
            db().execute("INSERT INTO tickets (description,category,room_id) VALUES ('Лампа','Электрика',1)")
            db().commit()
        self.login()
        for status in statuses:
            with self.subTest(status=status):
                self.assertIn(status.encode(), self.client.get('/admin').data)
                import re
                page = self.client.get('/admin/tickets/1').get_data(as_text=True)
                self.assertIn(status, page)
                version = re.search(r'name="version" value="([0-9]+)"', page).group(1)
                response = self.client.post('/admin/tickets/1', data={'csrf_token': self.csrf(), 'version': version, 'status': status, 'assignee_id': '', 'comment': 'Итог', 'visibility': 'public'})
                self.assertEqual(response.status_code, 302)
                with app.app_context():
                    self.assertEqual(db().execute('SELECT status FROM tickets WHERE id=1').fetchone()['status'], status)

    def test_room_and_inclusive_date_filters_combine_with_existing_filters(self):
        with app.app_context():
            db().executemany('INSERT INTO rooms VALUES (?,?,?)', [(1,'A','101'), (2,'B','101')])
            db().executemany('INSERT INTO tickets (description,category,room_id,status,created_at) VALUES (?,?,?,?,?)', [
                ('Подходит начало','Другое',1,'Новая','2025-01-01 00:00:00'),
                ('Подходит конец','Другое',1,'Новая','2025-01-02 23:59:59'),
                ('Другое помещение','Другое',2,'Новая','2025-01-01 12:00:00'),
                ('Вне даты','Другое',1,'Новая','2025-01-03 00:00:00'),
                ('Другой статус','Другое',1,'В работе','2025-01-01 12:00:00')])
            db().commit()
        self.login()
        response = self.client.get('/admin', query_string={'room_id':'1','date_from':'2025-01-01','date_to':'2025-01-02','status':'Новая'})
        text = response.get_data(as_text=True)
        self.assertIn('Подходит начало', text)
        self.assertIn('Подходит конец', text)
        for excluded in ('Другое помещение', 'Вне даты', 'Другой статус'):
            self.assertNotIn(excluded, text)
        self.assertIn('name="room_id"', text)
        self.assertIn('name="date_from"', text)
        self.assertIn('name="date_to"', text)

    def test_legacy_status_is_displayed_as_resolved_and_migrated_without_history_changes(self):
        with app.app_context():
            db().execute("INSERT INTO rooms VALUES (1,'Корпус','101')")
            db().execute("INSERT INTO tickets (description,category,room_id,status) VALUES ('Старая','Другое',1,'Закрыта')")
            db().execute("INSERT INTO ticket_history (ticket_id,change_description,comment,is_public) VALUES (1,'Статус: Новая → Закрыта','Закрыта вручную',1)")
            db().commit()
            original = tuple(db().execute('SELECT * FROM ticket_history').fetchone())
        self.login()
        text = self.client.get('/admin/tickets/1').get_data(as_text=True)
        self.assertIn('<option selected>Решена</option>', text)
        self.assertIn('Статус: Новая → Закрыта', text)
        self.assertIn('Старая'.encode(), self.client.get('/admin?status=Решена').data)
        init_db()
        init_db()
        with app.app_context():
            self.assertEqual(db().execute('SELECT status FROM tickets').fetchone()['status'], 'Решена')
            self.assertEqual([tuple(row) for row in db().execute('SELECT * FROM ticket_history')], [original])

    def test_saving_legacy_resolved_without_changes_needs_no_final_comment(self):
        with app.app_context():
            db().execute("INSERT INTO rooms VALUES (1,'Корпус','101')")
            db().execute("INSERT INTO tickets (description,category,room_id,status) VALUES ('Старая','Другое',1,'Закрыта')")
            db().commit()
        self.login()
        response = self.client.post('/admin/tickets/1', data={'csrf_token':self.csrf(), 'version':'0', 'status':'Решена', 'assignee_id':'', 'comment':'', 'visibility':'internal'})
        self.assertEqual(response.status_code, 302)
        with app.app_context():
            self.assertEqual(db().execute('SELECT COUNT(*) FROM ticket_history').fetchone()[0], 0)

    def test_stale_card_cannot_overwrite_another_clients_changes_or_history(self):
        import re
        with app.app_context():
            db().execute("INSERT INTO rooms VALUES (1,'Корпус','101')")
            db().execute("INSERT INTO tickets (description,category,room_id) VALUES ('Заявка','Другое',1)")
            db().commit()
        self.login()
        other = app.test_client()
        other.get('/login')
        with other.session_transaction() as sess:
            other_csrf = sess['csrf_token']
        other.post('/login', data={'login':'staff','password':'password','csrf_token':other_csrf})
        with other.session_transaction() as sess:
            other_csrf = sess['csrf_token']
        first_page = self.client.get('/admin/tickets/1').get_data(as_text=True)
        second_page = other.get('/admin/tickets/1').get_data(as_text=True)
        def version(page):
            match = re.search(r'name="version" value="([0-9]+)"', page)
            self.assertIsNotNone(match)
            return match.group(1)
        first = {'csrf_token':self.csrf(), 'version':version(first_page), 'status':'В работе','assignee_id':'1','comment':'Первый','visibility':'internal'}
        second = {'csrf_token':other_csrf, 'version':version(second_page), 'status':'На рассмотрении','assignee_id':'','comment':'Второй','visibility':'public'}
        self.assertEqual(self.client.post('/admin/tickets/1', data=first).status_code, 302)
        response = other.post('/admin/tickets/1', data=second)
        self.assertEqual(response.status_code, 409)
        with app.app_context():
            row = db().execute('SELECT status,assignee_id FROM tickets WHERE id=1').fetchone()
            self.assertEqual(tuple(row), ('В работе', 1))
            self.assertEqual([row['comment'] for row in db().execute('SELECT comment FROM ticket_history')], ['Первый'])

    def test_public_form_rejects_csrf(self):
        register_applicant(self.client)
        with app.app_context():
            db().execute("INSERT INTO rooms VALUES (1,'Корпус','101')")
            db().commit()
        self.client.get('/')
        self.assertEqual(self.client.post('/', data={'request_key': 'bad'}).status_code, 400)
        self.assertNotIn('Проверьте обязательные'.encode(), self.client.post('/', data={'request_key': 'bad'}).data)

    def test_hostile_csrf_value_is_rejected(self):
        self.client.get('/login')
        self.assertEqual(self.client.post('/login', data={'csrf_token': 'токен'}).status_code, 400)

    def test_security_boundaries(self):
        app.config['SECRET_KEY'] = None
        self.assertEqual(self.client.get('/login').status_code, 503)
        self.assertEqual(self.client.get('/admin').status_code, 503)
        app.config['SECRET_KEY'] = 'test-only-secret'
        response = self.login()
        cookie = response.headers.get('Set-Cookie')
        self.assertIn('HttpOnly', cookie)
        self.assertIn('Secure', cookie)
        self.assertIn('SameSite=Lax', cookie)
        self.client.get('/login')
        response = self.client.post('/login?next=https://attacker.invalid', data={'login': 'staff', 'password': 'password', 'csrf_token': self.csrf()})
        self.assertEqual(response.location, '/admin')
        with app.app_context():
            db().execute('DELETE FROM employees WHERE id=1')
            db().commit()
        self.assertEqual(self.client.get('/admin').status_code, 302)

    def test_attachment_and_private_history_are_not_public(self):
        folder = Path(app.config['UPLOAD_DIR'])
        folder.mkdir()
        image = folder / 'secret.png'
        image.write_bytes(b'attachment')
        with app.app_context():
            db().execute("INSERT INTO rooms VALUES (1,'Корпус','101')")
            db().execute("INSERT INTO tickets (description, category, room_id) VALUES ('Заявка','Другое',1)")
            db().execute("INSERT INTO ticket_access VALUES (1,'secret-token','request-key')")
            db().execute("INSERT INTO ticket_history (ticket_id,employee_id,change_description,comment,is_public) VALUES (1,1,'Заметка','очень приватно',0)")
            db().execute('INSERT INTO attachments (ticket_id,file_path) VALUES (1,?)', (str(image),))
            db().commit()
        self.assertEqual(self.client.get('/ticket/secret-token').status_code, 410)
        self.assertNotIn('очень приватно'.encode(), self.client.get('/ticket/secret-token').data)
        self.assertEqual(self.client.get('/admin/attachments/1').status_code, 302)
        self.login()
        self.assertIn('очень приватно'.encode(), self.client.get('/admin/tickets/1').data)
        response = self.client.get('/admin/attachments/1')
        self.assertEqual(response.data, b'attachment')
        response.close()
        with app.app_context():
            db().execute('UPDATE attachments SET file_path=? WHERE id=1', (str(Path(self.temp.name) / 'db.sqlite'),))
            db().commit()
        self.assertEqual(self.client.get('/admin/attachments/1').status_code, 404)

    def test_logout_revokes_copied_session_cookie(self):
        self.login()
        cookie = self.client.get_cookie('session').value
        self.client.post('/logout', data={'csrf_token': self.csrf()})
        other = app.test_client()
        other.set_cookie('session', cookie)
        self.assertEqual(other.get('/admin').status_code, 302)

    def test_panel_requires_login(self):
        self.assertEqual(self.client.get('/admin').status_code, 302)
        self.assertIn('/login', self.client.get('/admin').location)
