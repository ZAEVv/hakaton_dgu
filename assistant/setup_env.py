"""Create a local development .env once, without printing or overwriting secrets."""
import os
import secrets
from pathlib import Path


def create_local_env(path, example):
    text = Path(example).read_text(encoding='utf-8')
    text = text.replace('SECRET_KEY=\n', 'SECRET_KEY=' + secrets.token_urlsafe(48) + '\n', 1)
    text = text.replace('SESSION_COOKIE_SECURE=1\n', 'SESSION_COOKIE_SECURE=0\n', 1)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as out:
        out.write(text)


if __name__ == '__main__':
    base = Path(__file__).resolve().parent
    try:
        create_local_env(base / '.env', base / '.env.example')
    except FileExistsError:
        print('.env уже существует; файл не изменён.')
    else:
        print('Создан .env для локального HTTP. Добавьте ключ нейросети вручную при необходимости.')
