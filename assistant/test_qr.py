import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile
from unittest.mock import patch
import qrcode
from werkzeug.security import generate_password_hash
from main import app, db, init_db
from test_helpers import register_applicant


class QRTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config = app.config.copy()
        app.config.update(TESTING=True, SECRET_KEY='qr-test', DATABASE=str(Path(self.tmp.name) / 'db.sqlite'), UPLOAD_DIR=str(Path(self.tmp.name) / 'uploads'))
        init_db()
        with app.app_context():
            db().execute("INSERT INTO rooms VALUES (1, 'Корпус', 'Кабинет 214')")
            db().execute("INSERT INTO employees (login,name,password_hash,role) VALUES ('admin','Админ',?,'admin')", (generate_password_hash('admin-password'),))
            db().commit()

    def tearDown(self):
        app.config.clear()
        app.config.update(self.config)
        self.tmp.cleanup()

    def test_qr_survives_registration_and_unknown_room_falls_back(self):
        client = app.test_client()
        initial = client.get('/?room=1')
        self.assertEqual(initial.status_code, 200)
        self.assertIn('mobile-chat.css', initial.get_data(as_text=True))
        self.assertIn('mobile-form-shortcut', initial.get_data(as_text=True))
        self.assertIn('id="ticket-form"', initial.get_data(as_text=True))
        self.assertIn('id="chat-attach"', initial.get_data(as_text=True))
        self.assertIn('name="photo"', initial.get_data(as_text=True))
        register_applicant(client)
        response = client.get('/')
        self.assertIn('Место выбрано по QR-коду', response.get_data(as_text=True))
        self.assertIn('Корпус, Кабинет 214', response.get_data(as_text=True))
        self.assertIn('value="1" data-building="Корпус" selected', response.get_data(as_text=True))
        self.assertIn('не найдено', client.get('/?room=999').get_data(as_text=True))

    def test_admin_can_generate_and_manage_room_codes(self):
        client = app.test_client()
        self.assertEqual(client.get('/admin/qr').status_code, 302)
        client.get('/login')
        with client.session_transaction() as s: csrf = s['csrf_token']
        client.post('/login', data={'login':'admin','password':'admin-password','csrf_token':csrf})
        with client.session_transaction() as s: csrf = s['csrf_token']
        self.assertEqual(client.get('/admin/qr').status_code, 200)
        self.assertEqual(client.get('/admin/qr/1.png').mimetype, 'image/png')
        self.assertEqual(client.get('/admin/qr/999.png').status_code, 404)
        self.assertEqual(client.post('/admin/qr', data={'building':'Корпус','name':'Лаборатория','csrf_token':csrf}).status_code, 302)
        self.assertEqual(client.post('/admin/qr', data={'building':'Корпус','name':'Общая зона','room_id':'1','csrf_token':csrf}).status_code, 302)
        with app.app_context():
            self.assertEqual(db().execute('SELECT name FROM rooms WHERE id=1').fetchone()[0], 'Общая зона')

    def test_admin_can_download_all_rooms_as_zip(self):
        client = app.test_client()
        self.assertEqual(client.get('/admin/qr/all.zip').location, '/login')
        client.get('/login')
        with client.session_transaction() as s: csrf = s['csrf_token']
        client.post('/login', data={'login': 'admin', 'password': 'admin-password', 'csrf_token': csrf})
        with app.app_context():
            db().execute("INSERT INTO rooms VALUES (2, 'Учебный корпус', 'Кабинет 205')")
            db().commit()
        self.assertIn('Скачать все QR-коды', client.get('/admin/qr').get_data(as_text=True))
        with patch('qrcode.make', wraps=qrcode.make) as make:
            response = client.get('/admin/qr/all.zip')
            self.assertEqual({call.args[0] for call in make.call_args_list}, {'http://localhost/?room=1', 'http://localhost/?room=2'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'application/zip')
        self.assertIn('attachment', response.headers['Content-Disposition'])
        with ZipFile(BytesIO(response.data)) as archive:
            self.assertEqual(set(archive.namelist()), {'rooms.txt', 'room-1.png', 'room-2.png'})
            self.assertTrue(archive.read('room-2.png').startswith(b'\x89PNG\r\n\x1a\n'))
            self.assertIn('room-2.png — Учебный корпус — Кабинет 205', archive.read('rooms.txt').decode('utf-8'))

    def test_employee_cannot_download_archive(self):
        with app.app_context():
            db().execute("INSERT INTO employees (login,name,password_hash,role) VALUES ('worker','Исполнитель',?,'employee')", (generate_password_hash('worker-password'),))
            db().commit()
        client = app.test_client()
        client.get('/login')
        with client.session_transaction() as s: csrf = s['csrf_token']
        client.post('/login', data={'login': 'worker', 'password': 'worker-password', 'csrf_token': csrf})
        self.assertEqual(client.get('/admin/qr/all.zip').status_code, 403)

if __name__ == '__main__':
    unittest.main()
