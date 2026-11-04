import io
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import main
from main import app, db, init_db
from test_helpers import register_applicant
from werkzeug.security import generate_password_hash


class SecurityRegressions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old = app.config.copy()
        app.config.update(TESTING=True, SECRET_KEY='test-secret', DATABASE=str(Path(self.temp.name) / 'db.sqlite'), UPLOAD_DIR=str(Path(self.temp.name) / 'uploads'))
        init_db()

    def tearDown(self):
        app.config.clear()
        app.config.update(self.old)
        self.temp.cleanup()

    def test_slow_post_does_not_lock_database_and_revocation_wins(self):
        for role in ('applicant', 'staff'):
            with self.subTest(role=role):
                client = app.test_client()
                if role == 'applicant':
                    register_applicant(client, record_book='SLOW')
                    path, table = '/account/logout', 'applicant_sessions'
                else:
                    with app.app_context():
                        db().execute("INSERT INTO employees (login,name,password_hash,role) VALUES ('slow','Slow',?,'employee')", (generate_password_hash('password'),))
                        db().commit()
                    client.get('/login')
                    with client.session_transaction() as sess:
                        token = sess['csrf_token']
                    self.assertEqual(client.post('/login', data={'login': 'slow', 'password': 'password', 'csrf_token': token}).status_code, 302)
                    path, table = '/logout', 'employee_sessions'
                with client.session_transaction() as sess:
                    body = ('csrf_token=' + sess['csrf_token']).encode()
                entered, release = threading.Event(), threading.Event()

                class SlowInput(io.BytesIO):
                    def readinto(self, b):
                        entered.set()
                        if not release.wait(5):
                            raise RuntimeError('body not released')
                        return super().readinto(b)

                result = []
                def post():
                    try:
                        result.append(client.open(path, method='POST', input_stream=SlowInput(body), content_length=len(body), content_type='application/x-www-form-urlencoded'))
                    except Exception as exc:
                        result.append(exc)
                thread = threading.Thread(target=post)
                thread.start()
                try:
                    self.assertTrue(entered.wait(3))
                    with closing(sqlite3.connect(app.config['DATABASE'], timeout=0.2)) as connection:
                        with connection:
                            connection.execute('BEGIN IMMEDIATE')
                            connection.execute('DELETE FROM ' + table)
                finally:
                    release.set()
                    thread.join(6)
                self.assertFalse(thread.is_alive())
                self.assertEqual(result[0].status_code, 302)
                self.assertEqual(result[0].location, '/account/login' if role == 'applicant' else '/login')

    def test_protected_post_rejects_oversized_body(self):
        client = app.test_client()
        register_applicant(client)
        app.config['MAX_CONTENT_LENGTH'] = 64
        self.assertEqual(client.post('/account/logout', data=b'x' * 65,
                                     content_type='application/octet-stream').status_code, 413)
        self.assertEqual(client.get('/account').status_code, 200)

    def test_hash_verification_runs_once_for_existing_missing_and_inactive(self):
        password_hash = generate_password_hash('correct-password')
        with app.app_context():
            db().execute("INSERT INTO applicants (first_name,last_name,record_book,password_hash) VALUES ('A','B','EXISTS',?)", (password_hash,))
            db().execute("INSERT INTO employees (login,name,password_hash,role,is_active) VALUES ('active','A',?,'employee',1)", (password_hash,))
            db().execute("INSERT INTO employees (login,name,password_hash,role,is_active) VALUES ('inactive','I',?,'employee',0)", (password_hash,))
            db().commit()
        cases = [('/account/login', 'record_book', 'EXISTS', 'wrong', 401),
                 ('/account/login', 'record_book', 'MISSING', 'wrong', 401),
                 ('/login', 'login', 'active', 'wrong', 401),
                 ('/login', 'login', 'missing', 'wrong', 401),
                 ('/login', 'login', 'inactive', 'correct-password', 401),
                 ('/account/login', 'record_book', 'EXISTS', 'correct-password', 302),
                 ('/login', 'login', 'active', 'correct-password', 302)]
        for path, field, name, password, status in cases:
            with self.subTest(name=name, path=path, status=status):
                client = app.test_client()
                client.get(path)
                with client.session_transaction() as sess:
                    token = sess['csrf_token']
                with patch.object(main, 'check_password_hash', wraps=main.check_password_hash) as verify:
                    response = client.post(path, data={field: name, 'password': password, 'csrf_token': token})
                self.assertEqual(response.status_code, status)
                self.assertEqual(verify.call_count, 1)
                self.assertEqual(verify.call_args.args[1], password)
                if name in ('missing', 'MISSING', 'inactive'):
                    self.assertNotEqual(verify.call_args.args[0], password_hash)


if __name__ == '__main__':
    unittest.main()
