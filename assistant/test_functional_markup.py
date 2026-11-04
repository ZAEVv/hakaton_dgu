"""Structural hooks for the functional page layouts."""
import unittest
from html.parser import HTMLParser
from pathlib import Path

TEMPLATES = Path(__file__).parent / 'tameplates'

class ClassCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.classes = []

    def handle_starttag(self, tag, attrs):
        self.classes.append(set(dict(attrs).get('class', '').split()))


def has_class(source, token):
    parser = ClassCollector()
    parser.feed(source)
    return any(token in classes for classes in parser.classes)


class FunctionalMarkupTests(unittest.TestCase):
    def test_class_tokens_are_matched_individually(self):
        self.assertTrue(has_class('<div class="extra layout-account other">', 'layout-account'))
        self.assertFalse(has_class('<div class="layout-accounting">', 'layout-account'))

    def test_ticket_list_has_status_first_and_detail_has_conversation(self):
        account = (TEMPLATES / 'account.html').read_text()
        detail = (TEMPLATES / 'created.html').read_text()
        self.assertIn('class="ticket-row-status"', account)
        self.assertIn('class="ticket-conversation"', detail)

    def test_each_functional_page_has_a_layout_hook(self):
        pages = ('account', 'index', 'created', 'error', 'admin', 'admin_ticket',
                 'admin_applicant', 'categories', 'employees', 'qr_codes')
        for page in pages:
            with self.subTest(page=page):
                self.assertTrue(has_class((TEMPLATES / f'{page}.html').read_text(),
                                          f'layout-{page.replace("_", "-")}'))

    def test_base_templates_expose_content_frame(self):
        for page in ('applicant_base', 'staff_base'):
            with self.subTest(page=page):
                self.assertTrue(has_class((TEMPLATES / f'{page}.html').read_text(), 'site-content'))
