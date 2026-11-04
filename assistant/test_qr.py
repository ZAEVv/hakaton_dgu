import tempfile
import unittest
from pathlib import Path
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
        self.assertEqual(client.get('/?room=1').location, '/account/login')
        register_applicant(client)
        response = client.get('/')
        self.assertIn('Место выбрано по QR-коду', response.get_data(as_text=True))
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

if __name__ == '__main__':
    unittest.main()
