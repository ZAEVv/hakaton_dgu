CREATE TABLE IF NOT EXISTS rooms (
    id INTEGER PRIMARY KEY,
    building TEXT NOT NULL,
    name TEXT NOT NULL,
    UNIQUE(building, name)
);

CREATE TABLE IF NOT EXISTS knowledge_base (
    id INTEGER PRIMARY KEY,
    question TEXT NOT NULL UNIQUE,
    answer TEXT NOT NULL,
    is_verified INTEGER NOT NULL DEFAULT 0 CHECK (is_verified IN (0, 1))
);

CREATE TABLE IF NOT EXISTS employees (
    id INTEGER PRIMARY KEY,
    login TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'employee' CHECK (role IN ('admin', 'employee')),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS employee_history (
    id INTEGER PRIMARY KEY,
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    actor_id INTEGER NOT NULL REFERENCES employees(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    action TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS employee_sessions (
    token_hash TEXT PRIMARY KEY,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS applicants (
    id INTEGER PRIMARY KEY,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    record_book TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS applicant_sessions (
    token_hash TEXT PRIMARY KEY,
    applicant_id INTEGER NOT NULL REFERENCES applicants(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY,
    description TEXT NOT NULL,
    category TEXT NOT NULL,
    room_id INTEGER NOT NULL REFERENCES rooms(id),
    status TEXT NOT NULL DEFAULT 'Новая',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    assignee_id INTEGER REFERENCES employees(id),
    version INTEGER NOT NULL DEFAULT 0,
    applicant_id INTEGER REFERENCES applicants(id)
);

CREATE TABLE IF NOT EXISTS ticket_history (
    id INTEGER PRIMARY KEY,
    ticket_id INTEGER NOT NULL REFERENCES tickets(id),
    employee_id INTEGER REFERENCES employees(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    change_description TEXT NOT NULL,
    comment TEXT,
    is_public INTEGER NOT NULL DEFAULT 0 CHECK (is_public IN (0, 1)),
    applicant_id INTEGER REFERENCES applicants(id)
);

CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY,
    ticket_id INTEGER NOT NULL REFERENCES tickets(id),
    file_path TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ticket_access (
    ticket_id INTEGER PRIMARY KEY REFERENCES tickets(id),
    token TEXT NOT NULL UNIQUE,
    request_key TEXT NOT NULL UNIQUE
);

-- Limited request history for per-account assistant usage.
CREATE TABLE IF NOT EXISTS assistant_requests (
    id INTEGER PRIMARY KEY,
    applicant_id INTEGER NOT NULL REFERENCES applicants(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS assistant_requests_applicant_time ON assistant_requests(applicant_id, created_at);

CREATE TABLE IF NOT EXISTS login_attempts (
    id INTEGER PRIMARY KEY,
    client_hash TEXT NOT NULL,
    scope TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS login_attempts_client_time ON login_attempts(client_hash, scope, created_at);
