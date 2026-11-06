import json
import os
import re
import httpx
from .db import SEED

DANGER = re.compile(r'искр|дым|задым|гар[ьи]|(?<!не\s)горит|пожар|огол[её]н|током|замен\S*\s+проводк|ремонт\S*\s+(?:проводк|розетк)|вскры\S*\s+(?:блок|прибор)|обойти\s+защит',re.I)
DANGER_ANSWER='Отойдите на безопасное расстояние, не трогайте оборудование и не пытайтесь ремонтировать его. Предупредите находящихся рядом и немедленно сообщите ответственному сотруднику колледжа. При непосредственной угрозе жизни обратитесь в экстренную службу по местным правилам. Заявка не заменяет срочное оповещение.'
ROOM_QUESTION=dict(id='room',text='В каком кабинете нужна помощь?',options=[])
DETAIL_OPTIONS={
    'Оборудование':['Не включается','Не реагирует','Повреждён кабель','Появляется ошибка'],
    'Интернет и связь':['Нет подключения','Не работает Wi-Fi','Медленная скорость'],
    'Электрика и освещение':['Не горит свет','Искрит розетка','Повреждён провод'],
    'Мебель и имущество':['Сломана ручка','Повреждена дверь','Шатается мебель'],
    'Чистота':['Нужна уборка','Мусор','Загрязнение'],
}

def category_for(text):
    for pattern,category in [(r'интернет|wi.?fi|вай.?фай|сет[ьи]','Интернет и связь'),(r'розетк|свет|ламп|провод|освещ','Электрика и освещение'),(r'ручк|окн|стул|стол|двер|мебел','Мебель и имущество'),(r'гряз|уборк|мусор|чистот','Чистота'),(r'проектор|компьютер|принтер|ноутбук|монитор','Оборудование')]:
        if re.search(pattern,text,re.I): return category
    return 'Другое'

def _clean(value,limit):
    if not isinstance(value,str): return ''
    return re.sub(r'\s+',' ',value).strip()[:limit]

def _user_turns(text,history):
    values=[]
    for message in list(history or [])[-10:]:
        if isinstance(message,dict) and message.get('role')=='user':
            content=_clean(message.get('content'),4000)
            if content: values.append(content)
    content=_clean(text,4000)
    if content: values.append(content)
    unique=[]
    for value in values:
        if value not in unique: unique.append(value)
    return unique[-8:]

def _is_room_only(value):
    return bool(re.fullmatch(r'(?i)(?:в\s+)?кабинет\w*\s+\d{1,4}[.!]?|\d{3}',value.strip()))

def _informative_turns(text,history):
    ignored=re.compile(r'(?i)^(?:спасибо|ок|хорошо|да|нет|здравствуйте|привет|помогите|у меня проблема|что-то случилось)[.! ]*$')
    context_question=re.compile(r'(?i)^(?:а\s+)?(?:в\s+каком|какой)\s+(?:я\s+)?кабинет')
    return [value for value in _user_turns(text,history) if not _is_room_only(value) and not ignored.fullmatch(value) and not context_question.match(value)]

def _problem_draft(text,history):
    turns=_informative_turns(text,history)
    if not turns: return 'Обращение в УПК','Пользователь сообщил о проблеме в колледже.'
    title=''
    for value in reversed(turns):
        candidate=re.sub(r'(?i)^(?:здравствуйте|привет|подскажите|пожалуйста|извините)[,.! ]*','',value).strip()
        candidate=re.sub(r'(?i)^(?:в\s+)?кабинет\w*\s+\d{1,4}[,.:;\- ]*','',candidate).strip()
        if len(candidate)>=3:
            title=candidate
            break
    if not title: title=turns[-1]
    title=title[0].upper()+title[1:] if title else 'Обращение в УПК'
    description='. '.join(value.rstrip('.!?') for value in turns)
    if description and description[-1] not in '.!?': description+='.'
    return title[:100],description[:4000]

def _needs_details(text,history,category,kind):
    if kind=='unclear': return True
    if kind in ('danger','question'): return False
    if category=='Чистота': return False
    joined=' '.join(_informative_turns(text,history))
    core=re.sub(r'(?i)\b(?:в\s+)?кабинет\w*\s+\d{1,4}\b',' ',joined)
    core=re.sub(r'(?i)\b(?:не работает|не работают|сломал\w*|сломалось|не включается|не включаются|не печатает|не горит|поврежд\w*|не реагирует)\b',' ',core)
    core=re.sub(r'[^0-9A-Za-zА-Яа-яЁё]+',' ',core).strip()
    return len(core)<4

def _detail_question(category):
    text={
        'Оборудование':'Что именно не работает и что вы видите? Например: не включается, не реагирует или повреждён кабель.',
        'Интернет и связь':'Что именно с подключением: нет сети, не открываются сайты или не работает Wi-Fi?',
        'Электрика и освещение':'Что именно происходит: не горит свет, искрит розетка или повреждён провод?',
        'Мебель и имущество':'Что именно повреждено и где это находится в кабинете?',
        'Чистота':'Что нужно убрать и где именно в кабинете?',
    }.get(category,'Уточните, пожалуйста, что именно произошло и с каким оборудованием или предметом.')
    return dict(id='details',text=text,options=DETAIL_OPTIONS.get(category,[]))

def _clean_options(raw):
    if not isinstance(raw,list): return []
    result=[]
    for value in raw[:4]:
        text=_clean(value,80)
        if text and text not in result: result.append(text)
    return result

def _is_question(text):
    return bool(re.search(r'\?|^\s*(?:кто|где|почему|сколько|зачем|какой|какая|какое|как|когда)\b',text,re.I))

def _question_like_unknown(text):
    return _is_question(text)

def _model_questions(result):
    raw=result.get('questions')
    if not isinstance(raw,list): return []
    questions=[]
    for item in raw[:3]:
        if isinstance(item,str):
            text=_clean(item,240); options=[]
        elif isinstance(item,dict):
            text=_clean(item.get('text') or item.get('question'),240); options=_clean_options(item.get('options'))
        else: continue
        if text:
            questions.append(dict(id='details',text=text,options=options))
    return questions

def _draft_from_model(result,text,history,categories,local):
    title=_clean(result.get('title'),100)
    description=_clean(result.get('description'),4000)
    if len(title)<3 or len(description)<5:
        local_title,local_description=_problem_draft(text,history)
        title=title if len(title)>=3 else local_title
        description=description if len(description)>=5 else local_description
    category=result.get('category') if result.get('category') in categories else local['category']
    priority=result.get('priority') if result.get('priority') in ['Обычный','Высокий','Срочный'] else local['priority']
    return title,description,category,priority

def _finalize(result,text,history,location):
    kind=result.get('kind','unknown')
    local_title,local_description=_problem_draft(text,history)
    result['title']=_clean(result.get('title'),100) or local_title
    result['description']=_clean(result.get('description'),4000) or local_description
    if len(result['title'])<3: result['title']=local_title
    if len(result['description'])<5: result['description']=local_description
    result['category']=result.get('category') or category_for(text)
    result['priority']=result.get('priority') if result.get('priority') in ['Обычный','Высокий','Срочный'] else 'Обычный'
    result['confidence']=result.get('confidence') if isinstance(result.get('confidence'),(int,float)) and 0<=result['confidence']<=1 else .4
    result.setdefault('knowledgeId',None)
    result.setdefault('source',None)
    result.setdefault('notice',None)
    if kind in ('fault','danger'): result['suggestTicket']=True
    if kind=='unknown' and _question_like_unknown(text): result['suggestTicket']=False
    result['suggestTicket']=bool(result.get('suggestTicket'))
    if kind=='danger': result['priority']='Срочный'

    needs_context=result['suggestTicket'] or kind in ('fault','danger','unclear')
    questions=[];missing=[]
    if needs_context and not location:
        missing.append('location')
        questions.append(dict(ROOM_QUESTION))
    if needs_context and _needs_details(text,history,result['category'],kind):
        missing.append('details')
        question=_detail_question(result['category'])
        model_questions=_model_questions(result)
        for candidate in model_questions:
            if candidate['text']:
                question=dict(id='details',text=candidate['text'],options=candidate['options'] or question['options'])
                break
        questions.append(question)
    result['questions']=questions
    result['missing']=missing
    result['ready']=bool(location) and kind in ('fault','danger','unknown') and not missing and len(result['description'])>=12

    summary=_clean(result.get('summary'),240) or result['title']
    if result['ready'] and kind in ('fault','unknown') and re.search(r'уточн',summary,re.I):
        summary=result['title']
    if location:
        if str(location['room']) not in summary:
            summary=f"Кабинет {location['room']}: {summary}"
        result['location']=dict(room=location['room'],floor=location['floor'],building=location['building'])
    else:
        result.pop('location',None)
        if result['suggestTicket']: summary+=' Кабинет не указан.'
    result['summary']=summary

    answer=_clean(result.get('answer'),1200) or 'Уточните, пожалуйста, что произошло.'
    if result['ready'] and kind=='fault':
        answer=f"Принял проблему. Кабинет {location['room']}, {location['floor']} этаж. Проверьте карточку ниже и отправьте заявку сотруднику — он сможет ответить вам здесь же. Не используйте повреждённое оборудование до прихода сотрудника."
    elif result['ready'] and kind=='unknown':
        answer=f"Принял проблему. Кабинет {location['room']}, {location['floor']} этаж. Проверьте карточку ниже и отправьте заявку сотруднику — он сможет ответить вам здесь же."
    elif result['ready'] and kind=='danger':
        answer=DANGER_ANSWER+f" Для заявки: кабинет {location['room']}, {location['floor']} этаж. Отправьте заявку сотруднику после срочного оповещения."
    if 'location' in missing and not re.search(r'в каком (?:вы )?кабинете|укажите кабинет|выберите кабинет',answer,re.I):
        answer+=' Уточните, пожалуйста, в каком вы кабинете — это нужно для заявки.'
    if 'details' in missing and not re.search(r'уточн|что именно|опишите|что происходит',answer,re.I):
        answer+=' '+questions[-1]['text']
    result['answer']=answer
    return result

def fallback(text,knowledge):
    category=category_for(text)
    title,description=_problem_draft(text,[])
    base=dict(category=category,title=title,description=description,priority='Обычный',confidence=.9,knowledgeId=None,suggestTicket=False,source=None,summary=title,questions=[],missing=[],ready=False)
    if DANGER.search(text): return dict(base,kind='danger',answer=DANGER_ANSWER,priority='Срочный',suggestTicket=True,source='Правила безопасности УПК')
    if re.search(r'не работает|сломан|сломал|не включ|не печата|не горит|грязно|поврежд|отвал|протеч|теч[её]т|застрял|нет интернет',text,re.I): return dict(base,kind='fault',answer='Похоже, нужна помощь сотрудника. Подготовлю заявку: проверьте кабинет и описание, при необходимости добавьте фото. Не используйте повреждённое оборудование.',suggestTicket=True)
    kid=None
    for pattern,key in [(r'парол|wi.?fi|вай.?фай','wifi'),(r'когда|срок','timing'),(r'статус|отслед|проверить заяв','tracking'),(r'категори','category'),(r'как.*(?:проектор|hdmi)|подключ.*проектор','projector'),(r'принтер|печат','printer'),(r'как.*(?:сообщить|заявк|обращени)','report'),(r'повреждени.*(?:окн|мебел)|что делать.*(?:окн|мебел)','damage')]:
        if re.search(pattern,text,re.I): kid=key; break
    k=next((k for k in knowledge if k['id']==kid),None)
    if k: return dict(base,kind='question',answer=k['answer'],knowledgeId=k['id'],category=k['category'],source=k['source'])
    if (len(text.strip())<25 and not re.search(r'\?|^(кто|где|почему|сколько|зачем|какой|какая|как|когда)\b',text.strip(),re.I)) or re.search(r'у меня проблема|помогите|что-то случилось',text,re.I): return dict(base,kind='unclear',confidence=.4,answer='Расскажите, что именно произошло: какое оборудование или предмет, что с ним не так и в каком кабинете?')
    return dict(base,kind='unknown',confidence=.3,answer='В базе знаний нет проверенного ответа на этот вопрос. Я не буду придумывать сведения. Если нужна помощь в помещении колледжа, опишите проблему и оформите заявку для сотрудника.',suggestTicket=not _question_like_unknown(text))

async def analyze(text,history,location,knowledge,categories,client=None,system_prompt=None):
    local=fallback(text,knowledge)
    if local['kind']=='danger':
        return _finalize(dict(local,provider='safety'),text,history,location)
    # The QR is the authority for room context, even when the model is unavailable.
    if re.search(r'в каком (?:я )?кабинете|где я(?:\s|[?!.,]|$)|какой (?:у меня|мой) кабинет|номер (?:моего|этого) кабинета|какой кабинет определ',text,re.I):
        answer=(f"По QR-коду выбран кабинет {location['room']}, {location['floor']} этаж, {location['building']}. Это место будет указано в вашей заявке." if location else 'Кабинет пока не выбран. Отсканируйте QR-код в кабинете или выберите место кнопкой вверху чата.')
        return _finalize(dict(local,kind='question' if location else 'unclear',answer=answer,confidence=1 if location else .4,suggestTicket=False,source='Место обращения' if location else None,provider='context'),text,history,location)
    if location and local['kind']=='unclear':
        local['answer']=f"Кабинет {location['room']} уже выбран. Расскажите, что именно произошло: какое оборудование или предмет и что с ним не так?"
    key=os.getenv('DEEPSEEK_API_KEY')
    if not key: return _finalize(dict(local,provider='knowledge'),text,history,location)
    context=json.dumps(dict(location=location,categories=categories,knowledge=knowledge),ensure_ascii=False)
    messages=[dict(role='system',content=(system_prompt or SEED['system_prompt'])+'\nserverContext='+context)]
    messages.extend(dict(role=m['role'],content=m['content'][:3000]) for m in history[-8:] if m.get('role') in ['user','assistant'])
    messages.append(dict(role='user',content=text))
    owned=client is None
    if owned: client=httpx.AsyncClient(timeout=22)
    try:
        response=await client.post('https://api.deepseek.com/chat/completions',headers={'Authorization':f'Bearer {key}'},json={'model':os.getenv('DEEPSEEK_MODEL','deepseek-flash'),'messages':messages,'response_format':{'type':'json_object'},'max_tokens':1600,'temperature':.2})
        response.raise_for_status()
        result=json.loads(response.json()['choices'][0]['message']['content'].strip())
        if result.get('kind') not in ['question','fault','danger','unclear','unknown'] or not isinstance(result.get('answer'),str) or not result['answer'].strip() or not isinstance(result.get('confidence'),(int,float)) or not 0<=result['confidence']<=1: raise ValueError('invalid response')
        k=next((k for k in knowledge if k['id']==result.get('knowledgeId')),None)
        if result['kind']=='question' and not k: return _finalize(dict(local,provider='fallback',notice='Ответ модели не подтверждён базой знаний. Использован локальный ответ.'),text,history,location)
        if result['kind']=='danger':
            return _finalize(dict(local,kind='danger',answer=DANGER_ANSWER,priority='Срочный',suggestTicket=True,provider='deepseek',source='Правила безопасности УПК'),text,history,location)
        kind='fault' if local['kind']=='fault' else result['kind']
        # Ответы на вопросы берутся из проверенной инструкции, а не сочиняются моделью.
        if k and kind=='question': answer=k['answer']
        elif kind=='fault': answer='Похоже, нужна помощь сотрудника. Подготовлю заявку: проверьте кабинет и описание, при необходимости добавьте фото. Не используйте повреждённое оборудование.'
        elif kind=='unknown': answer='В базе знаний нет проверенного ответа. Обратитесь к ответственному сотруднику: я не могу подтвердить эти сведения.'
        else: answer='Уточните, что именно произошло и с каким оборудованием или предметом. Недостаточно данных для уверенного ответа.'
        title,description,category,priority=_draft_from_model(result,text,history,categories,local)
        return _finalize(dict(local,kind=kind,answer=answer,knowledgeId=k['id'] if k and kind=='question' else None,source=k['source'] if k and kind=='question' else None,category=category,title=title,description=description,priority=priority,confidence=result['confidence'],suggestTicket=kind in ['fault','danger','unknown'],summary=result.get('summary'),questions=result.get('questions'),provider='deepseek'),text,history,location)
    except (httpx.HTTPError,ValueError,KeyError,IndexError,TypeError):
        return _finalize(dict(local,provider='fallback',notice='DeepSeek временно недоступен. Ответ подготовлен по локальной базе знаний.'),text,history,location)
    finally:
        if owned: await client.aclose()
