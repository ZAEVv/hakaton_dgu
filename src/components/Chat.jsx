import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, ArrowRight, Check, ChevronDown, ClipboardList, Copy, MapPin, MessageCircle, Monitor, Paperclip, Send, ShieldCheck, Sparkles, X, RefreshCw, BookOpen, Menu } from 'lucide-react';
import { api, date, friendlyError, savedTickets, saveTicket, requestId } from '../api';
import { Icon, ThemeMenu, Spinner, ErrorBox, Modal, RoomSelect, Status, Empty, PageHeading } from './UI';
const greeting='Здравствуйте! Я помощник УПК. Подскажу, как пользоваться оборудованием, или помогу сообщить о проблеме. Что случилось?';
const quicks=[{text:'Не работает проектор',icon:Monitor,hint:'Оформить обращение'},{text:'Как подключить ноутбук к проектору?',icon:BookOpen,hint:'Получить инструкцию'},{text:'В кабинете грязно',icon:Sparkles,hint:'Сообщить о проблеме'}];
export function Chat({bootstrap,navigate,theme,setTheme,qrMode,onMenu}){
 const [room,setRoom]=useState(bootstrap.selected_location_id||'');
 const [roomModal,setRoomModal]=useState(false);
 const [messages,setMessages]=useState([]);
 const [text,setText]=useState('');
 const [busy,setBusy]=useState(false);
 const [sendingTicket,setSendingTicket]=useState(false);
 const [ticketCreated,setTicketCreated]=useState(null);
 const [error,setError]=useState('');
 const [photo,setPhoto]=useState(null);
 const [preview,setPreview]=useState('');
 const bottom=useRef(null);
 const input=useRef(null);
 const composing=useRef(false);
 const loc=bootstrap.locations.find(l=>l.id===Number(room));
 const lastAssistantIndex=[...messages].map((m,i)=>m.role==='assistant'?i:-1).filter(i=>i>=0).at(-1);
 useEffect(()=>{if(!photo){setPreview('');return;}const url=URL.createObjectURL(photo);setPreview(url);return()=>URL.revokeObjectURL(url);},[photo]);
 useEffect(()=>{if(messages.length||busy||sendingTicket)bottom.current?.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'nearest'});},[messages,busy,sendingTicket]);
 useEffect(()=>{const warn=e=>{if(text.trim()||photo){e.preventDefault();e.returnValue='';}};window.addEventListener('beforeunload',warn);return()=>window.removeEventListener('beforeunload',warn);},[text,photo]);
 function attach(e){const file=e.target.files[0];e.target.value='';if(!file)return;if(!['image/jpeg','image/png','image/webp'].includes(file.type)||file.size>8*1024*1024){setError('Выберите фото JPEG, PNG или WebP размером до 8 МБ.');return;}setError('');setPhoto(file);}
 function ticketLocation(result){
  return bootstrap.locations.find(l=>l.id===Number(room))||bootstrap.locations.find(l=>result?.location?.room!=null&&String(l.room)===String(result.location.room));
 }
 async function submitTicket(result,base=messages){
  if(sendingTicket||ticketCreated)return;
  const location=ticketLocation(result);
  if(!location){setError('Уточните кабинет — без него заявку нельзя отправить.');return;}
  const category=bootstrap.categories.find(c=>c.name===result?.category)||bootstrap.categories.find(c=>c.name==='Другое')||bootstrap.categories[0];
  if(!category){setError('Справочник категорий не загружен. Обновите страницу.');return;}
  setSendingTicket(true);setError('');
  try{
   const data=new FormData();
   data.append('title',result?.title||'Обращение в УПК');
   data.append('description',result?.description||result?.summary||'Проблема в кабинете');
   data.append('category_id',category.id);
   data.append('location_id',location.id);
   data.append('priority',result?.priority||'Обычный');
   data.append('idempotency_key',result?._draftKey||requestId());
   if(photo)data.append('photo',photo);
   const ticket=await api('/tickets',{method:'POST',body:data});
   saveTicket({...ticket,title:result?.title||'Обращение в УПК',created_at:new Date().toISOString()});
   setTicketCreated(ticket);setPhoto(null);
   setMessages([...base,{role:'assistant',content:`Готово. Заявка ${ticket.number} отправлена сотруднику УПК. Кабинет ${location.room}, ${location.floor} этаж, категория «${category.name}». Следить за статусом и ответить сотруднику можно в обращении.`,result:{kind:'ticket',ticket,title:result?.title,room:location.room,floor:location.floor,category:category.name},time:new Date().toISOString()}]);
  }catch(e){setError(friendlyError(e));}
  finally{setSendingTicket(false);}
 }
 function lastOffer(){const last=[...messages].reverse().find(m=>m.role==='assistant');return last?.result?.suggestTicket&&last.result.ready&&!ticketCreated?last:undefined;}
 async function send(value=text,roomOverride=null){
  if(busy||sendingTicket||!value.trim())return;
  const sent=value.trim();
  const roomId=roomOverride??room;
  const offer=lastOffer();
  if(!roomOverride&&offer&&/^(?:да|ок|хорошо|отправляй|отправьте|отправить|подтверждаю)[.! ]*$/i.test(sent)){
   setText('');setError('');
   const next=[...messages,{role:'user',content:sent,time:new Date().toISOString()}];
   setMessages(next);
   await submitTicket(offer.result,next);
   input.current?.focus();
   return;
  }
  setText('');setError('');
  const next=[...messages,{role:'user',content:sent,time:new Date().toISOString()}];
  setMessages(next);setBusy(true);
  try{
   const result=await api('/assistant',{method:'POST',body:{text:sent,location_id:roomId?Number(roomId):null,history:messages.slice(-8).map(m=>({role:m.role,content:m.content}))}});
   const enriched=result.suggestTicket?{...result,_draftKey:requestId()}:result;
   setMessages([...next,{role:'assistant',content:enriched.answer,result:enriched,time:new Date().toISOString()}]);
  }catch(e){setError(friendlyError(e));setText(sent);}
  finally{setBusy(false);input.current?.focus();}
 }
 function chooseRoom(id){
  const selected=bootstrap.locations.find(l=>l.id===Number(id));
  setRoom(String(id));
  send(selected?`Кабинет ${selected.room}`:'Кабинет выбран',id);
 }
 function followups(result){
  const questions=Array.isArray(result?.questions)?result.questions:[];
  if(!questions.length)return null;
  return <div className="followups">{questions.map((q,index)=>q.id==='room'?<RoomAnswer key={index} locations={bootstrap.locations} room={room} busy={busy} onChoose={chooseRoom}/>:q.options?.length?<div className="followup-options" key={index}><p>{q.text}</p><div>{q.options.map(option=><button type="button" key={option} onClick={()=>send(option)} disabled={busy||sendingTicket}>{option}</button>)}</div></div>:null)}</div>;
 }
 function ticketOffer(result){
  if(!result?.suggestTicket||!result?.ready||ticketCreated)return null;
  const location=ticketLocation(result);
  return <div className="ticket-offer"><span>Принял проблему</span><strong>{result.title}</strong><p>{result.summary&&result.summary!==result.title?result.summary:result.description}</p><div className="ticket-offer-meta"><span>{result.category}</span><span>{result.priority} приоритет</span><span>{location?`кабинет ${location.room}`:'кабинет не указан'}</span>{photo&&<span>фото приложено</span>}</div><div className="ticket-offer-actions"><button className="btn primary" disabled={sendingTicket} onClick={()=>submitTicket(result)}>{sendingTicket?<Spinner/>:<Icon as={Send} size={17}/>}Отправить сотруднику</button><button className="btn secondary" disabled={sendingTicket} onClick={()=>input.current?.focus()}>Добавить уточнение</button></div><small className="ticket-offer-hint">Можно также написать «да» в чат — отправлю заявку.</small></div>;
 }
 return <div className={`chat-page ${messages.length?'has-messages':''}`}>
  <div className="chat-grid"><section className="chat-card" aria-label="Диалог с помощником"><div className="chat-head"><button className="icon-btn messenger-mobile" aria-label="Открыть меню" onClick={onMenu}><Icon as={Menu}/></button><div className="assistant-avatar"><Icon as={MessageCircle} size={24}/></div><div className="chat-identity"><h2>Помощник УПК</h2><p>Подсказки и обращения</p></div><button className="chat-room" onClick={()=>setRoomModal(true)} aria-label="Выбрать кабинет"><Icon as={MapPin} size={17}/><span>{loc?loc.room:'Кабинет'}</span><span className="chat-room-floor">{loc?`${loc.floor} этаж`:''}</span><Icon as={ChevronDown} size={15}/></button><ThemeMenu theme={theme} onChange={setTheme}/></div>
  {bootstrap.invalid_qr&&<div className="inline-notice">Этот QR-код не найден. Выберите кабинет вручную.</div>}
  {qrMode&&loc&&<div className="qr-location"><Icon as={MapPin} size={15}/>{loc.building}, кабинет {loc.room}<Icon as={ShieldCheck} size={15}/></div>}
  <div className="messages" role="log" aria-label="Сообщения" aria-live="polite" aria-relevant="additions"><div className="chat-date">Сегодня</div><div className="message assistant"><div className="bubble"><strong className="bubble-author">Помощник УПК</strong><p>{loc?`Здравствуйте! Что случилось в кабинете ${loc.room}?`:greeting}</p><span className="message-time">Помощник УПК</span></div></div>
   {!messages.length&&<div className="conversation-starters"><p>Можно начать с этого</p>{quicks.map(q=><button key={q.text} onClick={()=>send(q.text)}><span className="starter-icon"><Icon as={q.icon}/></span><span><strong>{q.text}</strong><small>{q.hint}</small></span><Icon as={ArrowRight} size={18}/></button>)}</div>}
   {messages.map((m,i)=><div className={`message ${m.role} ${m.result?.kind==='danger'?'danger-message':''}`} key={i}><div className="bubble">{m.role==='assistant'&&<strong className="bubble-author">Помощник УПК</strong>}{m.result?.kind==='danger'&&<strong className="danger-label">Возможна опасность</strong>}<p>{m.content}</p>{m.result?.source&&<span className="source"><Icon as={BookOpen} size={13}/>{m.result.source}</span>}{m.result?.notice&&<span className="fallback-note">{m.result.notice}</span>}{m.role==='assistant'&&i===lastAssistantIndex&&followups(m.result)}{m.role==='assistant'&&i===lastAssistantIndex&&ticketOffer(m.result)}{m.result?.kind==='ticket'&&<div className="ticket-created-actions"><button className="btn primary" onClick={()=>navigate('/track/'+m.result.ticket.token)}>Открыть обращение<Icon as={ArrowRight} size={17}/></button></div>}<span className="message-time">{new Intl.DateTimeFormat('ru-RU',{hour:'2-digit',minute:'2-digit'}).format(new Date(m.time))}</span></div></div>)}
   {busy&&<div className="message assistant"><div className="bubble typing"><Spinner/><span>Помощник готовит ответ…</span></div></div>}{sendingTicket&&<div className="message assistant"><div className="bubble typing"><Spinner/><span>Отправляю заявку сотруднику…</span></div></div>}<div ref={bottom}/>
  </div>
  <div className="composer-area"><ErrorBox>{error}</ErrorBox>{preview&&<div className="attachment-preview"><img src={preview} alt="Выбранная фотография" width="56" height="56"/><div><strong>Фото для заявки</strong><small>Будет приложено к обращению</small></div><button className="icon-btn" aria-label="Удалить фото" onClick={()=>setPhoto(null)}><Icon as={X} size={18}/></button></div>}
  <form className="composer" onSubmit={e=>{e.preventDefault();send();}}><label className="icon-btn attach-button" title="Прикрепить фото"><Icon as={Paperclip} size={23}/><span className="sr-only">Прикрепить фото</span><input type="file" accept="image/jpeg,image/png,image/webp" onChange={attach}/></label><textarea ref={input} name="message" aria-label="Сообщение помощнику" placeholder="Напишите, что случилось…" value={text} maxLength={4000} rows={1} onChange={e=>setText(e.target.value)} onCompositionStart={()=>composing.current=true} onCompositionEnd={()=>composing.current=false} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!composing.current){e.preventDefault();send();}}}/><button className="send-button" aria-label="Отправить сообщение" disabled={busy||sendingTicket||!text.trim()}>{busy||sendingTicket?<Spinner/>:<Icon as={Send} size={21}/>}</button></form><div className="composer-note"><span><Icon as={ShieldCheck} size={13}/>Помощник сам классифицирует проблему. Заявка уйдёт только после вашего подтверждения.</span></div></div>
  </section></div>
  {roomModal&&<Modal title="Где нужна помощь?" onClose={()=>setRoomModal(false)}><RoomSelect locations={bootstrap.locations} value={room} onChange={setRoom}/><button className="btn primary full" onClick={()=>setRoomModal(false)}>Сохранить кабинет</button></Modal>}
 </div>;
}
function RoomAnswer({locations,room,busy,onChoose}){const [value,setValue]=useState(room||'');return <div className="room-answer"><p>Уточните кабинет — помощник укажет его в заявке для сотрудника.</p><RoomSelect locations={locations} value={value} onChange={setValue} id="followup-room"/><button type="button" className="btn primary full" disabled={!value||busy} onClick={()=>onChoose(value)}>Указать кабинет</button></div>;}
export function MyTickets({navigate}){const [tickets,setTickets]=useState(savedTickets);return <div className="content"><PageHeading eyebrow="На этом устройстве" title="Мои обращения" text="Здесь сохранены ваши безопасные ссылки. Ссылки дают доступ к заявкам — храните их у себя."/>{tickets.length?<div className="my-ticket-list">{tickets.map(t=><a key={t.token} href={'/track/'+t.token} onClick={e=>{e.preventDefault();navigate('/track/'+t.token);}}><div className="ticket-list-icon"><Icon as={ClipboardList}/></div><div><span className="ticket-number">{t.number}</span><h2>{t.title}</h2><p>{date(t.created_at)}</p></div><Icon as={ArrowRight}/></a>)}</div>:<Empty icon={ClipboardList} title="Здесь появятся ваши обращения" text="Опишите проблему помощнику и подтвердите отправку. Ссылка на заявку сохранится на этом устройстве."><button className="btn primary" onClick={()=>navigate('/')}>Написать помощнику</button></Empty>}</div>;}
export function Track({token}){const [ticket,setTicket]=useState(null);const [error,setError]=useState('');const [comment,setComment]=useState('');const [busy,setBusy]=useState(false);const [copied,setCopied]=useState(false);const [notice,setNotice]=useState('');async function load(){try{setTicket(await api('/track/'+token));setError('');}catch(e){setError(friendlyError(e));}}useEffect(()=>{load();const timer=setInterval(()=>{if(!document.hidden)load();},15000);return()=>clearInterval(timer);},[token]);async function reply(e){e.preventDefault();setBusy(true);try{await api('/track/'+token+'/comments',{method:'POST',body:{body:comment}});setComment('');setNotice('Комментарий отправлен');await load();}catch(e){setError(friendlyError(e));}finally{setBusy(false);}}
 async function copy(){try{await navigator.clipboard.writeText(location.href);setCopied(true);setTimeout(()=>setCopied(false),2500);}catch{setError('Не удалось скопировать. Сохраните адрес страницы из адресной строки.');}}
 return <div className="content track-page"><a href="/my" className="back-link"><Icon as={ArrowLeft} size={17}/>Мои обращения</a><ErrorBox>{error}</ErrorBox>{!ticket?!error&&<div className="screen-loader"><Spinner/>Загружаем обращение…</div>:<><PageHeading eyebrow={ticket.public_number} title={ticket.title} text={`Кабинет ${ticket.room} · ${ticket.floor} этаж · ${date(ticket.created_at)}`}><button className="btn secondary" onClick={copy}><Icon as={copied?Check:Copy} size={17}/>{copied?'Ссылка скопирована':'Сохранить ссылку'}</button><button className="icon-btn" aria-label="Обновить статус" onClick={load}><Icon as={RefreshCw}/></button></PageHeading><div className="tracking-grid"><div><div className="surface ticket-summary"><div className="summary-top"><Status value={ticket.status}/><span className={`priority ${ticket.priority==='Срочный'?'urgent':''}`}>{ticket.priority} приоритет</span></div><p className="user-text">{ticket.description}</p><dl className="ticket-meta"><div><dt>Категория</dt><dd>{ticket.category}</dd></div><div><dt>Место</dt><dd>{ticket.building}, {ticket.room}</dd></div><div><dt>Исполнитель</dt><dd>{ticket.assignee||'Ещё не назначен'}</dd></div></dl>{ticket.attachments.map(a=><a className="photo-link" key={a.id} href={`/api/track/${token}/attachments/${a.id}`} target="_blank" rel="noreferrer"><img src={`/api/track/${token}/attachments/${a.id}`} width="300" height="200" alt="Фотография из обращения" loading="lazy"/></a>)}</div><section className="surface comments-section"><h2>Диалог по заявке</h2>{!ticket.comments.length?<p className="muted">Здесь появятся ответы сотрудника. Вы можете добавить уточнение.</p>:ticket.comments.map(c=><article className="comment" key={c.id}><div><strong>{c.author}</strong><time>{date(c.created_at)}</time></div><p>{c.body}</p></article>)}<form onSubmit={reply} className="stack-form"><label className="field">Ваш комментарий<textarea name="comment" placeholder="Добавьте подробности или задайте вопрос…" value={comment} onChange={e=>setComment(e.target.value)} maxLength={4000} rows={3} required/></label><div className="form-actions"><span className="muted" role="status">{notice}</span><button className="btn primary" disabled={busy||!comment.trim()}>{busy?<Spinner/>:<Icon as={Send} size={17}/>}Отправить</button></div></form></section></div><aside className="surface history-panel"><h2>История обращения</h2><ol className="timeline">{ticket.history.map((h,i)=><li key={h.id}><span className={`timeline-dot ${i===ticket.history.length-1?'latest':''}`}/><strong>{h.new_status||h.note}</strong><p>{h.author}</p><time>{date(h.created_at)}</time></li>)}</ol><div className="private-note"><Icon as={ShieldCheck} size={18}/><p>Доступ к обращению есть только у вас по этой ссылке и у сотрудников УПК.</p></div></aside></div></>}</div>;
}
