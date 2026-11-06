from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from io import BytesIO, StringIO
import csv
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
import zipfile
from urllib.parse import urlparse
from collections import defaultdict, deque
from typing import Literal

from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI, Depends, Request, Response, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from PIL import Image, ImageOps, UnidentifiedImageError, ImageDraw, ImageFont
import qrcode
from .db import initialize, connect, digest, now, PASSWORDS, SEED
from .ai import analyze, DANGER

class Login(BaseModel):
    login: str = Field(min_length=1,max_length=80)
    password: str = Field(min_length=1,max_length=200)
class HistoryMessage(BaseModel):
    role: Literal['user','assistant']
    content: str = Field(min_length=1,max_length=3000)
class Analysis(BaseModel):
    text: str = Field(min_length=2,max_length=4000)
    location_id: int | None = None
    history: list[HistoryMessage] = Field(default_factory=list,max_length=12)
class UpdateTicket(BaseModel):
    status: str
    assignee_id: int | None = None
    category_id: int
    priority: str
    comment: str = Field(default='',max_length=4000)
    visibility: str = 'public'
    expected_updated_at: str
class Comment(BaseModel):
    body: str = Field(min_length=1,max_length=4000)
class StaffMessage(BaseModel):
    body: str = Field(min_length=1,max_length=4000)
    visibility: Literal['public','internal'] = 'public'
class LocationInput(BaseModel):
    building: str = Field(min_length=1,max_length=100)
    floor: int = Field(ge=0,le=30)
    room: str = Field(min_length=1,max_length=30)
    zone_name: str = Field(default='',max_length=100)
    active: bool = True
class UserInput(BaseModel):
    name: str = Field(min_length=2,max_length=100)
    login: str = Field(min_length=3,max_length=80,pattern=r'^[a-zA-Z0-9_.-]+$')
    password: str = Field(min_length=10,max_length=200)
    role: str
class UserUpdate(BaseModel):
    name: str = Field(min_length=2,max_length=100)
    role: str
    active: bool
    password: str = Field(default='',max_length=200)
class SettingsInput(BaseModel):
    public_url: str = Field(max_length=250)
    system_prompt: str = Field(default='',max_length=8000)
class CategoryInput(BaseModel):
    name: str = Field(min_length=2,max_length=80)

SELECT_TICKET='''SELECT t.*, c.name category,l.building,l.floor,l.room,l.zone_name,u.name assignee
 FROM tickets t JOIN categories c ON c.id=t.category_id JOIN locations l ON l.id=t.location_id LEFT JOIN users u ON u.id=t.assignee_id'''

def create_app(db_path=None):
    path=db_path or os.getenv('DB_PATH','.data/upk.sqlite')
    initialize(path)
    app=FastAPI(title='Цифровой помощник УПК',version='1.0.0')
    app.state.path=path
    lock=threading.RLock()
    rates=defaultdict(deque)
    staff_message_rates=defaultdict(deque)
    def db():
        connection=connect(path)
        try: yield connection
        finally: connection.close()
    def require_user(request:Request,connection=Depends(db)):
        token=request.cookies.get('upk_session','')
        row=connection.execute('SELECT u.id,u.name,u.login,u.role FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>? AND u.active=1',(digest(token),now())).fetchone()
        if not row: raise HTTPException(401,'Войдите в панель сотрудника')
        return dict(row)
    def admin(user=Depends(require_user)):
        if user['role']!='admin': raise HTTPException(403,'Действие доступно только администратору')
        return user
    def audit(connection,user,action): connection.execute('INSERT INTO audit(actor_id,action,created_at) VALUES (?,?,?)',(user['id'],action,now()))
    def setting(connection,key): return connection.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()['value']
    def location(connection,id):
        row=connection.execute('SELECT * FROM locations WHERE id=? AND active=1',(id,)).fetchone()
        if not row: raise HTTPException(400,'Выберите существующий кабинет')
        return dict(row)
    def tracked(connection,token):
        if not re.fullmatch(r'[a-f0-9]{64}',token): raise HTTPException(404,'Заявка не найдена. Проверьте безопасную ссылку.')
        row=connection.execute(SELECT_TICKET+' WHERE t.tracking_token_hash=?',(digest(token),)).fetchone()
        if not row: raise HTTPException(404,'Заявка не найдена. Проверьте безопасную ссылку.')
        return row
    def ticket_detail(connection,row,private=False):
        data=dict(row)
        for key in ['tracking_token_hash','idempotency_key','submission_hash']: data.pop(key,None)
        args=(row['id'],)
        data['comments']=[dict(r) for r in connection.execute("SELECT c.id,c.body,c.visibility,c.created_at,COALESCE(u.name,'Заявитель') author FROM comments c LEFT JOIN users u ON u.id=c.author_id WHERE c.ticket_id=?"+('' if private else " AND c.visibility='public'")+' ORDER BY c.id',args)]
        data['history']=[dict(r) for r in connection.execute("SELECT h.id,h.old_status,h.new_status,h.note,h.created_at,COALESCE(u.name,'Система') author FROM history h LEFT JOIN users u ON u.id=h.actor_id WHERE ticket_id=?"+("" if private else " AND h.visibility='public'")+" ORDER BY h.id",args)]
        data['attachments']=[dict(r) for r in connection.execute('SELECT id,file_type,created_at FROM attachments WHERE ticket_id=?',args)]
        return data
    def qr_image(connection,loc):
        url=setting(connection,'public_url').rstrip('/')+'/chat?qr='+loc['qr_key']
        qr=qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,box_size=12,border=4);qr.add_data(url);qr.make(fit=True)
        image=qr.make_image(fill_color='#10213f',back_color='white').convert('RGB')
        image=ImageOps.contain(image,(640,640)); canvas=Image.new('RGB',(720,820),'white');canvas.paste(image,((720-image.width)//2,110))
        draw=ImageDraw.Draw(canvas)
        fontpath=str(Path(__file__).with_name('fonts')/'LiberationSans-Regular.ttf')
        font=ImageFont.truetype(fontpath,34);small=ImageFont.truetype(fontpath,22)
        draw.text((360,45),f"УПК · Кабинет {loc['room']}",font=font,fill='#10213f',anchor='mt')
        draw.text((360,745),f"{loc['floor']} этаж · Помощник колледжа",font=small,fill='#10213f',anchor='mt')
        result=BytesIO();canvas.save(result,format='PNG');return result.getvalue()

    @app.middleware('http')
    async def protection(request,call_next):
        if request.url.path.startswith('/api/'):
            # Origin-проверка защищает cookie-сессию от межсайтовых изменений.
            if request.method not in ('GET','HEAD','OPTIONS'):
                origin=request.headers.get('origin')
                if origin:
                    allowed={f'{request.url.scheme}://{request.url.netloc}',os.getenv('PUBLIC_URL','http://localhost:5173').rstrip('/')}
                    if os.getenv('COOKIE_SECURE','false').lower()!='true': allowed.update({'http://localhost:5173','http://127.0.0.1:5173'})
                    # Публичный адрес админ может сменить для QR в локальной сети.
                    with connect(path) as c: allowed.add(setting(c,'public_url').rstrip('/'))
                    if origin.rstrip('/') not in allowed: return Response(json.dumps({'detail':'Недопустимый источник запроса'},ensure_ascii=False),403,media_type='application/json')
            limit=10 if request.url.path=='/api/auth/login' else 35 if request.url.path=='/api/assistant' else 80
            if request.method=='POST':
                key=(request.client.host if request.client else 'unknown',request.url.path)
                with lock:
                    q=rates[key]; current=time.monotonic()
                    while q and current-q[0]>60: q.popleft()
                    if len(q)>=limit: return Response('{"detail":"Слишком много запросов. Повторите через минуту."}',429,media_type='application/json')
                    q.append(current)
                    if len(rates)>5000:
                        for old in list(rates):
                            if not rates[old] or current-rates[old][-1]>60: del rates[old]
            size=request.headers.get('content-length')
            if size and int(size)>9*1024*1024: return Response('{"detail":"Файл должен быть не больше 8 МБ."}',413,media_type='application/json')
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['X-Frame-Options']='DENY'
        if request.url.path.startswith('/api/') or request.url.path.startswith('/track/'): response.headers['Cache-Control']='no-store'
        if request.url.path.startswith('/track/') or request.url.path.startswith('/api/track/'): response.headers['X-Robots-Tag']='noindex, nofollow'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; font-src 'self'; connect-src 'self' ws:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        return response

    @app.exception_handler(sqlite3.IntegrityError)
    async def integrity_error(request,exc): return Response(json.dumps({'detail':'Такая запись уже существует или используется в заявках.'},ensure_ascii=False),409,media_type='application/json')

    @app.get('/api/health')
    def health(): return {'status':'ok'}

    @app.get('/api/bootstrap')
    def bootstrap(qr:str|None=None,connection=Depends(db)):
        locations=[dict(r) for r in connection.execute('SELECT id,building,floor,room,zone_name FROM locations WHERE active=1 ORDER BY floor,room')]
        selected=None
        if qr:
            row=connection.execute('SELECT id FROM locations WHERE qr_key=? AND active=1',(qr,)).fetchone()
            selected=row['id'] if row else None
        return dict(locations=locations,categories=[dict(r) for r in connection.execute('SELECT * FROM categories')],statuses=SEED['statuses'],selected_location_id=selected,invalid_qr=bool(qr and not selected),knowledge=[dict(r) for r in connection.execute('SELECT * FROM knowledge')],ai_mode='deepseek' if os.getenv('DEEPSEEK_API_KEY') else 'knowledge')

    @app.post('/api/assistant')
    async def assistant(body:Analysis,connection=Depends(db)):
        loc=location(connection,body.location_id) if body.location_id else None
        knowledge=[dict(r) for r in connection.execute('SELECT * FROM knowledge')]
        categories=[r['name'] for r in connection.execute('SELECT * FROM categories')]
        if len(body.text.strip())<2: raise HTTPException(400,'Опишите вопрос или проблему')
        result=await analyze(body.text,[m.model_dump() for m in body.history],loc,knowledge,categories,system_prompt=setting(connection,'system_prompt'))
        with connection: connection.execute('INSERT INTO analyses(kind,provider,created_at) VALUES (?,?,?)',(result['kind'],result['provider'],now()))
        return result

    @app.post('/api/tickets',status_code=201)
    async def create_ticket(description:str=Form(...,min_length=5,max_length=4000),title:str=Form(...,min_length=3,max_length=120),category_id:int=Form(...),location_id:int=Form(...),idempotency_key:str=Form(...,min_length=30,max_length=100),priority:str=Form(default=''),photo:UploadFile|None=File(None),connection=Depends(db)):
        if len(description.strip())<5 or len(title.strip())<3: raise HTTPException(400,'Добавьте заголовок и описание проблемы')
        if priority and priority not in ['Обычный','Высокий','Срочный']: raise HTTPException(400,'Некорректный приоритет')
        loc=location(connection,location_id)
        if not connection.execute('SELECT id FROM categories WHERE id=?',(category_id,)).fetchone(): raise HTTPException(400,'Выберите категорию')
        if not re.fullmatch(r'[a-zA-Z0-9_-]{30,100}',idempotency_key): raise HTTPException(400,'Некорректный идентификатор отправки')
        image_data=None
        if photo:
            raw=await photo.read(8*1024*1024+1)
            if len(raw)>8*1024*1024: raise HTTPException(413,'Фотография должна быть не больше 8 МБ')
            try:
                with Image.open(BytesIO(raw)) as image:
                    if image.format not in ['JPEG','PNG','WEBP'] or image.width*image.height>24_000_000: raise ValueError()
                    image.load(); image=ImageOps.exif_transpose(image).convert('RGB');image.thumbnail((1800,1800))
                    out=BytesIO();image.save(out,'JPEG',quality=86);image_data=out.getvalue()
            except (UnidentifiedImageError,OSError,ValueError,Image.DecompressionBombError): raise HTTPException(400,'Прикрепите корректное фото JPEG, PNG или WebP до 24 мегапикселей')
        fingerprint=digest(json.dumps([description.strip(),title.strip(),category_id,location_id,priority,hashlib.sha256(image_data or b'').hexdigest()],ensure_ascii=False))
        token=hmac.new(setting(connection,'tracking_secret').encode(),idempotency_key.encode(),hashlib.sha256).hexdigest()
        with lock,connection:
            existing=connection.execute('SELECT * FROM tickets WHERE idempotency_key=?',(idempotency_key,)).fetchone()
            if existing:
                if existing['submission_hash']!=fingerprint: raise HTTPException(409,'Эта отправка уже сохранена с другим содержимым. Откройте созданную заявку.')
                return dict(number=existing['public_number'],token=token,reused=True)
            created=now();priority='Срочный' if DANGER.search(description) else (priority or 'Обычный')
            cursor=connection.execute('INSERT INTO tickets(title,description,category_id,location_id,priority,tracking_token_hash,idempotency_key,submission_hash,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)',(title.strip(),description.strip(),category_id,loc['id'],priority,digest(token),idempotency_key,fingerprint,created,created))
            tid=cursor.lastrowid;number=f'УПК-{tid:05d}'
            connection.execute('UPDATE tickets SET public_number=? WHERE id=?',(number,tid))
            connection.execute('INSERT INTO history(ticket_id,new_status,note,created_at) VALUES (?,?,?,?)',(tid,'Новая','Заявка зарегистрирована',created))
            if image_data: connection.execute('INSERT INTO attachments VALUES (?,?,?,?,?)',(secrets.token_hex(20),tid,image_data,'image/jpeg',created))
        return dict(number=number,token=token,reused=False)

    @app.get('/api/track/{token}')
    def track(token:str,connection=Depends(db)): return ticket_detail(connection,tracked(connection,token))
    @app.post('/api/track/{token}/comments')
    def public_comment(token:str,body:Comment,connection=Depends(db)):
        row=tracked(connection,token)
        if not body.body.strip(): raise HTTPException(400,'Напишите комментарий')
        with connection:
            connection.execute('INSERT INTO comments(ticket_id,body,visibility,created_at) VALUES (?,?,?,?)',(row['id'],body.body.strip(),'public',now()))
            connection.execute('UPDATE tickets SET updated_at=? WHERE id=?',(now(),row['id']))
        return {'ok':True}
    @app.get('/api/track/{token}/attachments/{aid}')
    def public_attachment(token:str,aid:str,connection=Depends(db)):
        ticket=tracked(connection,token)
        row=connection.execute('SELECT data,file_type FROM attachments WHERE id=? AND ticket_id=?',(aid,ticket['id'])).fetchone()
        if not row: raise HTTPException(404,'Фотография не найдена')
        return Response(row['data'],media_type=row['file_type'])

    @app.post('/api/auth/login')
    def login(body:Login,response:Response,connection=Depends(db)):
        row=connection.execute('SELECT * FROM users WHERE login=? AND active=1',(body.login,)).fetchone()
        try:
            if not row: PASSWORDS.verify(PASSWORDS.hash('invalid-account-timing'),body.password)
            else: PASSWORDS.verify(row['password_hash'],body.password)
        except Exception: raise HTTPException(401,'Неверный логин или пароль')
        if not row: raise HTTPException(401,'Неверный логин или пароль')
        token=secrets.token_urlsafe(40);expires=(datetime.now(timezone.utc)+timedelta(hours=12)).isoformat()
        with connection:
            connection.execute('DELETE FROM sessions WHERE expires_at<?',(now(),))
            connection.execute('INSERT INTO sessions VALUES (?,?,?)',(digest(token),row['id'],expires))
        response.set_cookie('upk_session',token,httponly=True,samesite='lax',secure=os.getenv('COOKIE_SECURE','false').lower()=='true',max_age=43200,path='/')
        return {k:row[k] for k in ['id','name','login','role']}
    @app.get('/api/auth/me')
    def me(user=Depends(require_user)): return user
    @app.post('/api/auth/logout')
    def logout(request:Request,response:Response,connection=Depends(db)):
        with connection: connection.execute('DELETE FROM sessions WHERE token_hash=?',(digest(request.cookies.get('upk_session','')),))
        response.delete_cookie('upk_session',path='/');return {'ok':True}

    def filtered(connection,query='',status='',category='',room='',date_from='',date_to='',mine='',unassigned=False,attention=False):
        clauses=[];args=[]
        if query: clauses.append('(CASEFOLD(t.public_number) LIKE ? OR CASEFOLD(t.title) LIKE ? OR CASEFOLD(t.description) LIKE ?)');args.extend([f'%{query.casefold()}%']*3)
        for field,value in [('t.status',status),('t.category_id',category),('t.location_id',room)]:
            if value: clauses.append(field+'=?');args.append(value)
        if mine: clauses.append('t.assignee_id=?');args.append(mine)
        if unassigned:
            clauses.append('t.assignee_id IS NULL');clauses.append("t.status NOT IN ('Решена','Отклонена')")
        if attention:
            clauses.append("t.status NOT IN ('Решена','Отклонена') AND (t.priority='Срочный' OR t.assignee_id IS NULL OR t.status='Нужны уточнения')")
        for op,value in [('>=',date_from),('<=',date_to)]:
            if value:
                try: datetime.strptime(value,'%Y-%m-%d')
                except ValueError: raise HTTPException(400,'Дата должна иметь формат ГГГГ-ММ-ДД')
                clauses.append(f"date(t.created_at,'+3 hours'){op}?");args.append(value)
        return connection.execute(SELECT_TICKET+(' WHERE '+' AND '.join(clauses) if clauses else '')+' ORDER BY t.id DESC',args).fetchall()
    @app.get('/api/staff/tickets')
    def tickets(query:str='',status:str='',category:str='',room:str='',date_from:str='',date_to:str='',mine:bool=False,unassigned:bool=False,attention:bool=False,user=Depends(require_user),connection=Depends(db)):
        return [ticket_detail(connection,r,True) for r in filtered(connection,query,status,category,room,date_from,date_to,user['id'] if mine else '',unassigned,attention)]
    @app.get('/api/staff/export.csv')
    def export(query:str='',status:str='',category:str='',room:str='',date_from:str='',date_to:str='',mine:bool=False,unassigned:bool=False,attention:bool=False,user=Depends(require_user),connection=Depends(db)):
        out=StringIO();writer=csv.writer(out);writer.writerow(['Номер','Создана','Заголовок','Описание','Категория','Кабинет','Статус','Приоритет','Исполнитель'])
        def safe(v):
            v=str(v or ''); return "'"+v if v.lstrip().startswith(('=','+','-','@')) else v
        for r in filtered(connection,query,status,category,room,date_from,date_to,user['id'] if mine else '',unassigned,attention): writer.writerow([safe(r[k]) for k in ['public_number','created_at','title','description','category','room','status','priority','assignee']])
        return Response('\ufeff'+out.getvalue(),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="upk-tickets.csv"'})
    @app.get('/api/staff/users')
    def staff_users(user=Depends(require_user),connection=Depends(db)): return [dict(r) for r in connection.execute('SELECT id,name,role,active FROM users WHERE active=1')]
    @app.get('/api/staff/tickets/{tid}')
    def detail(tid:int,user=Depends(require_user),connection=Depends(db)):
        row=connection.execute(SELECT_TICKET+' WHERE t.id=?',(tid,)).fetchone()
        if not row: raise HTTPException(404,'Заявка не найдена')
        return ticket_detail(connection,row,True)
    @app.post('/api/staff/tickets/{tid}/comments')
    def staff_message(tid:int,body:StaffMessage,user=Depends(require_user),connection=Depends(db)):
        text=body.body.strip()
        if not text: raise HTTPException(400,'Напишите сообщение')
        with lock,connection:
            old=connection.execute('SELECT public_number FROM tickets WHERE id=?',(tid,)).fetchone()
            if not old: raise HTTPException(404,'Заявка не найдена')
            queue=staff_message_rates[(user['id'],tid)];current=time.monotonic()
            while queue and current-queue[0]>60: queue.popleft()
            if len(queue)>=12: raise HTTPException(429,'Слишком много сообщений по этой заявке. Подождите минуту.')
            queue.append(current)
            stamp=now()
            visibility='public' if body.visibility=='public' else 'internal'
            connection.execute('INSERT INTO comments(ticket_id,author_id,body,visibility,created_at) VALUES (?,?,?,?,?)',(tid,user['id'],text,visibility,stamp))
            connection.execute('UPDATE tickets SET updated_at=? WHERE id=?',(stamp,tid))
            note='Написано заявителю' if visibility=='public' else 'Внутренняя заметка'
            connection.execute('INSERT INTO history(ticket_id,actor_id,note,visibility,created_at) VALUES (?,?,?,?,?)',(tid,user['id'],note,visibility,stamp))
            audit(connection,user,f'Сообщение по заявке {old["public_number"]}')
            row=connection.execute(SELECT_TICKET+' WHERE t.id=?',(tid,)).fetchone()
            return ticket_detail(connection,row,True)
    @app.patch('/api/staff/tickets/{tid}')
    def update_ticket(tid:int,body:UpdateTicket,user=Depends(require_user),connection=Depends(db)):
        with lock,connection:
            old=connection.execute('SELECT * FROM tickets WHERE id=?',(tid,)).fetchone()
            if not old: raise HTTPException(404,'Заявка не найдена')
            if old['updated_at']!=body.expected_updated_at: raise HTTPException(409,'Заявка уже изменилась. Обновите карточку и повторите действие.')
            if body.status not in SEED['statuses']: raise HTTPException(400,'Неизвестный статус')
            if body.status=='Новая' and old['status']!='Новая': raise HTTPException(400,'Статус «Новая» устанавливается при регистрации')
            if body.status in ['Решена','Отклонена'] and not body.comment.strip(): raise HTTPException(400,'Добавьте итоговый комментарий или причину отклонения')
            if body.status in ['Назначен исполнитель','В работе'] and not body.assignee_id: raise HTTPException(400,'Назначьте исполнителя')
            if body.assignee_id and not connection.execute('SELECT id FROM users WHERE id=? AND active=1',(body.assignee_id,)).fetchone(): raise HTTPException(400,'Исполнитель не найден')
            if not connection.execute('SELECT id FROM categories WHERE id=?',(body.category_id,)).fetchone(): raise HTTPException(400,'Категория не найдена')
            if body.priority not in ['Обычный','Высокий','Срочный'] or body.visibility not in ['public','internal']: raise HTTPException(400,'Некорректные параметры')
            stamp=now();resolved=(old['resolved_at'] if old['status']==body.status and old['resolved_at'] else stamp) if body.status in ['Решена','Отклонена'] else None
            connection.execute('UPDATE tickets SET status=?,assignee_id=?,category_id=?,priority=?,updated_at=?,resolved_at=? WHERE id=?',(body.status,body.assignee_id,body.category_id,body.priority,stamp,resolved,tid))
            if body.status!=old['status']: connection.execute('INSERT INTO history(ticket_id,actor_id,old_status,new_status,note,created_at) VALUES (?,?,?,?,?,?)',(tid,user['id'],old['status'],body.status,'Изменён статус',stamp))
            if body.assignee_id!=old['assignee_id']: connection.execute('INSERT INTO history(ticket_id,actor_id,note,created_at) VALUES (?,?,?,?)',(tid,user['id'],'Обновлён исполнитель',stamp))
            if body.category_id!=old['category_id'] or body.priority!=old['priority']: connection.execute('INSERT INTO history(ticket_id,actor_id,note,created_at) VALUES (?,?,?,?)',(tid,user['id'],'Обновлены категория или приоритет',stamp))
            if body.comment.strip():
                visibility='public' if body.status in ['Решена','Отклонена'] else body.visibility
                connection.execute('INSERT INTO comments(ticket_id,author_id,body,visibility,created_at) VALUES (?,?,?,?,?)',(tid,user['id'],body.comment.strip(),visibility,stamp))
                connection.execute('INSERT INTO history(ticket_id,actor_id,note,visibility,created_at) VALUES (?,?,?,?,?)',(tid,user['id'],'Добавлен комментарий' if visibility=='public' else 'Обновлена внутренняя запись',visibility,stamp))
            audit(connection,user,f'Обновлена заявка {old["public_number"]}')
        return detail(tid,user,connection)
    @app.get('/api/staff/attachments/{aid}')
    def attachment(aid:str,user=Depends(require_user),connection=Depends(db)):
        row=connection.execute('SELECT data,file_type FROM attachments WHERE id=?',(aid,)).fetchone()
        if not row: raise HTTPException(404,'Фотография не найдена')
        return Response(row['data'],media_type=row['file_type'])
    @app.get('/api/staff/stats')
    def stats(user=Depends(require_user),connection=Depends(db)):
        rows=connection.execute('SELECT * FROM tickets').fetchall();total=len(rows);solved=sum(r['status']=='Решена' for r in rows);open_count=sum(r['status'] not in ['Решена','Отклонена'] for r in rows)
        avg=connection.execute("SELECT AVG((julianday(resolved_at)-julianday(created_at))*24) hours FROM tickets WHERE status='Решена' AND resolved_at IS NOT NULL").fetchone()['hours']
        today=(datetime.now(timezone.utc)+timedelta(hours=3)).date();start=today-timedelta(days=13)
        created={r['day']:r['count'] for r in connection.execute("SELECT date(created_at,'+3 hours') day,COUNT(*) count FROM tickets WHERE date(created_at,'+3 hours')>=? GROUP BY day",(start.isoformat(),))}
        resolved={r['day']:r['count'] for r in connection.execute("SELECT date(resolved_at,'+3 hours') day,COUNT(*) count FROM tickets WHERE resolved_at IS NOT NULL AND date(resolved_at,'+3 hours')>=? GROUP BY day",(start.isoformat(),))}
        daily=[dict(date=(start+timedelta(days=offset)).isoformat(),created=created.get((start+timedelta(days=offset)).isoformat(),0),resolved=resolved.get((start+timedelta(days=offset)).isoformat(),0)) for offset in range(14)]
        attention=connection.execute("SELECT COUNT(*) count FROM tickets WHERE status NOT IN ('Решена','Отклонена') AND (priority='Срочный' OR assignee_id IS NULL OR status='Нужны уточнения')").fetchone()['count']
        unassigned=connection.execute("SELECT COUNT(*) count FROM tickets WHERE assignee_id IS NULL AND status NOT IN ('Решена','Отклонена')").fetchone()['count']
        return dict(total=total,open=open_count,solved=solved,urgent=sum(r['priority']=='Срочный' and r['status'] not in ['Решена','Отклонена'] for r in rows),attention=attention,unassigned=unassigned,avg_hours=round(avg,1) if avg is not None else None,daily=daily,categories=[dict(r) for r in connection.execute('SELECT c.name,COUNT(t.id) count FROM categories c LEFT JOIN tickets t ON c.id=t.category_id GROUP BY c.id ORDER BY count DESC')],rooms=[dict(r) for r in connection.execute('SELECT l.room,l.floor,COUNT(t.id) count FROM locations l JOIN tickets t ON l.id=t.location_id GROUP BY l.id ORDER BY count DESC LIMIT 10')],statuses=[dict(r) for r in connection.execute('SELECT status,COUNT(*) count FROM tickets GROUP BY status')],priorities=[dict(r) for r in connection.execute('SELECT priority,COUNT(*) count FROM tickets GROUP BY priority')],assignees=[dict(r) for r in connection.execute("SELECT u.id,u.name,SUM(CASE WHEN t.status NOT IN ('Решена','Отклонена') THEN 1 ELSE 0 END) open,SUM(CASE WHEN t.status='Решена' THEN 1 ELSE 0 END) solved FROM users u LEFT JOIN tickets t ON t.assignee_id=u.id WHERE u.active=1 GROUP BY u.id ORDER BY open DESC,u.name")],ai=[dict(r) for r in connection.execute('SELECT kind,provider,COUNT(*) count FROM analyses GROUP BY kind,provider')])

    @app.get('/api/admin/locations')
    def locations(user=Depends(admin),connection=Depends(db)): return [dict(r) for r in connection.execute('SELECT * FROM locations ORDER BY floor,room')]
    @app.post('/api/admin/locations')
    def add_location(body:LocationInput,user=Depends(admin),connection=Depends(db)):
        with connection:
            connection.execute('INSERT INTO locations(building,floor,room,zone_name,qr_key,active) VALUES (?,?,?,?,?,?)',(body.building,body.floor,body.room,body.zone_name,secrets.token_hex(16),body.active));audit(connection,user,'Добавлен кабинет '+body.room)
        return {'ok':True}
    @app.patch('/api/admin/locations/{lid}')
    def edit_location(lid:int,body:LocationInput,user=Depends(admin),connection=Depends(db)):
        with connection:
            if not connection.execute('SELECT id FROM locations WHERE id=?',(lid,)).fetchone(): raise HTTPException(404,'Кабинет не найден')
            connection.execute('UPDATE locations SET building=?,floor=?,room=?,zone_name=?,active=? WHERE id=?',(body.building,body.floor,body.room,body.zone_name,body.active,lid));audit(connection,user,'Изменён кабинет '+body.room)
        return {'ok':True}
    @app.post('/api/admin/locations/{lid}/rotate')
    def rotate(lid:int,user=Depends(admin),connection=Depends(db)):
        with connection:
            if not connection.execute('UPDATE locations SET qr_key=? WHERE id=?',(secrets.token_hex(16),lid)).rowcount: raise HTTPException(404,'Кабинет не найден')
            audit(connection,user,f'Обновлена QR-привязка кабинета ID {lid}')
        return {'ok':True}
    @app.get('/api/admin/qr/{lid}.png')
    def qr_png(lid:int,download:bool=False,user=Depends(admin),connection=Depends(db)):
        loc=location(connection,lid)
        return Response(qr_image(connection,loc),media_type='image/png',headers={'Content-Disposition':f'{"attachment" if download else "inline"}; filename="upk-room-{loc["room"]}.png"'})
    @app.get('/api/admin/qr.zip')
    def qr_zip(user=Depends(admin),connection=Depends(db)):
        out=BytesIO()
        with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as archive:
            for r in connection.execute('SELECT * FROM locations WHERE active=1 ORDER BY floor,room'): archive.writestr(f'floor-{r["floor"]}/upk-room-{r["room"]}.png',qr_image(connection,dict(r)))
        return Response(out.getvalue(),media_type='application/zip',headers={'Content-Disposition':'attachment; filename="upk-qr-codes.zip"'})
    @app.get('/api/admin/settings')
    def settings(user=Depends(admin),connection=Depends(db)):
        return dict(public_url=setting(connection,'public_url'),ai_mode='deepseek' if os.getenv('DEEPSEEK_API_KEY') else 'knowledge',model=os.getenv('DEEPSEEK_MODEL','deepseek-flash'),system_prompt=setting(connection,'system_prompt'))
    @app.put('/api/admin/settings')
    def update_settings(body:SettingsInput,user=Depends(admin),connection=Depends(db)):
        parsed=urlparse(body.public_url)
        if parsed.scheme not in ['http','https'] or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ['','/']: raise HTTPException(400,'Укажите адрес приложения без пути, например http://192.168.1.10:5173')
        prompt=body.system_prompt.strip()
        if body.system_prompt and not prompt: raise HTTPException(400,'Системный промпт не может быть пустым')
        with connection:
            connection.execute('UPDATE settings SET value=? WHERE key=?',(body.public_url.rstrip('/'),'public_url'))
            if prompt: connection.execute('UPDATE settings SET value=? WHERE key=?',(prompt,'system_prompt'))
            audit(connection,user,'Изменён системный промпт' if prompt else 'Изменён адрес для QR-кодов')
        return {'ok':True}
    @app.get('/api/admin/users')
    def users(user=Depends(admin),connection=Depends(db)): return [dict(r) for r in connection.execute('SELECT id,name,login,role,active FROM users')]
    @app.post('/api/admin/users')
    def add_user(body:UserInput,user=Depends(admin),connection=Depends(db)):
        if body.role not in ['admin','staff']: raise HTTPException(400,'Выберите роль')
        with connection: connection.execute('INSERT INTO users(name,login,password_hash,role) VALUES (?,?,?,?)',(body.name,body.login,PASSWORDS.hash(body.password),body.role));audit(connection,user,'Создан пользователь '+body.login)
        return {'ok':True}
    @app.patch('/api/admin/users/{uid}')
    def edit_user(uid:int,body:UserUpdate,user=Depends(admin),connection=Depends(db)):
        if body.role not in ['admin','staff']: raise HTTPException(400,'Выберите роль')
        if uid==user['id'] and (not body.active or body.role!='admin'): raise HTTPException(400,'Нельзя отключить свой аккаунт или снять свою роль администратора')
        if body.password and len(body.password)<10: raise HTTPException(400,'Пароль должен содержать минимум 10 символов')
        with connection:
            if not connection.execute('UPDATE users SET name=?,role=?,active=? WHERE id=?',(body.name,body.role,body.active,uid)).rowcount: raise HTTPException(404,'Пользователь не найден')
            if body.password: connection.execute('UPDATE users SET password_hash=? WHERE id=?',(PASSWORDS.hash(body.password),uid))
            connection.execute('DELETE FROM sessions WHERE user_id=?',(uid,));audit(connection,user,f'Изменён пользователь ID {uid}')
        return {'ok':True}
    @app.post('/api/admin/categories')
    def add_category(body:CategoryInput,user=Depends(admin),connection=Depends(db)):
        with connection: connection.execute('INSERT INTO categories(name) VALUES (?)',(body.name,));audit(connection,user,'Создана категория '+body.name)
        return {'ok':True}
    @app.patch('/api/admin/categories/{cid}')
    def edit_category(cid:int,body:CategoryInput,user=Depends(admin),connection=Depends(db)):
        with connection:
            if not connection.execute('UPDATE categories SET name=? WHERE id=?',(body.name,cid)).rowcount: raise HTTPException(404,'Категория не найдена')
            audit(connection,user,'Изменена категория '+body.name)
        return {'ok':True}
    @app.get('/api/admin/audit')
    def audit_list(user=Depends(admin),connection=Depends(db)): return [dict(r) for r in connection.execute('SELECT a.*,u.name actor FROM audit a JOIN users u ON u.id=a.actor_id ORDER BY a.id DESC LIMIT 100')]

    if Path('dist').exists():
        app.mount('/assets',StaticFiles(directory='dist/assets'),name='assets')
        @app.get('/{full_path:path}')
        def spa(full_path:str):
            if full_path.startswith('api/'): raise HTTPException(404,'Маршрут не найден')
            return FileResponse('dist/index.html')
    return app

app=create_app()
