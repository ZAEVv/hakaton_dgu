import hashlib
from io import BytesIO
import re
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from werkzeug.security import generate_password_hash
from PIL import Image
from main import app, db, init_db, credential_hash
from test_helpers import register_applicant


class AnonymousTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = app.config.copy()
        app.config.update(TESTING=True, SECRET_KEY='test-secret', DATABASE=str(Path(self.tmp.name) / 'db.sqlite'), UPLOAD_DIR=str(Path(self.tmp.name) / 'uploads'))
        init_db()
        with app.app_context():
            db().execute("INSERT INTO rooms VALUES (1,'Корпус А','101')")
            db().execute("INSERT INTO employees (login,name,password_hash,role) VALUES ('admin','Админ',?,'admin')", (generate_password_hash('admin-password'),))
            db().commit()
        self.client = app.test_client()

    def tearDown(self):
        app.config.clear()
        app.config.update(self.old)
        self.tmp.cleanup()

    def csrf(self, client):
        with client.session_transaction() as s:
            return s['csrf_token']

    def submit(self, key=None, description='Не работает свет'):
        return self.client.post('/', data={'csrf_token': self.csrf(self.client), 'request_key': key or str(uuid.uuid4()),
                                          'description': description, 'category': 'Электрика', 'building': 'Корпус А', 'room_id': '1'})

    def test_qr_chat_create_track_update_and_privacy(self):
        page = self.client.get('/?room=1').get_data(as_text=True)
        self.assertIn('Место выбрано по QR-коду', page)
        self.assertIn('value="1" data-building="Корпус А" selected', page)
        self.assertIn('Помощник уже знает это место', page)
        with patch('main.assist', return_value={'type': 'fault', 'draft': 'Не работает свет', 'category': 'Электрика'}) as helper:
            response = self.client.post('/api/assistant', json={'message': 'свет', 'room_id': '1'}, headers={'X-CSRF-Token': self.csrf(self.client)})
            self.assertEqual(helper.call_args.kwargs['location'], {'building': 'Корпус А', 'room': '101'})
        self.assertEqual(response.json['draft'], 'Не работает свет')
        key = str(uuid.uuid4())
        result = self.submit(key)
        self.assertEqual(result.location, '/track/view')
        self.assertEqual(self.submit(key).location, '/track/view')
        page = self.client.get(result.location).get_data(as_text=True)
        code = re.search(r'id="tracking-code">([0-9]{3})', page).group(1)
        link_token = re.search(r'id="tracking-link" href="[^"]+#([0-9a-f]{64})"', page).group(1)
        self.assertIn('Заявка № 1', page)
        with app.app_context():
            self.assertEqual(db().execute('SELECT count(*) FROM tickets').fetchone()[0], 1)
            access = db().execute('SELECT token_hash, credential_hash FROM anonymous_ticket_pin_access').fetchone()
            self.assertEqual(access['token_hash'], hashlib.sha256(link_token.encode()).hexdigest())
            self.assertEqual(access['credential_hash'], credential_hash(link_token, code))
        other = app.test_client()
        self.assertEqual(other.get('/track/view').status_code, 404)
        self.assertEqual(other.get('/account/tickets/1').location, '/account/login')
        other.get('/track')
        self.assertEqual(other.post('/track', data={'csrf_token': self.csrf(other), 'code': '1'}).status_code, 400)
        self.assertEqual(other.post('/track', data={'csrf_token': self.csrf(other), 'code': code}).status_code, 400)
        wrong = f'{(int(code)+1)%1000:03d}'
        self.assertEqual(other.post('/track', data={'csrf_token': self.csrf(other), 'link_token': link_token, 'code': wrong}).status_code, 400)
        self.assertEqual(other.post('/track', data={'csrf_token': self.csrf(other), 'link_token': link_token, 'code': code}).location, '/track/view')
        staff = app.test_client()
        staff.get('/login')
        staff.post('/login', data={'csrf_token': self.csrf(staff), 'login': 'admin', 'password': 'admin-password'})
        self.assertIn('Без аккаунта', staff.get('/admin').get_data(as_text=True))
        card = staff.get('/admin/tickets/1').get_data(as_text=True)
        self.assertIn('Без аккаунта', card)
        update = {'csrf_token': self.csrf(staff), 'version': '0', 'status': 'В работе', 'assignee_id': '1', 'visibility': 'public', 'comment': 'Заявка принята, приступаем к работе.'}
        self.assertEqual(staff.post('/admin/tickets/1', data=update).status_code, 302)
        update.update(version='1', status='Нужны уточнения', visibility='internal', comment='Секретная заметка')
        self.assertEqual(staff.post('/admin/tickets/1', data=update).status_code, 302)
        text = other.get('/track/view').get_data(as_text=True)
        for expected in ('Нужны уточнения', 'Заявка принята', 'В работе → Нужны уточнения', 'Корпус А', '101'):
            self.assertIn(expected, text)
        self.assertNotIn('Секретная заметка', text)
        self.assertEqual(other.post('/track/view', data={'csrf_token': self.csrf(other), 'comment': 'Спасибо'}).status_code, 302)
        self.assertIn('Спасибо', other.get('/track/view').get_data(as_text=True))

    def test_unknown_room_and_registration_preserves_qr(self):
        self.assertIn('не найдено', self.client.get('/?room=999').get_data(as_text=True))
        self.client.get('/?room=1')
        register_applicant(self.client)
        self.assertIn('value="1" data-building="Корпус А" selected', self.client.get('/').get_data(as_text=True))
        self.assertEqual(self.submit().location, '/account/tickets/1')
        self.assertIn('Не работает свет', self.client.get('/account').get_data(as_text=True))

    def test_danger_and_ai_failure_manual_form(self):
        self.client.get('/?room=1')
        headers = {'X-CSRF-Token': self.csrf(self.client)}
        danger = self.client.post('/api/assistant', json={'message': 'из розетки идут искры'}, headers=headers)
        self.assertEqual(danger.json['type'], 'danger')
        self.assertIn('не трогайте', danger.json['answer'])
        self.assertEqual(self.submit(description='Из розетки идут искры').location, '/track/view')
        with patch.dict('os.environ', {'DEEPSEEK_API_KEY': ''}):
            self.assertEqual(self.client.post('/api/assistant', json={'message': 'не работает свет'}, headers=headers).status_code, 503)
        self.assertEqual(self.submit().location, '/track/view')

    def test_old_link_and_guessed_request_key_do_not_grant_access(self):
        self.client.get('/')
        key = str(uuid.uuid4())
        self.submit(key)
        stranger = app.test_client()
        stranger.get('/?room=1')
        self.assertEqual(stranger.post('/', data={'csrf_token': self.csrf(stranger), 'request_key': key, 'description': 'x', 'category': 'Электрика', 'building': 'Корпус А', 'room_id': '1'}).status_code, 409)
        self.assertEqual(stranger.get('/ticket/old-secret').status_code, 410)
        self.assertEqual(stranger.get('/admin').location, '/login')
        self.assertEqual(stranger.get('/admin/qr').location, '/login')

    def test_anonymous_photo_access_and_tracking_csrf(self):
        self.client.get('/')
        photo = BytesIO()
        Image.new('RGB', (2, 2), 'red').save(photo, format='PNG')
        photo.seek(0)
        result = self.client.post('/', data={'csrf_token': self.csrf(self.client), 'request_key': str(uuid.uuid4()),
            'description': 'Фото', 'category': 'Другое', 'building': 'Корпус А', 'room_id': '1', 'photo': (photo, 'test.png')})
        self.assertEqual(result.location, '/track/view')
        response = self.client.get('/track/attachments/1')
        self.assertEqual(response.status_code, 200)
        response.close()
        self.assertEqual(self.client.get('/track/attachments/999').status_code, 404)
        self.assertEqual(app.test_client().get('/track/attachments/1').status_code, 404)
        self.assertEqual(self.client.post('/track/view', data={'comment': 'Без CSRF'}).status_code, 400)

    def test_anonymous_ai_limit_and_warning_bypass(self):
        self.client.get('/')
        headers = {'X-CSRF-Token': self.csrf(self.client)}
        with patch.dict('os.environ', {'DEEPSEEK_API_KEY': ''}):
            for _ in range(10):
                self.assertEqual(self.client.post('/api/assistant', json={'message': 'не работает свет'}, headers=headers).status_code, 503)
            self.assertEqual(self.client.post('/api/assistant', json={'message': 'не работает свет'}, headers=headers).status_code, 429)
            self.assertEqual(self.client.post('/api/assistant', json={'message': 'из розетки идут искры'}, headers=headers).json['type'], 'danger')

    def test_migration_does_not_enable_historical_access(self):
        with app.app_context():
            db().execute("INSERT INTO tickets (description,category,room_id) VALUES ('Старая','Другое',1)")
            db().execute("INSERT INTO ticket_access (ticket_id,token,request_key) VALUES (1,'old-token','old-key')")
            db().commit()
        init_db()
        init_db()
        with app.app_context():
            self.assertEqual(db().execute('SELECT COUNT(*) FROM anonymous_ticket_access').fetchone()[0], 0)
            self.assertEqual(db().execute('SELECT description FROM tickets WHERE id=1').fetchone()[0], 'Старая')
        self.assertEqual(self.client.get('/ticket/old-token').status_code, 410)

    def test_prior_anonymous_codes_still_work(self):
        code = 'a' * 64
        with app.app_context():
            db().execute("INSERT INTO tickets (description,category,room_id) VALUES ('Прежняя','Другое',1)")
            db().execute('INSERT INTO anonymous_ticket_access (ticket_id,token_hash) VALUES (?,?)', (1, hashlib.sha256(code.encode()).hexdigest()))
            db().commit()
        self.client.get('/track')
        self.assertEqual(self.client.post('/track', data={'csrf_token': self.csrf(self.client), 'code': code}).location, '/track/view')
        self.assertIn('Прежняя', self.client.get('/track/view').get_data(as_text=True))

    def test_pin_limit_applies_across_clients(self):
        self.client.get('/')
        self.submit()
        page = self.client.get('/track/view').get_data(as_text=True)
        code = re.search(r'id="tracking-code">([0-9]{3})', page).group(1)
        link_token = re.search(r'id="tracking-link" href="[^"]+#([0-9a-f]{64})"', page).group(1)
        wrong = f'{(int(code)+1)%1000:03d}'
        for i in range(4):
            client = app.test_client()
            client.environ_base['REMOTE_ADDR'] = f'192.0.2.{i+1}'
            client.get('/track')
            response = client.post('/track', data={'csrf_token': self.csrf(client), 'link_token': link_token, 'code': wrong})
            self.assertEqual(response.status_code, 400 if i < 3 else 429)


if __name__ == '__main__':
    unittest.main()
