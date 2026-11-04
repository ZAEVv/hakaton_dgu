import os
import hashlib
import secrets
import sqlite3
import uuid
import re
import click
from io import BytesIO
from pathlib import Path

from flask import Flask, abort, g, redirect, render_template, request, url_for, session, send_file
from functools import wraps
from PIL import Image, UnidentifiedImageError
from dotenv import load_dotenv
from werkzeug.security import check_password_hash, generate_password_hash

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
        g.db.create_function('casefold', 1, lambda value: str(value).casefold())
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
        db().execute('BEGIN IMMEDIATE')
        columns = {row['name'] for row in db().execute('PRAGMA table_info(knowledge_base)')}
        if 'is_verified' not in columns:
            db().execute('ALTER TABLE knowledge_base ADD COLUMN is_verified INTEGER NOT NULL DEFAULT 0 CHECK (is_verified IN (0, 1))')
        ticket_columns = {row['name'] for row in db().execute('PRAGMA table_info(tickets)')}
        if 'version' not in ticket_columns:
            db().execute('ALTER TABLE tickets ADD COLUMN version INTEGER NOT NULL DEFAULT 0')
        if 'applicant_id' not in ticket_columns:
            db().execute('ALTER TABLE tickets ADD COLUMN applicant_id INTEGER REFERENCES applicants(id)')
        history_columns = {row['name'] for row in db().execute('PRAGMA table_info(ticket_history)')}
        if 'applicant_id' not in history_columns:
            db().execute('ALTER TABLE ticket_history ADD COLUMN applicant_id INTEGER REFERENCES applicants(id)')
        db().execute('CREATE INDEX IF NOT EXISTS tickets_applicant_idx ON tickets(applicant_id, created_at)')
        employee_columns = {row['name'] for row in db().execute('PRAGMA table_info(employees)')}
        if 'role' not in employee_columns:
            # Existing staff already had full access; preserve it during migration.
            db().execute("ALTER TABLE employees ADD COLUMN role TEXT NOT NULL DEFAULT 'employee' CHECK (role IN ('admin', 'employee'))")
            db().execute("UPDATE employees SET role='admin'")
        if 'is_active' not in employee_columns:
            db().execute('ALTER TABLE employees ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))')
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


def applicant_required(view):
    @wraps(view)
    def protected(*args, **kwargs):
        if not app.secret_key:
            abort(503, 'SECRET_KEY не настроен')
        if request.method == 'POST':
            db().execute('BEGIN IMMEDIATE')
        auth_token = session.get('applicant_auth_token', '')
        token_hash = hashlib.sha256(auth_token.encode()).hexdigest()
        applicant = db().execute('''SELECT a.id, a.first_name, a.last_name, a.record_book
                                    FROM applicants a JOIN applicant_sessions s ON s.applicant_id=a.id
                                    WHERE a.id=? AND s.token_hash=? AND s.created_at >= datetime('now', '-12 hours')''',
                                 (session.get('applicant_id'), token_hash)).fetchone()
        if not applicant:
            session.pop('applicant_id', None)
            session.pop('applicant_auth_token', None)
            return redirect(url_for('applicant_login'))
        g.applicant = applicant
        return view(*args, **kwargs)
    return protected


@app.route('/', methods=['GET', 'POST'])
@applicant_required
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
        previous = db().execute('''SELECT t.id, t.applicant_id FROM ticket_access a JOIN tickets t ON t.id=a.ticket_id
                                   WHERE a.request_key=?''', (request_key,)).fetchone() if valid_key else None
        if previous:
            if previous['applicant_id'] != g.applicant['id']:
                abort(409, 'Обновите форму и повторите отправку.')
            return redirect(url_for('account_ticket', ticket_id=previous['id']))
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
                    cursor = connection.execute('INSERT INTO tickets (description, category, room_id, applicant_id) VALUES (?, ?, ?, ?)',
                                                (description, category, room_id, g.applicant['id']))
                    connection.execute(
                        'INSERT INTO ticket_history (ticket_id, applicant_id, change_description, is_public) VALUES (?, ?, ?, 1)',
                        (cursor.lastrowid, g.applicant['id'], 'Заявка создана заявителем'),
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
                    return redirect(url_for('account_ticket', ticket_id=cursor.lastrowid))
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


@app.route('/ticket/<token>', methods=['GET', 'POST'])
def ticket(token):
    return render_template('error.html', message='Доступ по секретным ссылкам отключён. Войдите в личный кабинет. Старые заявки доступны только сотрудникам.'), 410


@app.get('/account')
@applicant_required
def account():
    items = db().execute('''SELECT t.*, r.building, r.name AS room FROM tickets t JOIN rooms r ON r.id=t.room_id
                            WHERE t.applicant_id=? ORDER BY t.created_at DESC, t.id DESC''', (g.applicant['id'],)).fetchall()
    return render_template('account.html', items=items, csrf_token=csrf_token())


@app.route('/account/tickets/<int:ticket_id>', methods=['GET', 'POST'])
@applicant_required
def account_ticket(ticket_id):
    if request.method == 'POST':
        check_csrf()
    item = db().execute('''SELECT t.id, t.created_at, t.description, t.category, t.status,
                                   r.building, r.name AS room
                           FROM tickets t JOIN rooms r ON r.id=t.room_id WHERE t.id=? AND t.applicant_id=?''',
                        (ticket_id, g.applicant['id'])).fetchone()
    if not item:
        abort(404)
    error = None
    if request.method == 'POST':
        comment = request.form.get('comment', '').strip()
        if item['status'] in ('Решена', 'Отклонена', 'Закрыта'):
            abort(409, 'Заявка закрыта. Отправка комментариев недоступна.')
        if not comment or len(comment) > 5000:
            error = 'Введите ответ длиной от 1 до 5000 символов.'
        else:
            status = 'В работе' if item['status'] == 'Нужны уточнения' else item['status']
            change = 'Ответ заявителя'
            if status != item['status']:
                change = f"Статус: {item['status']} → {status}; Ответ заявителя"
            db().execute('UPDATE tickets SET status=?, version=version+1 WHERE id=?', (status, item['id']))
            db().execute('INSERT INTO ticket_history (ticket_id,applicant_id,change_description,comment,is_public) VALUES (?,?,?,?,1)',
                         (item['id'], g.applicant['id'], change, comment))
            db().commit()
            return redirect(url_for('account_ticket', ticket_id=item['id']))
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
    attachments = db().execute('SELECT id FROM attachments WHERE ticket_id=?', (item['id'],)).fetchall()
    return render_template('created.html', number=item['id'], item=item, history=history, attachments=attachments,
                           csrf_token=csrf_token(), error=error), 400 if error else 200


def revoke_browser_sessions():
    for key, table in (('auth_token', 'employee_sessions'), ('applicant_auth_token', 'applicant_sessions')):
        token = session.get(key)
        if token:
            db().execute(f'DELETE FROM {table} WHERE token_hash=?', (hashlib.sha256(token.encode()).hexdigest(),))


def start_applicant_session(applicant_id):
    revoke_browser_sessions()
    db().execute("DELETE FROM applicant_sessions WHERE created_at < datetime('now', '-12 hours')")
    token = secrets.token_urlsafe(32)
    db().execute('INSERT INTO applicant_sessions (token_hash,applicant_id) VALUES (?,?)',
                 (hashlib.sha256(token.encode()).hexdigest(), applicant_id))
    db().commit()
    session.clear()
    session['applicant_id'] = applicant_id
    session['applicant_auth_token'] = token
    csrf_token()


def record_book_number(value):
    return value.strip().upper()


@app.route('/account/register', methods=['GET', 'POST'])
def applicant_register():
    token = csrf_token()
    error = None
    if request.method == 'POST':
        check_csrf()
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        record_book = record_book_number(request.form.get('record_book', ''))
        password = request.form.get('password', '')
        if not first_name or len(first_name) > 80 or not last_name or len(last_name) > 80 or not re.fullmatch(r'[A-ZА-ЯЁ0-9/-]{1,40}', record_book):
            error = 'Укажите имя и фамилию (до 80 символов) и номер зачётной книжки (до 40 букв, цифр, / или -).'
        elif not 10 <= len(password) <= 256:
            error = 'Пароль должен содержать от 10 до 256 символов.'
        elif password != request.form.get('password_confirm', ''):
            error = 'Пароли не совпадают.'
        else:
            db().execute('BEGIN IMMEDIATE')
            if db().execute('SELECT 1 FROM applicants WHERE record_book=?', (record_book,)).fetchone():
                error = 'Этот номер зачётной книжки уже зарегистрирован. Войдите в свой аккаунт.'
            else:
                applicant_id = db().execute('INSERT INTO applicants (first_name,last_name,record_book,password_hash) VALUES (?,?,?,?)',
                                            (first_name, last_name, record_book, generate_password_hash(password))).lastrowid
                start_applicant_session(applicant_id)
                return redirect(url_for('account'))
    return render_template('applicant_auth.html', registering=True, csrf_token=token, error=error), 400 if error else 200


@app.route('/account/login', methods=['GET', 'POST'])
def applicant_login():
    token = csrf_token()
    error = None
    if request.method == 'POST':
        check_csrf()
        db().execute('BEGIN IMMEDIATE')
        applicant = db().execute('SELECT * FROM applicants WHERE record_book=?',
                                 (record_book_number(request.form.get('record_book', '')),)).fetchone()
        password = request.form.get('password', '')
        if applicant and len(password) <= 256 and check_password_hash(applicant['password_hash'], password):
            start_applicant_session(applicant['id'])
            return redirect(url_for('account'))
        error = 'Неверный номер зачётной книжки или пароль.'
    return render_template('applicant_auth.html', registering=False, csrf_token=token, error=error), 401 if error else 200


@app.post('/account/logout')
@applicant_required
def applicant_logout():
    check_csrf()
    revoke_browser_sessions()
    db().commit()
    session.clear()
    return redirect(url_for('applicant_login'))


@app.get('/account/attachments/<int:attachment_id>')
@applicant_required
def account_attachment(attachment_id):
    attachment = db().execute('''SELECT a.file_path FROM attachments a JOIN tickets t ON t.id=a.ticket_id
                                 WHERE a.id=? AND t.applicant_id=?''', (attachment_id, g.applicant['id'])).fetchone()
    if not attachment:
        abort(404)
    return attachment_response(attachment['file_path'])


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
        if request.method == 'POST':
            db().execute('BEGIN IMMEDIATE')
        employee_id = session.get('employee_id')
        auth_token = session.get('auth_token', '')
        token_hash = hashlib.sha256(auth_token.encode()).hexdigest()
        valid = db().execute('''SELECT e.* FROM employees e JOIN employee_sessions s ON s.employee_id=e.id
                                 WHERE e.id=? AND e.is_active=1 AND s.token_hash=? AND s.created_at >= datetime('now', '-12 hours')''',
                             (employee_id, token_hash)).fetchone()
        if not valid:
            session.pop('employee_id', None)
            session.pop('auth_token', None)
            return redirect(url_for('login'))
        g.employee = valid
        return view(*args, **kwargs)
    return protected


@app.context_processor
def staff_context():
    return {'current_employee': getattr(g, 'employee', None), 'current_applicant': getattr(g, 'applicant', None)}


def require_admin():
    if g.employee['role'] != 'admin':
        abort(403)


@app.cli.command('create-admin')
@click.option('--login', prompt='Логин')
@click.option('--name', prompt='Имя')
@click.password_option(prompt='Пароль')
def create_admin(login, name, password):
    """Create an administrator without demo data."""
    if not login.strip() or len(login.strip()) > 80 or not name.strip() or len(name.strip()) > 120 or not 10 <= len(password) <= 256:
        raise click.ClickException('Укажите логин, имя и пароль от 10 до 256 символов.')
    init_db()
    db().execute('BEGIN IMMEDIATE')
    if db().execute('SELECT 1 FROM employees WHERE login=?', (login.strip(),)).fetchone():
        raise click.ClickException('Этот логин уже занят.')
    employee_id = db().execute("INSERT INTO employees (login,name,password_hash,role) VALUES (?,?,?,'admin')",
                               (login.strip(), name.strip(), generate_password_hash(password))).lastrowid
    db().execute('INSERT INTO employee_history (employee_id,actor_id,action) VALUES (?,?,?)',
                 (employee_id, employee_id, 'Администратор создан через команду на сервере'))
    db().commit()
    click.echo('Администратор создан.')


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
        clauses.append('''(casefold(t.description) LIKE ? OR CAST(t.id AS TEXT) = ? OR casefold(r.name) LIKE ?
                           OR casefold(a.last_name || ' ' || a.first_name) LIKE ? OR casefold(a.record_book) LIKE ?)''')
        params.extend((f'%{query.casefold()}%', query, f'%{query.casefold()}%', f'%{query.casefold()}%', f'%{query.casefold()}%'))
    sql = '''SELECT t.*, r.building, r.name AS room, e.name AS assignee,
                    a.first_name, a.last_name, a.record_book
             FROM tickets t JOIN rooms r ON r.id=t.room_id LEFT JOIN employees e ON e.id=t.assignee_id
             LEFT JOIN applicants a ON a.id=t.applicant_id'''
    if clauses:
        sql += ' WHERE ' + ' AND '.join(clauses)
    items = db().execute(sql + ' ORDER BY t.created_at DESC, t.id DESC', params).fetchall()
    employees = db().execute('SELECT id, name FROM employees ORDER BY name').fetchall()
    buildings = db().execute('SELECT DISTINCT building FROM rooms ORDER BY building').fetchall()
    rooms = db().execute('SELECT id, building, name FROM rooms ORDER BY building, name').fetchall()
    return render_template('admin.html', items=items, employees=employees, buildings=buildings, rooms=rooms,
                           statuses=STATUSES, categories=CATEGORIES, csrf_token=csrf_token())


@app.get('/admin/applicants/<int:applicant_id>')
@staff_required
def admin_applicant(applicant_id):
    applicant = db().execute('SELECT id,first_name,last_name,record_book,created_at FROM applicants WHERE id=?', (applicant_id,)).fetchone()
    if not applicant:
        abort(404)
    items = db().execute('SELECT id,description,status,created_at FROM tickets WHERE applicant_id=? ORDER BY created_at DESC,id DESC', (applicant_id,)).fetchall()
    return render_template('admin_applicant.html', applicant=applicant, items=items, csrf_token=csrf_token())


@app.route('/admin/tickets/<int:ticket_id>', methods=['GET', 'POST'])
@staff_required
def admin_ticket(ticket_id):
    item = db().execute('''SELECT t.*, r.building, r.name AS room, a.first_name, a.last_name, a.record_book FROM tickets t
                           JOIN rooms r ON r.id=t.room_id LEFT JOIN applicants a ON a.id=t.applicant_id WHERE t.id=?''', (ticket_id,)).fetchone()
    if not item:
        abort(404)
    employees = db().execute('SELECT id, name FROM employees WHERE is_active=1 OR id=? ORDER BY name', (item['assignee_id'],)).fetchall()
    error = None
    if request.method == 'POST':
        check_csrf()
        if g.employee['role'] != 'admin' and item['assignee_id'] != g.employee['id']:
            abort(403)
        version = request.form.get('version', '')
        if not version.isascii() or not version.isdigit() or len(version) > 18:
            abort(400, 'Некорректная версия заявки')
        if int(version) != item['version']:
            abort(409, 'Заявка изменена другим сотрудником. Обновите страницу и повторите изменения.')
        status = request.form.get('status', '')
        assignee = request.form.get('assignee_id', '')
        if g.employee['role'] != 'admin' and assignee != str(item['assignee_id']):
            abort(403)
        comment = request.form.get('comment', '').strip()
        visibility = request.form.get('visibility', '')
        current_status = 'Решена' if item['status'] == 'Закрыта' else item['status']
        if (status not in STATUSES or visibility not in ('public', 'internal') or len(comment) > 5000
            or (assignee and not any(str(e['id']) == assignee for e in employees))
            or (status in ('Решена', 'Отклонена') and status != current_status and (not comment or visibility != 'public'))):
            error = 'Проверьте поля. При решении или отклонении обязателен публичный итоговый комментарий или причина.'
        else:
            assignee_id = int(assignee) if assignee else None
            changes = []
            if status != current_status:
                changes.append(f"Статус: {current_status} → {status}")
            if assignee_id != item['assignee_id']:
                if assignee_id and not db().execute('SELECT 1 FROM employees WHERE id=? AND is_active=1', (assignee_id,)).fetchone():
                    abort(400, 'Сотрудник заблокирован.')
                name = next((e['name'] for e in employees if e['id'] == assignee_id), 'не назначен')
                old_name = next((e['name'] for e in employees if e['id'] == item['assignee_id']), 'не назначен')
                changes.append(f'Исполнитель: {old_name} → {name}')
            if changes or comment:
                updated = db().execute('UPDATE tickets SET status=?, assignee_id=?, version=version+1 WHERE id=? AND version=?', (status, assignee_id, ticket_id, int(version)))
                if updated.rowcount != 1:
                    db().rollback()
                    abort(409, 'Заявка изменена другим сотрудником. Обновите страницу и повторите изменения.')
                db().execute('INSERT INTO ticket_history (ticket_id, employee_id, change_description, comment, is_public) VALUES (?, ?, ?, ?, ?)',
                             (ticket_id, session['employee_id'], '; '.join(changes) or 'Комментарий', comment or None, int(visibility == 'public')))
                db().commit()
            return redirect(url_for('admin_ticket', ticket_id=ticket_id))
    history = db().execute('''SELECT h.*, COALESCE(e.name, a.last_name || ' ' || a.first_name) AS author
                              FROM ticket_history h LEFT JOIN employees e ON e.id=h.employee_id
                              LEFT JOIN applicants a ON a.id=h.applicant_id
                              WHERE h.ticket_id=? ORDER BY h.id DESC''', (ticket_id,)).fetchall()
    attachments = db().execute('SELECT id FROM attachments WHERE ticket_id=?', (ticket_id,)).fetchall()
    return render_template('admin_ticket.html', item=item, employees=employees, statuses=STATUSES, history=history,
                           attachments=attachments, csrf_token=csrf_token(), error=error,
                           can_edit=g.employee['role'] == 'admin' or item['assignee_id'] == g.employee['id']), 400 if error else 200


@app.post('/admin/tickets/<int:ticket_id>/claim')
@staff_required
def claim_ticket(ticket_id):
    check_csrf()
    item = db().execute('SELECT * FROM tickets WHERE id=?', (ticket_id,)).fetchone()
    if not item:
        abort(404)
    if item['assignee_id'] is not None or item['status'] in ('Решена', 'Отклонена', 'Закрыта'):
        abort(409, 'Заявка уже назначена или закрыта.')
    db().execute('UPDATE tickets SET assignee_id=?, version=version+1 WHERE id=?', (g.employee['id'], ticket_id))
    db().execute('INSERT INTO ticket_history (ticket_id,employee_id,change_description) VALUES (?,?,?)',
                 (ticket_id, g.employee['id'], f"Исполнитель: {g.employee['name']} (взял заявку)"))
    db().commit()
    return redirect(url_for('admin_ticket', ticket_id=ticket_id))


@app.route('/admin/employees', methods=['GET', 'POST'])
@staff_required
def manage_employees():
    require_admin()
    error = None
    if request.method == 'POST':
        check_csrf()
        action = request.form.get('action', '')
        if action == 'create':
            name = request.form.get('name', '').strip()
            login_name = request.form.get('login', '').strip()
            password = request.form.get('password', '')
            if not name or len(name) > 120 or not login_name or len(login_name) > 80 or not 10 <= len(password) <= 256:
                error = 'Укажите имя (до 120 символов), логин (до 80) и пароль от 10 до 256 символов.'
            elif db().execute('SELECT 1 FROM employees WHERE login=?', (login_name,)).fetchone():
                error = 'Этот логин уже занят.'
            else:
                employee_id = db().execute("INSERT INTO employees (name,login,password_hash,role) VALUES (?,?,?,'employee')",
                                           (name, login_name, generate_password_hash(password))).lastrowid
                audit_action = 'Создана учётная запись исполнителя'
        else:
            employee_id = request.form.get('employee_id', '')
            employee = db().execute('SELECT * FROM employees WHERE id=?', (employee_id,)).fetchone()
            if not employee:
                abort(404)
            if employee['id'] == g.employee['id'] and action == 'block':
                abort(400, 'Нельзя заблокировать собственную учётную запись.')
            if action in ('block', 'unblock'):
                db().execute('UPDATE employees SET is_active=? WHERE id=?', (int(action == 'unblock'), employee_id))
                audit_action = 'Учётная запись заблокирована' if action == 'block' else 'Учётная запись разблокирована'
                if action == 'block':
                    tickets = db().execute("SELECT id FROM tickets WHERE assignee_id=? AND status NOT IN ('Решена','Отклонена','Закрыта')", (employee_id,)).fetchall()
                    for item in tickets:
                        db().execute('UPDATE tickets SET assignee_id=NULL, version=version+1 WHERE id=?', (item['id'],))
                        db().execute('INSERT INTO ticket_history (ticket_id,employee_id,change_description) VALUES (?,?,?)',
                                     (item['id'], g.employee['id'], f"Исполнитель: {employee['name']} → не назначен (блокировка сотрудника)"))
            elif action == 'reset_password':
                password = request.form.get('password', '')
                if not 10 <= len(password) <= 256:
                    error = 'Пароль должен содержать от 10 до 256 символов.'
                else:
                    db().execute('UPDATE employees SET password_hash=? WHERE id=?', (generate_password_hash(password), employee_id))
                    audit_action = 'Пароль сброшен'
            else:
                abort(400)
            if not error and action in ('block', 'reset_password'):
                db().execute('DELETE FROM employee_sessions WHERE employee_id=?', (employee_id,))
        if not error:
            db().execute('INSERT INTO employee_history (employee_id,actor_id,action) VALUES (?,?,?)',
                         (employee_id, g.employee['id'], audit_action))
            db().commit()
            return redirect(url_for('manage_employees'))
    employees = db().execute('SELECT id,name,login,role,is_active FROM employees ORDER BY name').fetchall()
    history = db().execute('''SELECT h.*, e.name AS employee_name, a.name AS actor_name FROM employee_history h
                              JOIN employees e ON e.id=h.employee_id JOIN employees a ON a.id=h.actor_id ORDER BY h.id DESC''').fetchall()
    return render_template('employees.html', employees=employees, history=history, error=error,
                           csrf_token=csrf_token()), 400 if error else 200


@app.get('/admin/attachments/<int:attachment_id>')
@staff_required
def admin_attachment(attachment_id):
    attachment = db().execute('SELECT file_path FROM attachments WHERE id=?', (attachment_id,)).fetchone()
    if not attachment:
        abort(404)
    return attachment_response(attachment['file_path'])


def attachment_response(file_path):
    path = Path(file_path).resolve()
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
        db().execute('BEGIN IMMEDIATE')
        employee = db().execute('SELECT * FROM employees WHERE login = ?', (request.form.get('login', ''),)).fetchone()
        if employee and employee['is_active'] and check_password_hash(employee['password_hash'], request.form.get('password', '')):
            revoke_browser_sessions()
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
