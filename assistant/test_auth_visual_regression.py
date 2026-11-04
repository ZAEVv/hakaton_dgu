import unittest
from pathlib import Path


class AuthVisualRegression(unittest.TestCase):
    def test_auth_paragraph_rule_does_not_override_error_color(self):
        css = (Path(__file__).parent / 'static' / 'redesign.css').read_text()
        self.assertIn('.auth-page .auth-form > p.error { color:var(--danger-ink); }', css)

    def test_primary_palette_is_blue_not_green(self):
        css = (Path(__file__).parent / 'static' / 'redesign.css').read_text()
        self.assertIn('--canvas:#e8edf4', css)
        self.assertNotIn('#155b4d', css)
