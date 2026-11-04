import tempfile
import uuid
from unittest.mock import patch
from test_helpers import register_applicant
import unittest
from pathlib import Path
from werkzeug.security import generate_password_hash
from main import app, db, init_db


class CategoriesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old = app.config.copy()
        app.config.update(TESTING=True, SECRET_KEY='test-secret', DATABASE=str(Path(self.temp.name) / 'db.sqlite'))
        init_db()
        with app.app_context():
            db().execute("INSERT INTO employees(login,name,password_hash,role) VALUES ('admin','Admin',?,'admin')", (generate_password_hash('test-password'),))
            db().commit()
        self.client = app.test_client()
        self.client.get('/login')
        with self.client.session_transaction() as s:
            token = s['csrf_token']
        self.client.post('/login', data={'csrf_token': token, 'login': 'admin', 'password': 'test-password'})

    def tearDown(self):
        app.config.clear()
        app.config.update(self.old)
        self.temp.cleanup()

    def post(self, **data):
        with self.client.session_transaction() as s:
            data['csrf_token'] = s['csrf_token']
        return self.client.post('/admin/categories', data=data)

    def test_admin_can_create_category_for_new_tickets(self):
        self.assertEqual(self.post(action='create', name='Связь').status_code, 302)
        with app.app_context():
            self.assertIsNotNone(db().execute("SELECT id FROM categories WHERE name='Связь' AND is_active=1").fetchone())

    def test_historical_name_cannot_be_reused_after_rename(self):
        with app.app_context():
            db().execute("INSERT INTO rooms VALUES (1,'А','101')")
            db().execute("INSERT INTO tickets(description,category,room_id) VALUES ('Старая','Электрика',1)")
            db().commit()
        self.assertEqual(self.post(action='rename', category_id='1', name='Свет').status_code, 302)
        self.assertEqual(self.post(action='create', name='электрика').status_code, 400)

    def test_permissions_csrf_and_validation(self):
        anonymous = app.test_client()
        self.assertEqual(anonymous.get('/admin/categories').status_code, 302)
        self.assertEqual(anonymous.post('/admin/categories').status_code, 302)
        with app.app_context():
            db().execute("INSERT INTO employees(login,name,password_hash,role) VALUES ('worker','Worker',?,'employee')", (generate_password_hash('test-password'),))
            db().commit()
        worker = app.test_client()
        worker.get('/login')
        with worker.session_transaction() as session:
            token = session['csrf_token']
        worker.post('/login', data={'csrf_token': token, 'login': 'worker', 'password': 'test-password'})
        self.assertEqual(worker.get('/admin/categories').status_code, 403)
        self.assertEqual(worker.post('/admin/categories', data={'csrf_token': token, 'action': 'create', 'name': 'X'}).status_code, 403)
        self.assertEqual(self.client.post('/admin/categories', data={'action': 'create', 'name': 'X'}).status_code, 400)
        for name in (' ', 'x' * 121, 'ЭЛЕКТРИКА', 'bad\nname'):
            self.assertEqual(self.post(action='create', name=name).status_code, 400)
        self.assertEqual(self.post(action='rename', category_id='999', name='Нет').status_code, 404)
        self.assertEqual(self.post(action='delete', category_id='1').status_code, 400)

    def test_disable_rename_preserve_existing_and_filter_and_new_forms(self):
        with app.app_context():
            db().execute("INSERT INTO rooms VALUES (1,'А','101')")
            db().execute("INSERT INTO tickets(description,category,room_id) VALUES ('Старая','Электрика',1)")
            db().commit()
        self.assertEqual(self.post(action='rename', category_id='1', name='Свет').status_code, 302)
        self.assertEqual(self.post(action='disable', category_id='1').status_code, 302)
        page = self.client.get('/admin?category=Электрика').get_data(as_text=True)
        self.assertIn('Старая', page)
        self.assertIn('Электрика', page)
        applicant = app.test_client()
        register_applicant(applicant)
        with applicant.session_transaction() as session:
            csrf = session['csrf_token']
        page = applicant.get('/').get_data(as_text=True)
        self.assertNotIn('value="Свет"', page)
        self.assertNotIn('value="Электрика"', page)
        form = {'csrf_token': csrf, 'request_key': str(uuid.uuid4()), 'description': 'Сломалось', 'category': 'Свет', 'room_id': '1', 'building': 'А'}
        self.assertEqual(applicant.post('/', data=form).status_code, 400)
        with patch('main.assist', return_value={'type': 'unclear'}) as classify:
            self.assertEqual(applicant.post('/api/assistant', json={'message': 'Не работает'}, headers={'X-CSRF-Token': csrf}).status_code, 200)
            self.assertNotIn('Свет', classify.call_args.args[2])
        self.assertEqual(self.post(action='enable', category_id='1').status_code, 302)
        self.assertEqual(applicant.post('/', data=form).status_code, 302)
        with app.app_context():
            self.assertEqual([r[0] for r in db().execute('SELECT category FROM tickets ORDER BY id')], ['Электрика', 'Свет'])

    def test_migration_preserves_custom_old_tickets_and_is_idempotent(self):
        with app.app_context():
            db().execute("INSERT INTO rooms VALUES (1,'А','101')")
            db().execute("INSERT INTO tickets(description,category,room_id) VALUES ('Старая','Старая категория',1)")
            db().execute('DROP TABLE categories')
            db().commit()
        init_db()
        init_db()
        with app.app_context():
            self.assertEqual(db().execute('SELECT category FROM tickets').fetchone()[0], 'Старая категория')
            self.assertEqual(db().execute("SELECT is_active FROM categories WHERE name='Старая категория'").fetchone()[0], 0)
            self.assertEqual(db().execute('SELECT COUNT(*) FROM categories').fetchone()[0], 6)
        self.assertIn('Старая категория', self.client.get('/admin').get_data(as_text=True))


    def test_last_active_category_cannot_be_disabled_and_retry_is_safe(self):
        with app.app_context():
            db().execute("UPDATE categories SET is_active=0 WHERE id != 1")
            db().execute("INSERT INTO rooms VALUES (1,'А','101')")
            db().execute("INSERT INTO tickets(description,category,room_id) VALUES ('Сохранить','Электрика',1)")
            db().commit()
        response = self.post(action='disable', category_id='1')
        self.assertEqual(response.status_code, 400)
        self.assertIn('последнюю активную категорию', response.get_data(as_text=True))
        self.assertEqual(self.post(action='disable', category_id='2').status_code, 302)
        self.assertEqual(self.post(action='disable', category_id='999').status_code, 404)
        self.assertEqual(self.post(action='rename', category_id='1', name='Свет').status_code, 302)
        with app.app_context():
            self.assertEqual(db().execute('SELECT COUNT(*) FROM categories WHERE is_active=1').fetchone()[0], 1)
            self.assertEqual(db().execute('SELECT description,category FROM tickets').fetchone()[:], ('Сохранить','Электрика'))

    def test_parallel_disables_leave_one_active_category(self):
        import inspect
        import threading
        from concurrent.futures import ThreadPoolExecutor
        import main
        with app.app_context():
            db().execute('UPDATE categories SET is_active=0 WHERE id > 2')
            db().commit()
        clients = [app.test_client(), app.test_client()]
        with self.client.session_transaction() as session:
            credentials = dict(session)
        for client in clients:
            with client.session_transaction() as session:
                session.update(credentials)
        barrier = threading.Barrier(2)
        local = threading.local()
        original = main.db
        def synchronized_db():
            if not getattr(local, 'entered', False) and any(f.function == 'protected' for f in inspect.stack()):
                local.entered = True
                barrier.wait(timeout=5)
            return original()
        def disable(index):
            return clients[index].post('/admin/categories', data={
                'csrf_token': credentials['csrf_token'], 'action':'disable', 'category_id': str(index + 1)}).status_code
        with patch('main.db', side_effect=synchronized_db), ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(disable, range(2)))
        self.assertEqual(sorted(results), [302, 400])
        with app.app_context():
            self.assertEqual(db().execute('SELECT COUNT(*) FROM categories WHERE is_active=1').fetchone()[0], 1)
