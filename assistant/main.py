import os
import secrets
import sqlite3
import uuid
from io import BytesIO
from pathlib import Path

from flask import Flask, abort, g, redirect, render_template, request, url_for
from PIL import Image, UnidentifiedImageError
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent
load_dotenv(BASE / '.env')


def configured_path(name, default):
    path = Path(os.environ.get(name) or default).expanduser()
    return str(path if path.is_absolute() else BASE / path)


app = Flask(__name__, template_folder='tameplates', static_folder='static')
app.config.update(
    DATABASE=configured_path('DATABASE', 'helpdesk.sqlite3'),
    UPLOAD_DIR=configured_path('UPLOAD_DIR', 'uploads'),
    API_KEY=os.environ.get('API_KEY', ''),
    TRUSTED_HOSTS=[host.strip() for host in (os.environ.get('TRUSTED_HOSTS') or 'localhost,127.0.0.1,[::1]').split(',') if host.strip()],
    MAX_CONTENT_LENGTH=5 * 1024 * 1024,
)
CATEGORIES = ('Электрика', 'Сантехника', 'Мебель', 'Оборудование', 'Другое')


def db():
    if 'db' not in g:
        g.db = sqlite3.connect(app.config['DATABASE'], timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys = ON')
    return g.db


@app.teardown_appcontext
def close_db(error):
    connection = g.pop('db', None)
    if connection is not None:
        connection.close()


def init_db():
    with app.app_context():
        Path(app.config['DATABASE']).parent.mkdir(parents=True, exist_ok=True)
        db().executescript((BASE / 'schema.sql').read_text(encoding='utf-8'))
        columns = {row['name'] for row in db().execute('PRAGMA table_info(knowledge_base)')}
        if 'is_verified' not in columns:
            db().execute('ALTER TABLE knowledge_base ADD COLUMN is_verified INTEGER NOT NULL DEFAULT 0 CHECK (is_verified IN (0, 1))')
        db().commit()


@app.errorhandler(413)
def too_large(error):
    return render_template('error.html', message='Запрос слишком большой. Выберите фото до 4 МБ и отправьте форму заново.'), 413


@app.errorhandler(sqlite3.Error)
def database_error(error):
    app.logger.exception('База данных недоступна')
    return render_template('error.html', message='База данных временно недоступна. Не удалось подтвердить сохранение заявки. Повторите отправку позже.'), 503


@app.after_request
def private_response(response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response


@app.route('/', methods=['GET', 'POST'])
def index():
    rooms = db().execute('SELECT id, building, name FROM rooms ORDER BY building, name').fetchall()
    error = None
    status_code = 200
    values = request.form if request.method == 'POST' else {}
    request_key = values.get('request_key', '')
    if request.method == 'POST':
        description = values.get('description', '').strip()
        category = values.get('category', '')
        room_id = values.get('room_id', '')
        building = values.get('building', '')
        try:
            parsed_key = uuid.UUID(request_key)
            valid_key = str(parsed_key) == request_key and parsed_key.version == 4
        except (ValueError, AttributeError):
            valid_key = False
        previous = db().execute('SELECT token FROM ticket_access WHERE request_key = ?', (request_key,)).fetchone() if valid_key else None
        if previous:
            return redirect(url_for('ticket', token=previous['token']))
        if not valid_key or not description or len(description) > 5000 or category not in CATEGORIES or not any(str(r['id']) == room_id and r['building'] == building for r in rooms):
            error = 'Проверьте обязательные поля. Описание должно содержать не более 5000 символов.'
            status_code = 400
            if not valid_key:
                request_key = str(uuid.uuid4())
        else:
            photo = request.files.get('photo')
            photo_bytes = None
            ext = None
            if photo and photo.filename:
                try:
                    photo_bytes = photo.read(4 * 1024 * 1024 + 1)
                    if len(photo_bytes) > 4 * 1024 * 1024:
                        raise ValueError('large')
                    with Image.open(BytesIO(photo_bytes)) as picture:
                        image_format = picture.format
                        if picture.width * picture.height > 20_000_000:
                            raise ValueError('dimensions')
                        picture.verify()
                    with Image.open(BytesIO(photo_bytes)) as picture:
                        picture.load()
                    ext = {'JPEG': '.jpg', 'PNG': '.png', 'WEBP': '.webp'}.get(image_format)
                    if not ext:
                        raise ValueError('format')
                except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
                    error = 'Фото должно быть исправным изображением JPEG, PNG или WebP: до 4 МБ и не более 20 мегапикселей.'
                    status_code = 400
            if not error:
                saved_path = None
                created_file = False
                try:
                    connection = db()
                    connection.execute('BEGIN IMMEDIATE')
                    existing = connection.execute('SELECT token FROM ticket_access WHERE request_key = ?', (request_key,)).fetchone()
                    if existing:
                        connection.rollback()
                        return redirect(url_for('ticket', token=existing['token']))
                    cursor = connection.execute('INSERT INTO tickets (description, category, room_id) VALUES (?, ?, ?)', (description, category, room_id))
                    connection.execute(
                        'INSERT INTO ticket_history (ticket_id, change_description, is_public) VALUES (?, ?, 1)',
                        (cursor.lastrowid, 'Заявка создана заявителем'),
                    )
                    token = secrets.token_urlsafe(32)
                    connection.execute('INSERT INTO ticket_access (ticket_id, token, request_key) VALUES (?, ?, ?)', (cursor.lastrowid, token, request_key))
                    if photo_bytes is not None:
                        folder = Path(app.config['UPLOAD_DIR'])
                        folder.mkdir(parents=True, exist_ok=True)
                        saved_path = folder / (secrets.token_hex(24) + ext)
                        with saved_path.open('xb') as file:
                            created_file = True
                            file.write(photo_bytes)
                        connection.execute('INSERT INTO attachments (ticket_id, file_path) VALUES (?, ?)', (cursor.lastrowid, str(saved_path)))
                    connection.commit()
                    return redirect(url_for('ticket', token=token))
                except (sqlite3.Error, OSError):
                    db().rollback()
                    if created_file:
                        try:
                            saved_path.unlink(missing_ok=True)
                        except OSError:
                            app.logger.exception('Не удалось удалить несохранённое вложение')
                    app.logger.exception('Не удалось сохранить заявку')
                    error = 'Не удалось сохранить заявку. Попробуйте ещё раз.'
                    status_code = 503
    buildings = sorted({room['building'] for room in rooms})
    return render_template('index.html', rooms=rooms, buildings=buildings, categories=CATEGORIES, values=values, request_key=request_key if request_key else str(uuid.uuid4()), error=error), status_code


@app.get('/ticket/<token>')
def ticket(token):
    item = db().execute('SELECT tickets.id FROM tickets JOIN ticket_access ON tickets.id = ticket_access.ticket_id WHERE ticket_access.token = ?', (token,)).fetchone()
    if not item:
        abort(404)
    return render_template('created.html', number=item['id'])


if __name__ == '__main__':
    init_db()
    app.run()
