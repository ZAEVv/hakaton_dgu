"""Экспорт PNG из защищённой админки. Не выводит пароли и cookie."""
import argparse
from pathlib import Path
import os
import getpass
import zipfile
from io import BytesIO
import httpx
from dotenv import load_dotenv
load_dotenv()
p=argparse.ArgumentParser(description='Скачать все QR-коды УПК')
p.add_argument('--url',default='http://localhost:3001');p.add_argument('--output',default='artifacts/qr')
a=p.parse_args()
password=os.getenv('ADMIN_PASSWORD')
if not password and Path('.local-credentials').exists():
    lines=[line for line in Path('.local-credentials').read_text().splitlines() if line.startswith('admin: ')]
    if lines: password=lines[0].split(': ',1)[1]
if not password: password=getpass.getpass('Пароль администратора: ')
with httpx.Client(base_url=a.url,timeout=60,trust_env=False) as client:
    r=client.post('/api/auth/login',json={'login':'admin','password':password});r.raise_for_status()
    r=client.get('/api/admin/qr.zip');r.raise_for_status()
    output=Path(a.output);output.mkdir(parents=True,exist_ok=True)
    archive=output.parent/'upk-qr-codes.zip';archive.write_bytes(r.content)
    with zipfile.ZipFile(BytesIO(r.content)) as z:
        for name in z.namelist():
            target=output/name
            if not target.resolve().is_relative_to(output.resolve()): raise ValueError('Некорректный путь в архиве')
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(z.read(name))
    client.post('/api/auth/logout')
    print(f'Сохранены PNG: {output}; ZIP: {archive}')
