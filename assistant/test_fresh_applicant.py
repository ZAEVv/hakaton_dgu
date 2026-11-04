"""Applicant redesign integration contracts against an isolated Flask app."""
import tempfile
import unittest
import uuid
from pathlib import Path

from main import app, db, init_db
from test_helpers import register_applicant


class FreshApplicantTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = app.config.copy()
        app.config.update(TESTING=True, SECRET_KEY='fresh-test', DATABASE=str(Path(self.tmp.name) / 'test.sqlite'), UPLOAD_DIR=str(Path(self.tmp.name) / 'uploads'))
        init_db()
        with app.app_context():
            db().execute("INSERT INTO rooms VALUES (1, 'Корпус', '101')")
            db().commit()
        self.client = app.test_client()

    def tearDown(self):
        app.config.clear()
        app.config.update(self.old)
        self.tmp.cleanup()

    def test_auth_shell_has_semantic_footer_and_no_legacy_static_css(self):
        html = self.client.get('/account/login').get_data(as_text=True)
        self.assertIn('class="site-footer"', html)
        self.assertNotIn('/static/static.css', html)
        self.assertIn('name="csrf_token"', html)
        self.assertIn('name="record_book"', html)
        self.assertIn('data-theme-choice="dark"', html)

    def test_request_workspace_and_account_flow(self):
        self.client.get('/?room=1')
        register_applicant(self.client)
        html = self.client.get('/').get_data(as_text=True)
        self.assertLess(html.index('id="manual-form"'), html.index('id="ai-heading"'))
        for text in ('Место выбрано по QR-коду', 'value="1" data-building="Корпус" selected', 'name="request_key"', 'name="csrf_token"', 'id="chat-send-ticket"', 'DeepSeek', 'Опасная ситуация?'):
            self.assertIn(text, html)
        with self.client.session_transaction() as sess:
            csrf = sess['csrf_token']
        response = self.client.post('/', data={'csrf_token': csrf, 'request_key': str(uuid.uuid4()), 'description': 'Не работает лампа', 'category': 'Электрика', 'building': 'Корпус', 'room_id': '1'})
        self.assertEqual(response.status_code, 302)
        detail = self.client.get(response.location).get_data(as_text=True)
        self.assertIn('Не работает лампа', detail)
        self.assertIn('name="comment"', detail)
        listing = self.client.get('/account').get_data(as_text=True)
        self.assertIn('class="ticket-list"', listing)
        self.assertIn('Не работает лампа', listing)

    def test_validation_preserves_values_and_opens_manual_form(self):
        register_applicant(self.client)
        with self.client.session_transaction() as sess:
            csrf = sess['csrf_token']
        result = self.client.post('/', data={'csrf_token': csrf, 'request_key': str(uuid.uuid4()), 'description': 'Сломан свет', 'category': 'Электрика', 'building': 'Корпус', 'room_id': '999'})
        self.assertEqual(result.status_code, 400)
        html = result.get_data(as_text=True)
        self.assertIn('<details id="manual-form" open', html)
        self.assertIn('Сломан свет', html)
        self.assertIn('role="alert"', html)
