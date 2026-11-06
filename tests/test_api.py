import asyncio
from io import BytesIO
import json
import secrets
import zipfile
import pytest
import httpx
from fastapi.testclient import TestClient
from PIL import Image
from server.app import create_app
from server.db import SEED, connect
from server.ai import analyze, fallback

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('ADMIN_PASSWORD','Admin-testing-2026!')
    monkeypatch.setenv('STAFF_PASSWORD','Staff-testing-2026!')
    monkeypatch.delenv('DEEPSEEK_API_KEY',raising=False)
    monkeypatch.chdir(tmp_path)
    app=create_app(str(tmp_path/'test.sqlite'))
    with TestClient(app) as c: yield c

def login(c,role='admin'):
    result=c.post('/api/auth/login',json={'login':role,'password':f'{role.title()}-testing-2026!'})
    assert result.status_code==200,result.text
    return result.json()

def create(c,**kwargs):
    b=c.get('/api/bootstrap').json()
    data=dict(title='Не работает проектор',description='В кабинете не работает проектор',location_id=str(b['locations'][0]['id']),category_id=str(b['categories'][0]['id']),idempotency_key=secrets.token_hex(20))
    data.update(kwargs)
    r=c.post('/api/tickets',data=data)
    assert r.status_code==201,r.text
    return r.json(),data

def test_all_locations_and_qr(client):
    b=client.get('/api/bootstrap').json()
    assert len(b['locations'])==43
    assert [r['room'] for r in b['locations']]==[str(i) for a,z in [(101,110),(201,216),(301,317)] for i in range(a,z+1)]
    assert client.get('/api/admin/locations').status_code==401
    assert client.get('/api/bootstrap?qr=bad').json()['invalid_qr']
    login(client)
    rooms=client.get('/api/admin/locations').json()
    room=next(r for r in rooms if r['room']=='214')
    assert client.get('/api/bootstrap?qr='+room['qr_key']).json()['selected_location_id']==room['id']
    png=client.get(f'/api/admin/qr/{room["id"]}.png')
    assert png.status_code==200
    assert Image.open(BytesIO(png.content)).size==(720,820)
    archive=client.get('/api/admin/qr.zip')
    with zipfile.ZipFile(BytesIO(archive.content)) as z: assert len(z.namelist())==43
    assert client.post(f'/api/admin/locations/{room["id"]}/rotate').status_code==200
    assert client.get('/api/bootstrap?qr='+room['qr_key']).json()['invalid_qr']

def test_end_to_end_and_private_notes(client):
    made,data=create(client)
    token=made['token']
    assert len(token)==64
    detail=client.get('/api/track/'+token).json()
    assert detail['status']=='Новая'
    assert not {'tracking_token_hash','idempotency_key','submission_hash'} & detail.keys()
    assert client.get('/api/track/'+'f'*64).status_code==404
    login(client,'staff')
    listed=client.get('/api/staff/tickets?query=проектор').json()
    assert len(listed)==1
    assert len(client.get('/api/staff/tickets?query=ПРОЕКТОР').json())==1
    t=listed[0]
    body=dict(status='В работе',assignee_id=2,category_id=t['category_id'],priority='Высокий',comment='INTERNAL SECRET',visibility='internal',expected_updated_at=t['updated_at'])
    r=client.patch(f'/api/staff/tickets/{t["id"]}',json=body)
    assert r.status_code==200,r.text
    assert 'INTERNAL SECRET' not in client.get('/api/track/'+token).text
    assert client.patch(f'/api/staff/tickets/{t["id"]}',json=body).status_code==409
    body.update(status='Решена',comment='',expected_updated_at=r.json()['updated_at'])
    assert client.patch(f'/api/staff/tickets/{t["id"]}',json=body).status_code==400
    body['comment']='Заменён HDMI-кабель, проектор проверен.'
    solved=client.patch(f'/api/staff/tickets/{t["id"]}',json=body)
    assert solved.status_code==200
    public=client.get('/api/track/'+token).json()
    assert public['status']=='Решена'
    assert public['comments'][0]['body']==body['comment']
    assert [h['new_status'] for h in public['history'] if h['new_status']]==['Новая','В работе','Решена']
    stats=client.get('/api/staff/stats').json()
    assert stats['total']==1 and stats['solved']==1 and stats['open']==0
    assert client.post('/api/track/'+token+'/comments',json={'body':'Спасибо, всё работает!'}).status_code==200
    assert client.get('/api/staff/tickets?status=Новая').json()==[]
    assert 'Заменён HDMI' not in client.get('/api/staff/export.csv').text  # comments aren't exported
    assert client.get('/api/admin/users').status_code==403
    assert client.post('/api/auth/logout').status_code==200
    assert client.get('/api/staff/tickets').status_code==401

def test_idempotency_and_validation(client):
    made,data=create(client)
    retry=client.post('/api/tickets',data=data)
    assert retry.json()['token']==made['token'] and retry.json()['reused']
    assert client.post('/api/tickets',data={**data,'description':'Другая проблема'}).status_code==409
    assert client.post('/api/tickets',data={**data,'idempotency_key':secrets.token_hex(20),'location_id':'99999'}).status_code==400
    login(client)
    assert client.get('/api/staff/stats').json()['total']==1
    assert client.patch('/api/staff/tickets/1',json={'status':'Решена'}).status_code==422
    assert client.post('/api/auth/login',json={'login':'admin','password':'wrong'}).status_code==401
    assert client.post('/api/admin/categories',json={'name':'Test'},headers={'Origin':'https://evil.example'}).status_code==403

def test_photos_are_validated_and_protected(client):
    made,data=create(client)
    data['idempotency_key']=secrets.token_hex(20)
    invalid=client.post('/api/tickets',data=data,files={'photo':('bad.jpg',b'<script>evil()</script>','image/jpeg')})
    assert invalid.status_code==400
    image=BytesIO();Image.new('RGB',(32,32),'red').save(image,'PNG')
    r=client.post('/api/tickets',data=data,files={'photo':('photo.png',image.getvalue(),'image/png')})
    assert r.status_code==201,r.text
    ticket=client.get('/api/track/'+r.json()['token']).json()
    aid=ticket['attachments'][0]['id']
    assert client.get('/api/staff/attachments/'+aid).status_code==401
    assert client.get(f'/api/track/{made["token"]}/attachments/{aid}').status_code==404
    blob=client.get(f'/api/track/{r.json()["token"]}/attachments/{aid}')
    assert blob.status_code==200 and blob.headers['content-type']=='image/jpeg'
    assert not Image.open(BytesIO(blob.content)).getexif()

@pytest.mark.parametrize('text,kind',[
 ('Как подключить ноутбук к проектору?','question'),('В кабинете 214 не работает проектор','fault'),
 ('Сломалась ручка окна в кабинете 305','fault'),('В розетке искрит','danger'),
 ('Где посмотреть статус заявки?','question'),('Когда починят проектор?','question'),
 ('У меня проблема','unclear'),('Какой пароль от Wi-Fi сотрудников?','question'),
 ('В кабинете грязно','fault'),('Как заменить проводку самому?','danger'),
 ('Кто выиграл соревнования по шахматам в прошлом году?','unknown'),('Кто директор?','unknown')])
def test_ai_acceptance(client,text,kind):
    r=client.post('/api/assistant',json={'text':text})
    assert r.status_code==200,r.text
    assert r.json()['kind']==kind
    if kind=='danger': assert 'не трогайте' in r.json()['answer'] and r.json()['priority']=='Срочный'
    if 'Когда' in text: assert 'нет' in r.json()['answer']

def test_deepseek_json_and_fallback(monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY','test-key')
    captured=[]
    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'kind':'question','answer':'invented password','knowledgeId':'wifi','confidence':.9})}}]})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            result=await analyze('Какой пароль от Wi-Fi сотрудников?',[],None,SEED['knowledge'],SEED['categories'],client=c)
            assert result['provider']=='deepseek'
            assert 'invented password' not in result['answer']
            assert result['answer']==next(k['answer'] for k in SEED['knowledge'] if k['id']=='wifi')
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(503))) as c:
            result=await analyze('У меня проблема',[],None,SEED['knowledge'],SEED['categories'],client=c)
            assert result['provider']=='fallback' and result['notice']
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'choices':[{'message':{'content':'  '}}]}))) as c:
            assert (await analyze('Тестовая неисправность',[],None,SEED['knowledge'],SEED['categories'],client=c))['provider']=='fallback'
    asyncio.run(run())
    assert captured[0]['response_format']=={'type':'json_object'}
    assert captured[0]['messages'][0]['role']=='system'

def test_admin_management(client):
    me=login(client)
    assert client.patch('/api/admin/users/'+str(me['id']),json={'name':me['name'],'role':'staff','active':True}).status_code==400
    created=client.post('/api/admin/users',json={'name':'Новый сотрудник','login':'new_staff','password':'strong-password-123','role':'staff'})
    assert created.status_code==200
    assert client.post('/api/admin/locations',json={'building':'Лаборатория','floor':1,'room':'Л-1'}).status_code==200
    assert client.put('/api/admin/settings',json={'public_url':'https://college.example.org'}).status_code==200
    assert client.put('/api/admin/settings',json={'public_url':'javascript:alert(1)'}).status_code==400
    assert client.post('/api/admin/categories',json={'name':'Территория'}).status_code==200
    assert len(client.get('/api/admin/audit').json())>=4

def test_qr_room_is_known_without_model_and_not_guessed(client):
    login(client)
    rooms=client.get('/api/admin/locations').json()
    for room in rooms:
        bootstrap=client.get('/api/bootstrap',params={'qr':room['qr_key']}).json()
        assert bootstrap['selected_location_id']==room['id']
    room=next(r for r in rooms if r['room']=='317')
    result=client.post('/api/assistant',json={'text':'В каком я кабинете?','location_id':room['id']}).json()
    assert result['provider']=='context' and result['suggestTicket'] is False
    assert '317' in result['answer'] and '3 этаж' in result['answer']
    no_room=client.post('/api/assistant',json={'text':'В каком я кабинете?'}).json()
    assert no_room['kind']=='unclear' and 'не выбран' in no_room['answer']
    danger=client.post('/api/assistant',json={'text':'В каком я кабинете? Здесь дым и искры','location_id':room['id']}).json()
    assert danger['kind']=='danger'

def test_deepseek_receives_verified_location(monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY','test-key')
    location={'id':24,'room':'214','floor':2,'building':'Главный корпус'}
    captured=[]
    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'kind':'fault','answer':'Заявка','confidence':.95})}}]})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            result=await analyze('Не работает проектор',[],location,SEED['knowledge'],SEED['categories'],client=c,system_prompt='Кастомный системный промпт')
            assert result['provider']=='deepseek'
    asyncio.run(run())
    assert captured[0]['messages'][0]['content'].startswith('Кастомный системный промпт')
    context=json.loads(captured[0]['messages'][0]['content'].split('serverContext=',1)[1])
    assert context['location']==location

def test_ai_intake_asks_room_and_builds_draft(client):
    no_room=client.post('/api/assistant',json={'text':'Не работает проектор'}).json()
    assert no_room['kind']=='fault'
    assert no_room['suggestTicket'] is True and no_room['ready'] is False
    assert any(q['id']=='room' for q in no_room['questions'])
    assert 'в каком' in no_room['answer'].lower()
    assert no_room['title']=='Не работает проектор'

    bootstrap=client.get('/api/bootstrap').json()
    room=next(r for r in bootstrap['locations'] if r['room']=='214')
    ready=client.post('/api/assistant',json={'text':'Не работает проектор','location_id':room['id']}).json()
    assert ready['kind']=='fault' and ready['ready'] is True
    assert not any(q['id']=='room' for q in ready['questions'])
    assert ready['location']['room']=='214' and '214' in ready['summary']
    assert ready['description']=='Не работает проектор.'

def test_ai_intake_asks_details_and_uses_conversation(client):
    bootstrap=client.get('/api/bootstrap').json()
    room=next(r for r in bootstrap['locations'] if r['room']=='305')
    incomplete=client.post('/api/assistant',json={'text':'Не работает','location_id':room['id']}).json()
    assert incomplete['kind']=='fault' and incomplete['ready'] is False
    assert any(q['id']=='details' for q in incomplete['questions'])
    assert 'что именно' in incomplete['questions'][0]['text'].lower()

    follow=client.post('/api/assistant',json={'text':'Проектор не включается, индикатор не горит','location_id':room['id'],'history':[{'role':'user','content':'Не работает'},{'role':'assistant','content':'Что именно не работает?'}]}).json()
    assert follow['kind']=='fault' and follow['ready'] is True
    assert 'проектор' in follow['title'].lower()
    assert 'не включается' in follow['description'].lower()

def test_staff_can_write_to_applicant_without_changing_status(client):
    made,_=create(client)
    token=made['token']
    login(client,'staff')
    ticket=client.get('/api/staff/tickets?query=проектор').json()[0]
    working=client.patch(f'/api/staff/tickets/{ticket["id"]}',json=dict(status='В работе',assignee_id=2,category_id=ticket['category_id'],priority='Обычный',comment='',visibility='public',expected_updated_at=ticket['updated_at']))
    assert working.status_code==200,working.text
    message=client.post(f'/api/staff/tickets/{ticket["id"]}/comments',json={'body':'Заявка принята в работу. Исполнитель уже занимается проблемой.','visibility':'public'})
    assert message.status_code==200,message.text
    assert message.json()['status']=='В работе'
    assert any(c['body']=='Заявка принята в работу. Исполнитель уже занимается проблемой.' for c in message.json()['comments'])
    track=client.get('/api/track/'+token).json()
    assert any(c['body']=='Заявка принята в работу. Исполнитель уже занимается проблемой.' for c in track['comments'])
    assert any(h['note']=='Написано заявителю' for h in message.json()['history'])
    assert 'noindex' in client.get('/api/track/'+token).headers.get('x-robots-tag','')

    internal=client.post(f'/api/staff/tickets/{ticket["id"]}/comments',json={'body':'Внутренняя служебная заметка','visibility':'internal'})
    assert internal.status_code==200
    assert any(c['body']=='Внутренняя служебная заметка' for c in internal.json()['comments'])
    public_track=client.get('/api/track/'+token)
    assert 'Внутренняя служебная заметка' not in public_track.text
    assert not any(h['note']=='Внутренняя заметка' for h in public_track.json()['history'])
    assert any(h['note']=='Внутренняя заметка' for h in internal.json()['history'])
    assert client.post('/api/staff/tickets/999/comments',json={'body':'Нет такой заявки'}).status_code==404

def test_ticket_priority_is_preserved_and_danger_wins(client):
    made,_=create(client,title='Не работает проектор',description='Проектор не включается',priority='Высокий')
    login(client,'staff')
    ticket=client.get('/api/staff/tickets?query=проектор').json()[0]
    assert ticket['priority']=='Высокий'
    danger,_=create(client,title='Искрит розетка',description='В розетке искрит',priority='Обычный',idempotency_key=secrets.token_hex(20))
    urgent=client.get('/api/staff/tickets?query=искрит').json()[0]
    assert urgent['priority']=='Срочный'
    invalid=client.post('/api/tickets',data=dict(title='Проверка',description='Проверка приоритета',category_id=ticket['category_id'],location_id=ticket['location_id'],idempotency_key=secrets.token_hex(20),priority='Критический'))
    assert invalid.status_code==400

def test_stats_daily_and_quick_filters(client):
    made,_=create(client)
    login(client,'staff')
    stats=client.get('/api/staff/stats').json()
    assert len(stats['daily'])==14
    assert stats['attention']>=1 and stats['unassigned']==1
    assert client.get('/api/staff/tickets?attention=1').json()
    assert len(client.get('/api/staff/tickets?unassigned=1').json())==1
    ticket=client.get('/api/staff/tickets?query=проектор').json()[0]
    working=client.patch(f'/api/staff/tickets/{ticket["id"]}',json=dict(status='В работе',assignee_id=2,category_id=ticket['category_id'],priority='Обычный',comment='',visibility='public',expected_updated_at=ticket['updated_at']))
    assert working.status_code==200,working.text
    assert len(client.get('/api/staff/tickets?mine=1').json())==1
    assert client.get('/api/staff/tickets?unassigned=1').json()==[]

def test_system_prompt_can_be_edited(client):
    login(client)
    saved=client.put('/api/admin/settings',json={'public_url':'https://college.example.org','system_prompt':'Кастомный системный промпт'})
    assert saved.status_code==200,saved.text
    assert client.get('/api/admin/settings').json()['system_prompt']=='Кастомный системный промпт'
    assert client.put('/api/admin/settings',json={'public_url':'https://college.example.org','system_prompt':'   '}).status_code==400
