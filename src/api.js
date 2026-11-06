export async function api(path, options = {}) {
  const isForm=options.body instanceof FormData;
  const response=await fetch('/api'+path,{...options,headers:{...(!isForm&&options.body?{'Content-Type':'application/json'}:{}),...options.headers},body:options.body&&!isForm?JSON.stringify(options.body):options.body});
  if(!response.ok){ let data;try{data=await response.json();}catch{data={};} const error=new Error(typeof data.detail==='string'?data.detail:response.status===422?'Проверьте заполнение полей.':'Не удалось выполнить запрос. Попробуйте ещё раз.');error.status=response.status;throw error;}
  return response.json();
}
export function friendlyError(error){return error instanceof TypeError?'Нет связи с сервером. Проверьте подключение и повторите.':error.message;}
// getRandomValues also works on HTTP LAN origins used by the room QR codes.
export function requestId(){return Array.from(crypto.getRandomValues(new Uint8Array(20)),byte=>byte.toString(16).padStart(2,'0')).join('');}
export const date=(value,short=false)=>new Intl.DateTimeFormat('ru-RU',{day:'numeric',month:'short',...(short?{}:{hour:'2-digit',minute:'2-digit'}),timeZone:'Europe/Moscow'}).format(new Date(value));
export function savedTickets(){try{return JSON.parse(localStorage.getItem('upk-tickets-v1')||'[]');}catch{return [];}}
export function saveTicket(ticket){try{const list=savedTickets();if(!list.some(t=>t.token===ticket.token))localStorage.setItem('upk-tickets-v1',JSON.stringify([ticket,...list].slice(0,50)));}catch{ /* Статус всё равно доступен по ссылке после отправки. */ }}
