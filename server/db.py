import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
from datetime import datetime, timezone
from argon2 import PasswordHasher

SEED = json.loads(Path(__file__).with_name('seed.json').read_text())
PASSWORDS = PasswordHasher()
def now(): return datetime.now(timezone.utc).isoformat()
def digest(value): return hashlib.sha256(value.encode()).hexdigest()
def connect(path):
    db = sqlite3.connect(path, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.create_function('CASEFOLD',1,lambda value: str(value or '').casefold())
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA journal_mode=WAL')
    return db

def initialize(path):
    if path != ':memory:': Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = connect(path)
    db.executescript('''
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,name TEXT NOT NULL,login TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,role TEXT NOT NULL CHECK(role IN ('admin','staff')),active INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),expires_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS categories(id INTEGER PRIMARY KEY,name TEXT UNIQUE NOT NULL);
    CREATE TABLE IF NOT EXISTS locations(id INTEGER PRIMARY KEY,building TEXT NOT NULL,floor INTEGER NOT NULL,room TEXT NOT NULL,zone_name TEXT NOT NULL DEFAULT '',qr_key TEXT UNIQUE NOT NULL,active INTEGER NOT NULL DEFAULT 1,UNIQUE(building,room));
    CREATE TABLE IF NOT EXISTS knowledge(id TEXT PRIMARY KEY,question TEXT NOT NULL,answer TEXT NOT NULL,category TEXT NOT NULL,source TEXT NOT NULL,updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS tickets(id INTEGER PRIMARY KEY AUTOINCREMENT,public_number TEXT UNIQUE,title TEXT NOT NULL,description TEXT NOT NULL,category_id INTEGER NOT NULL REFERENCES categories(id),location_id INTEGER NOT NULL REFERENCES locations(id),status TEXT NOT NULL DEFAULT 'Новая',priority TEXT NOT NULL,assignee_id INTEGER REFERENCES users(id),tracking_token_hash TEXT UNIQUE NOT NULL,idempotency_key TEXT UNIQUE NOT NULL,submission_hash TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,resolved_at TEXT);
    CREATE TABLE IF NOT EXISTS comments(id INTEGER PRIMARY KEY,ticket_id INTEGER NOT NULL REFERENCES tickets(id),author_id INTEGER REFERENCES users(id),body TEXT NOT NULL,visibility TEXT NOT NULL CHECK(visibility IN ('public','internal')),created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY,ticket_id INTEGER NOT NULL REFERENCES tickets(id),actor_id INTEGER REFERENCES users(id),old_status TEXT,new_status TEXT,note TEXT NOT NULL,visibility TEXT NOT NULL DEFAULT 'public',created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS attachments(id TEXT PRIMARY KEY,ticket_id INTEGER NOT NULL REFERENCES tickets(id),data BLOB NOT NULL,file_type TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS analyses(id INTEGER PRIMARY KEY,kind TEXT NOT NULL,provider TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,actor_id INTEGER NOT NULL REFERENCES users(id),action TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS tickets_status_idx ON tickets(status,created_at);
    CREATE INDEX IF NOT EXISTS history_ticket_idx ON history(ticket_id);
    ''')
    if 'visibility' not in [row[1] for row in db.execute('PRAGMA table_info(history)')]:
        db.execute("ALTER TABLE history ADD COLUMN visibility TEXT NOT NULL DEFAULT 'public'")
    with db:
        db.execute("UPDATE history SET visibility='internal' WHERE note IN ('Обновлена внутренняя запись','Внутренняя заметка')")
        for key,value in [('tracking_secret',secrets.token_hex(32)),('public_url',os.getenv('PUBLIC_URL','http://localhost:5173')),('system_prompt',SEED['system_prompt'])]: db.execute('INSERT OR IGNORE INTO settings VALUES (?,?)',(key,value))
        for name in SEED['categories']: db.execute('INSERT OR IGNORE INTO categories(name) VALUES (?)',(name,))
        for floor,start,end in [(1,101,110),(2,201,216),(3,301,317)]:
            for room in range(start,end+1): db.execute('INSERT OR IGNORE INTO locations(building,floor,room,qr_key) VALUES (?,?,?,?)',('Главный корпус',floor,str(room),secrets.token_hex(16)))
        for k in SEED['knowledge']:
            db.execute('INSERT INTO knowledge(id,question,answer,category,source,updated_at) VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET question=excluded.question,answer=excluded.answer,category=excluded.category,source=excluded.source,updated_at=excluded.updated_at',(k['id'],k['question'],k['answer'],k['category'],k['source'],now()))
        credentials=[]
        for login,name,role,env in [('admin','Администратор УПК','admin','ADMIN_PASSWORD'),('staff','Сотрудник УПК','staff','STAFF_PASSWORD')]:
            if not db.execute('SELECT id FROM users WHERE login=?',(login,)).fetchone():
                password=os.getenv(env) or secrets.token_urlsafe(14)
                db.execute('INSERT INTO users(name,login,password_hash,role) VALUES (?,?,?,?)',(name,login,PASSWORDS.hash(password),role))
                credentials.append(f'{login}: {password}')
        if credentials and path!=':memory:' and os.getenv('WRITE_CREDENTIALS','true')=='true':
            f=Path('.local-credentials'); fd=os.open(str(f),os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
            with os.fdopen(fd,'a') as out: out.write('\n'.join(credentials)+'\n')
            print('Учётные записи созданы. Пароли находятся в .local-credentials')
    db.close()
