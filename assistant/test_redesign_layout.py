"""Layout contracts for the applicant workspace and staff queue."""
import unittest
from pathlib import Path

TEMPLATES = Path(__file__).parent / 'tameplates'

class RedesignLayoutTests(unittest.TestCase):
    def test_applicant_has_parallel_manual_and_assisted_paths(self):
        page = (TEMPLATES / 'index.html').read_text()
        self.assertIn('class="request-workspace"', page)
        self.assertIn('<details id="manual-form"', page)
        self.assertIn("include 'ai_assistant.html'", page)
        self.assertIn('name="csrf_token"', page)
        self.assertIn('name="request_key"', page)

    def test_chat_precedes_manual_fallback_in_workspace(self):
        page = (TEMPLATES / 'index.html').read_text()
        self.assertLess(page.index("include 'ai_assistant.html'"), page.index('<details id="manual-form"'))

    def test_staff_exposes_queue_and_breakdowns(self):
        page = (TEMPLATES / 'admin.html').read_text()
        self.assertIn('class="staff-queue"', page)
        self.assertIn('class="statistics-distributions"', page)
