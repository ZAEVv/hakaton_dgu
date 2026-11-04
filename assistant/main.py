import os
import hashlib
import secrets
import sqlite3
import uuid
from io import BytesIO
from pathlib import Path

from flask import Flask, abort, g, redirect, render_template, request, url_for, session, send_file
from functools import wraps
from PIL import Image, UnidentifiedImageError
from dotenv import load_dotenv
from werkzeug.security import check_password_hash

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
    SECRET_KEY=os.environ.get('SECRET_KEY') or None,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=os.environ.get('SESSION_COOKIE_SECURE', '1') == '1',
    TRUSTED_HOSTS=[host.strip() for host in (os.environ.get('TRUSTED_HOSTS') or 'localhost,127.0.0.1,[::1]').split(',') if host.strip()],
    MAX_CONTENT_LENGTH=5 * 1024 * 1024,
)
CATEGORIES = ('Электрика', 'Сантехника', 'Мебель', 'Оборудование', 'Другое')
STATUSES = ('Новая', 'На рассмотрении', 'Назначен исполнитель', 'В работе', 'Нужны уточнения', 'Решена', 'Отклонена')


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
        ticket_columns = {row['name'] for row in db().execute('PRAGMA table_info(tickets)')}
        if 'version' not in ticket_columns:
            db().execute('ALTER TABLE tickets ADD COLUMN version INTEGER NOT NULL DEFAULT 0')
        db().execute("UPDATE tickets SET status='Решена', version=version+1 WHERE status='Закрыта'")
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
    if request.method == 'POST':
        check_csrf()
    token = csrf_token()
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
    return render_template('index.html', rooms=rooms, buildings=buildings, categories=CATEGORIES, values=values, request_key=request_key if request_key else str(uuid.uuid4()), error=error, csrf_token=token), status_code


@app.get('/ticket/<token>')
def ticket(token):
    item = db().execute('''SELECT t.id, t.created_at, t.description, t.category, t.status,
                                  r.building, r.name AS room
                           FROM tickets t JOIN ticket_access a ON a.ticket_id=t.id
                           JOIN rooms r ON r.id=t.room_id WHERE a.token=?''', (token,)).fetchone()
    if not item:
        abort(404)
    rows = db().execute('''SELECT created_at, change_description, comment, is_public
                           FROM ticket_history WHERE ticket_id=? ORDER BY id''', (item['id'],)).fetchall()
    history = []
    valid_statuses = (*STATUSES, 'Закрыта')
    for row in rows:
        if row['is_public']:
            history.append(dict(date=row['created_at'], change=row['change_description'], comment=row['comment']))
        else:
            # Internal entries can combine a status change with private details.
            # Only reconstruct recognised status transitions; never expose the entry itself.
            transition = row['change_description'].split(';', 1)[0]
            for old in valid_statuses:
                for new in valid_statuses:
                    if transition == f'Статус: {old} → {new}':
                        history.append(dict(date=row['created_at'], change=transition, comment=None))
    return render_template('created.html', number=item['id'], item=item, history=history)


def csrf_token():
    if not app.secret_key:
        abort(503, 'SECRET_KEY не настроен')
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_urlsafe(32)
    return session['csrf_token']


def check_csrf():
    if not app.secret_key:
        abort(503, 'SECRET_KEY не настроен')
    expected = session.get('csrf_token', '')
    supplied = request.form.get('csrf_token', '')
    if not expected or not secrets.compare_digest(expected.encode('utf-8'), supplied.encode('utf-8')):
        abort(400)


def staff_required(view):
    @wraps(view)
    def protected(*args, **kwargs):
        if not app.secret_key:
            abort(503, 'SECRET_KEY не настроен')
        employee_id = session.get('employee_id')
        auth_token = session.get('auth_token', '')
        token_hash = hashlib.sha256(auth_token.encode()).hexdigest()
        valid = db().execute('''SELECT e.id FROM employees e JOIN employee_sessions s ON s.employee_id=e.id
                                WHERE e.id=? AND s.token_hash=? AND s.created_at >= datetime('now', '-12 hours')''',
                             (employee_id, token_hash)).fetchone()
        if not valid:
            session.clear()
            return redirect(url_for('login'))
        return view(*args, **kwargs)
    return protected


@app.get('/admin')
@staff_required
def admin():
    clauses, params = [], []
    for field, column in (('status', 't.status'), ('category', 't.category'), ('building', 'r.building'), ('assignee', 't.assignee_id'), ('room_id', 't.room_id')):
        value = request.args.get(field, '').strip()
        if value:
            if field == 'status' and value == 'Решена':
                clauses.append("t.status IN ('Решена', 'Закрыта')")
            else:
                clauses.append(f'{column} = ?')
                params.append(value)
    for field, operator in (('date_from', '>='), ('date_to', '<=')):
        value = request.args.get(field, '').strip()
        if value:
            clauses.append(f'date(t.created_at) {operator} ?')
            params.append(value)
    query = request.args.get('q', '').strip()
    if query:
        clauses.append('(t.description LIKE ? OR CAST(t.id AS TEXT) = ? OR r.name LIKE ?)')
        params.extend((f'%{query}%', query, f'%{query}%'))
    sql = '''SELECT t.*, r.building, r.name AS room, e.name AS assignee
             FROM tickets t JOIN rooms r ON r.id=t.room_id LEFT JOIN employees e ON e.id=t.assignee_id'''
    if clauses:
        sql += ' WHERE ' + ' AND '.join(clauses)
    items = db().execute(sql + ' ORDER BY t.created_at DESC, t.id DESC', params).fetchall()
    employees = db().execute('SELECT id, name FROM employees ORDER BY name').fetchall()
    buildings = db().execute('SELECT DISTINCT building FROM rooms ORDER BY building').fetchall()
    rooms = db().execute('SELECT id, building, name FROM rooms ORDER BY building, name').fetchall()
    return render_template('admin.html', items=items, employees=employees, buildings=buildings, rooms=rooms,
                           statuses=STATUSES, categories=CATEGORIES, csrf_token=csrf_token())


@app.route('/admin/tickets/<int:ticket_id>', methods=['GET', 'POST'])
@staff_required
def admin_ticket(ticket_id):
    item = db().execute('''SELECT t.*, r.building, r.name AS room FROM tickets t
                           JOIN rooms r ON r.id=t.room_id WHERE t.id=?''', (ticket_id,)).fetchone()
    if not item:
        abort(404)
    employees = db().execute('SELECT id, name FROM employees ORDER BY name').fetchall()
    error = None
    if request.method == 'POST':
        check_csrf()
        version = request.form.get('version', '')
        if not version.isascii() or not version.isdigit() or len(version) > 18:
            abort(400, 'Некорректная версия заявки')
        if int(version) != item['version']:
            abort(409, 'Заявка изменена другим сотрудником. Обновите страницу и повторите изменения.')
        status = request.form.get('status', '')
        assignee = request.form.get('assignee_id', '')
        comment = request.form.get('comment', '').strip()
        visibility = request.form.get('visibility', '')
        current_status = 'Решена' if item['status'] == 'Закрыта' else item['status']
        if (status not in STATUSES or visibility not in ('public', 'internal') or len(comment) > 5000
            or (assignee and not any(str(e['id']) == assignee for e in employees))
            or (status in ('Решена', 'Отклонена') and status != current_status and not comment)):
            error = 'Проверьте поля. При решении или отклонении обязателен итоговый комментарий.'
        else:
            assignee_id = int(assignee) if assignee else None
            changes = []
            if status != current_status:
                changes.append(f"Статус: {current_status} → {status}")
            if assignee_id != item['assignee_id']:
                name = next((e['name'] for e in employees if e['id'] == assignee_id), 'не назначен')
                changes.append(f'Исполнитель: {name}')
            if changes or comment:
                updated = db().execute('UPDATE tickets SET status=?, assignee_id=?, version=version+1 WHERE id=? AND version=?', (status, assignee_id, ticket_id, int(version)))
                if updated.rowcount != 1:
                    db().rollback()
                    abort(409, 'Заявка изменена другим сотрудником. Обновите страницу и повторите изменения.')
                db().execute('INSERT INTO ticket_history (ticket_id, employee_id, change_description, comment, is_public) VALUES (?, ?, ?, ?, ?)',
                             (ticket_id, session['employee_id'], '; '.join(changes) or 'Комментарий', comment or None, int(visibility == 'public')))
                db().commit()
            return redirect(url_for('admin_ticket', ticket_id=ticket_id))
    history = db().execute('''SELECT h.*, e.name AS author FROM ticket_history h LEFT JOIN employees e ON e.id=h.employee_id
                              WHERE h.ticket_id=? ORDER BY h.id DESC''', (ticket_id,)).fetchall()
    attachments = db().execute('SELECT id FROM attachments WHERE ticket_id=?', (ticket_id,)).fetchall()
    return render_template('admin_ticket.html', item=item, employees=employees, statuses=STATUSES, history=history,
                           attachments=attachments, csrf_token=csrf_token(), error=error), 400 if error else 200


@app.get('/admin/attachments/<int:attachment_id>')
@staff_required
def admin_attachment(attachment_id):
    attachment = db().execute('SELECT file_path FROM attachments WHERE id=?', (attachment_id,)).fetchone()
    if not attachment:
        abort(404)
    path = Path(attachment['file_path']).resolve()
    if not path.is_relative_to(Path(app.config['UPLOAD_DIR']).resolve()) or not path.is_file():
        abort(404)
    response = send_file(path, as_attachment=True, download_name=path.name)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@app.route('/login', methods=['GET', 'POST'])
def login():
    token = csrf_token()
    error = None
    if request.method == 'POST':
        check_csrf()
        employee = db().execute('SELECT * FROM employees WHERE login = ?', (request.form.get('login', ''),)).fetchone()
        if employee and check_password_hash(employee['password_hash'], request.form.get('password', '')):
            old_token = session.get('auth_token')
            if old_token:
                db().execute('DELETE FROM employee_sessions WHERE token_hash=?', (hashlib.sha256(old_token.encode()).hexdigest(),))
            db().execute("DELETE FROM employee_sessions WHERE created_at < datetime('now', '-12 hours')")
            auth_token = secrets.token_urlsafe(32)
            db().execute('INSERT INTO employee_sessions (token_hash, employee_id) VALUES (?, ?)',
                         (hashlib.sha256(auth_token.encode()).hexdigest(), employee['id']))
            db().commit()
            session.clear()
            session['employee_id'] = employee['id']
            session['auth_token'] = auth_token
            csrf_token()
            return redirect(url_for('admin'))
        error = 'Неверный логин или пароль'
    return render_template('login.html', csrf_token=token, error=error), 401 if error else 200


@app.post('/logout')
@staff_required
def logout():
    check_csrf()
    db().execute('DELETE FROM employee_sessions WHERE token_hash=?',
                 (hashlib.sha256(session['auth_token'].encode()).hexdigest(),))
    db().commit()
    session.clear()
    return redirect(url_for('login'))


if __name__ == '__main__':
    init_db()
    app.run()
