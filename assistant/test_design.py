"""Compatibility checks for the shared applicant/staff visual layer."""
import unittest

from main import app


class SharedDesignTests(unittest.TestCase):
    def test_both_login_pages_load_local_shared_design_and_theme(self):
        old_config = app.config.copy()
        app.config.update(TESTING=True, SECRET_KEY='design-test-only')
        try:
            with app.test_client() as client:
                for path in ('/account/login', '/account/register', '/login'):
                    with self.subTest(path=path):
                        page = client.get(path)
                        self.assertEqual(page.status_code, 200)
                        self.assertIn(b'/static/design.css', page.data)
                        self.assertIn(b'/static/swiss.css', page.data)
                        self.assertIn(b'/static/theme.js', page.data)
                        self.assertIn(b'data-theme-choice="light"', page.data)
                        self.assertIn(b'data-theme-choice="dark"', page.data)
                stylesheet = client.get('/static/swiss.css')
                self.assertEqual(stylesheet.status_code, 200)
                self.assertNotIn(b'@import', stylesheet.data)
                self.assertNotIn(b'url(https:', stylesheet.data)
                self.assertNotIn(b'url(http:', stylesheet.data)
                stylesheet.close()
        finally:
            app.config.clear()
            app.config.update(old_config)
