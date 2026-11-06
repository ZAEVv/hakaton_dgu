import React, { lazy, Suspense, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { MessageCircle, ClipboardList, BookOpen, ShieldCheck, Menu, X, Search } from 'lucide-react';
import { api, friendlyError, savedTickets } from './api';
import { Brand, Icon, ThemePicker, ThemeMenu, Spinner, ErrorBox, PageHeading } from './components/UI';
import { Chat, MyTickets, Track } from './components/Chat';
import './styles.css';
import './messenger.css';
const Admin=lazy(()=>import('./components/Admin'));
function App(){
 const [route,setRoute]=useState(()=>({path:location.pathname,search:location.search}));
 const {path,search}=route;
 const [bootstrap,setBootstrap]=useState(null),[error,setError]=useState(''),[menu,setMenu]=useState(false),[query,setQuery]=useState('');
 const [theme,setTheme]=useState(()=>{try{return localStorage.getItem('upk-theme-v1')==='night'||localStorage.getItem('upk-messenger-theme')==='dark'?'night':'garden';}catch{return 'garden';}});
 useEffect(()=>{document.documentElement.dataset.theme=theme;try{localStorage.setItem('upk-theme-v1',theme);localStorage.setItem('upk-messenger-theme',theme==='night'?'dark':'green');}catch{}},[theme]);
 useEffect(()=>{const pop=()=>{setRoute({path:location.pathname,search:location.search});setMenu(false);};window.addEventListener('popstate',pop);return()=>window.removeEventListener('popstate',pop);},[]);
 useEffect(()=>{let cancelled=false;setBootstrap(null);setError('');api('/bootstrap'+search).then(b=>{if(!cancelled)setBootstrap(b);}).catch(e=>{if(!cancelled)setError(friendlyError(e));});return()=>{cancelled=true;};},[search]);
 function navigate(to){history.pushState(null,'',to);setRoute({path:location.pathname,search:location.search});setMenu(false);window.scrollTo(0,0);}
 const nav=[['/','Помощник УПК','Подсказки и новые заявки',MessageCircle],['/my','Мои обращения','История на этом устройстве',ClipboardList],['/knowledge','База знаний','Инструкции по оборудованию',BookOpen]];
 if(path.startsWith('/admin'))return <Suspense fallback={<div className="screen-loader"><Spinner/> Открываем панель…</div>}><Admin theme={theme} setTheme={setTheme} bootstrap={bootstrap} refreshBootstrap={()=>api('/bootstrap').then(setBootstrap)}/></Suspense>;
 const inChat=path==='/'||path==='/chat';
 const tickets=savedTickets().filter(t=>(t.title+' '+t.number).toLocaleLowerCase('ru').includes(query.toLocaleLowerCase('ru')));
 return <div className="messenger-layout">
  <a href="#main" className="skip-link">К содержимому</a>
  <aside className={`messenger-sidebar ${menu?'is-open':''}`} aria-label="Разделы помощника">
   <div className="messenger-brand"><Brand/><button className="icon-btn messenger-mobile" aria-label="Закрыть меню" onClick={()=>setMenu(false)}><Icon as={X}/></button></div>
   <label className="messenger-search"><Icon as={Search} size={18}/><input type="search" aria-label="Найти своё обращение" placeholder="Найти обращение" value={query} onChange={e=>setQuery(e.target.value)}/></label>
   <nav className="messenger-nav" aria-label="Основная навигация">{nav.map(([href,label,hint,icon])=><a href={href} key={href} aria-current={(path===href||(href==='/'&&inChat))?'page':undefined} onClick={e=>{e.preventDefault();navigate(href==='/'&&search?'/chat'+search:href);}}><span className="messenger-nav-icon"><Icon as={icon}/></span><span><strong>{label}</strong><small>{hint}</small></span></a>)}</nav>
   <div className="messenger-list-heading"><span>Последние обращения</span><span>{tickets.length}</span></div>
   <div className="messenger-recent">{tickets.length?tickets.map(t=><a key={t.token} href={'/track/'+t.token} onClick={e=>{e.preventDefault();navigate('/track/'+t.token);}} aria-current={path==='/track/'+t.token?'page':undefined}><Icon as={ClipboardList} size={19}/><span><strong>{t.title}</strong><small>{t.number}</small></span></a>):<p>{query?'Обращения не найдены.':'После отправки здесь появятся ваши обращения.'}</p>}</div>
   <div className="messenger-footer"><a href="/admin" onClick={e=>{e.preventDefault();navigate('/admin');}}><Icon as={ShieldCheck} size={18}/>Вход для сотрудников</a><div><span>Цветовая тема</span><ThemePicker theme={theme} onChange={setTheme}/></div></div>
  </aside>
  {menu&&<button className="messenger-overlay" aria-label="Закрыть меню" onClick={()=>setMenu(false)}/>}
  <main className="messenger-workspace" id="main">
   {!inChat&&<header className="messenger-page-header"><button className="icon-btn messenger-mobile" aria-label="Открыть меню" onClick={()=>setMenu(true)}><Icon as={Menu}/></button><strong>{path.startsWith('/track/')?'Обращение':path==='/my'?'Мои обращения':'База знаний'}</strong><ThemeMenu theme={theme} onChange={setTheme}/></header>}
   {error?<div className="content"><ErrorBox>{error}</ErrorBox><button className="btn primary" onClick={()=>location.reload()}>Повторить загрузку</button></div>:!bootstrap?<div className="screen-loader"><Spinner/> Загружаем помощника…</div>:path.startsWith('/track/')?<Track token={path.split('/')[2]}/>:path==='/my'?<MyTickets navigate={navigate}/>:path==='/knowledge'?<div className="content knowledge-page"><PageHeading title="База знаний" text="Безопасные ответы на частые вопросы. Если инструкция не помогла — напишите помощнику."/><div className="knowledge-list">{bootstrap.knowledge.map(k=><details key={k.id}><summary><span><Icon as={BookOpen}/>{k.question}</span></summary><div><p>{k.answer}</p><small>{k.source}</small><button className="btn secondary" onClick={()=>navigate(search?'/chat'+search:'/')}>Открыть помощника</button></div></details>)}</div></div>:<Chat bootstrap={bootstrap} navigate={navigate} theme={theme} setTheme={setTheme} qrMode={path==='/chat'} onMenu={()=>setMenu(true)}/>}
  </main>
 </div>;
}
createRoot(document.getElementById('root')).render(<App/>);
