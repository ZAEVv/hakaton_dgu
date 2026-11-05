"""Initialize the configured database and add only the example rooms.

Back up an existing database and its photos before running this script.
"""
from pathlib import Path

from main import app, db, init_db


def bootstrap_rooms():
    init_db()
    with app.app_context():
        sql = Path(__file__).with_name('rooms.example.sql').read_text(encoding='utf-8')
        db().executescript(sql)
        db().commit()


if __name__ == '__main__':
    bootstrap_rooms()
    print('База и пример помещений подготовлены. Аккаунты и заявки не создавались.')
