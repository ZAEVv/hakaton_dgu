"""Structural hooks for the functional page layouts."""
import unittest
from pathlib import Path

TEMPLATES = Path(__file__).parent / 'tameplates'

class FunctionalMarkupTests(unittest.TestCase):
    def test_each_functional_page_has_a_layout_hook(self):
        pages = ('account', 'index', 'created', 'error', 'admin', 'admin_ticket',
                 'admin_applicant', 'categories', 'employees', 'qr_codes')
        for page in pages:
            with self.subTest(page=page):
                self.assertIn(f'class="layout-{page.replace("_", "-")}"',
                              (TEMPLATES / f'{page}.html').read_text())

    def test_base_templates_expose_content_frame(self):
        for page in ('applicant_base', 'staff_base'):
            with self.subTest(page=page):
                self.assertIn('class="site-content"', (TEMPLATES / f'{page}.html').read_text())
