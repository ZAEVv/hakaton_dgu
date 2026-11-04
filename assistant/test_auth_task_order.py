"""The primary authentication task precedes supplementary context."""
import unittest
from pathlib import Path

TEMPLATES = Path(__file__).parent / 'tameplates'

class AuthTaskOrderTests(unittest.TestCase):
    def test_forms_precede_supplementary_panel(self):
        for name in ('applicant_auth.html', 'login.html'):
            with self.subTest(template=name):
                page = (TEMPLATES / name).read_text()
                self.assertLess(page.index('class="auth-form"'), page.index("include 'campus_panel.html'"))
