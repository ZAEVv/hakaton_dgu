import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from main import app, db, init_db
from test_helpers import register_applicant


class AssistantApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old = app.config.copy()
        app.config.update(TESTING=True, SECRET_KEY='test-only-secret', DATABASE=str(Path(self.temp.name) / 'db.sqlite'), UPLOAD_DIR=str(Path(self.temp.name) / 'uploads'))
        init_db()
        self.client = app.test_client()
        register_applicant(self.client)
        with self.client.session_transaction() as session:
            self.csrf = session['csrf_token']

    def tearDown(self):
        app.config.clear()
        app.config.update(self.old)
        self.temp.cleanup()

    def send(self, message, token=None):
        return self.client.post('/api/assistant', json={'message': message}, headers={'X-CSRF-Token': token or self.csrf})

    def test_csrf_and_danger_without_external_call(self):
        self.assertEqual(self.send('искры из розетки', 'bad').status_code, 400)
        with patch('main.assist', wraps=__import__('ai_helper').assist) as helper:
            response = self.send('из розетки идут искры')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json['type'], 'danger')
            self.assertIn('не трогайте', response.json['answer'])
            helper.assert_called_once()

    def test_service_error_and_rate_limit_do_not_break_form(self):
        with patch.dict('os.environ', {'DEEPSEEK_API_KEY': ''}):
            for _ in range(10):
                self.assertEqual(self.send('не работает свет').status_code, 503)
            self.assertEqual(self.send('не работает свет').status_code, 429)
            self.assertEqual(self.send('из розетки идут искры').json['type'], 'danger')
            self.assertEqual(self.client.get('/').status_code, 200)

    def test_fault_result_can_be_returned_without_creating_ticket(self):
        with patch('main.assist', return_value={'type': 'fault', 'category': 'Электрика', 'draft': 'Не работает свет', 'answer': 'Проверьте заявку', 'question': None, 'source': None}):
            response = self.send('Не работает свет')
        self.assertEqual(response.json['category'], 'Электрика')
        with app.app_context():
            self.assertEqual(db().execute('SELECT COUNT(*) FROM tickets').fetchone()[0], 0)
