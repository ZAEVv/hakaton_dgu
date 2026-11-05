import tempfile
import unittest
from pathlib import Path

from bootstrap_rooms import bootstrap_rooms
from main import app, db
from setup_env import create_local_env


class BootstrapRoomsTests(unittest.TestCase):
    def test_local_env_created_once_with_private_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / '.env'
            create_local_env(target, Path(__file__).with_name('.env.example'))
            text = target.read_text(encoding='utf-8')
            self.assertRegex(text, r'SECRET_KEY=\S+')
            self.assertIn('SESSION_COOKIE_SECURE=0', text)
            self.assertIn('DEEPSEEK_API_KEY=\n', text)
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                create_local_env(target, Path(__file__).with_name('.env.example'))
            self.assertEqual(target.read_text(encoding='utf-8'), text)

    def test_bootstrap_is_idempotent_and_creates_no_accounts_or_tickets(self):
        old = app.config.copy()
        with tempfile.TemporaryDirectory() as tmp:
            try:
                app.config.update(TESTING=True, SECRET_KEY='test-secret', DATABASE=str(Path(tmp) / 'test.sqlite3'))
                bootstrap_rooms()
                bootstrap_rooms()
                with app.app_context():
                    rooms = {row['name'] for row in db().execute("SELECT name FROM rooms WHERE building='Учебный корпус'")}
                    expected = {f'Кабинет {n}' for n in (*range(101, 111), *range(201, 217), *range(301, 311))}
                    self.assertEqual(rooms, expected)
                    for table in ('employees', 'applicants', 'tickets', 'attachments'):
                        self.assertEqual(db().execute(f'SELECT count(*) FROM {table}').fetchone()[0], 0)
            finally:
                app.config.clear()
                app.config.update(old)


if __name__ == '__main__':
    unittest.main()
