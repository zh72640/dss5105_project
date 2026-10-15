/* Chat recommendations remain owner-scoped and never become v1 drafts. */
(() => {
  'use strict';
  const C=ChatV2,target=document.getElementById('chat-recommendations-list'),notice=document.getElementById('chat-recommendations-notice');
  let busy=false,pending=null,owner=null;
  const key=()=>`sweaterco.chat.confirm.v2.${owner||''}`;
  async function deliver(){
    if(!pending||busy)return;busy=true;notice.textContent='Confirming allocation…';
    try{const data=await C.request(pending.url,pending.body);pending=null;localStorage.removeItem(key());notice.textContent=data.assistant_message?.content||'Committed; the result was saved in the conversation.';await refresh();}
    catch(e){notice.textContent=e.message;if(e.status&&e.status<500){pending=null;localStorage.removeItem(key());await refresh();}else{const b=C.text('button','Retry confirmation');b.addEventListener('click',deliver);notice.append(b);}}
    finally{busy=false;}
  }
  async function confirm(rec,button){if(busy||pending)return;button.disabled=true;pending={url:`/api/chat/sessions/${rec.session_id}/turns`,body:C.confirmation(rec,crypto.randomUUID())};localStorage.setItem(key(),JSON.stringify(pending));await deliver();}
  async function refresh(){
    const me=await C.request('/api/auth/me');if(!me.username){owner=null;target.replaceChildren();return;}
    if(owner!==me.username){owner=me.username;try{pending=JSON.parse(localStorage.getItem(key())||'null');}catch{pending=null;}if(pending){notice.textContent='The last confirmation has no recovered result.';const b=C.text('button','Retry confirmation');b.addEventListener('click',deliver);notice.append(b);}}
    let cursor=0,items=[];do{const page=await C.request(`/api/chat/recommendations?after=${cursor}&limit=100`);items.push(...page.items);cursor=page.next_cursor;}while(cursor!=null);
    target.replaceChildren();items.reverse().forEach(rec=>{const card=C.card(rec,confirm);if(busy||pending)card.querySelector('button').disabled=true;const link=C.text('a','View conversation ↗');link.href='/chat?session='+encodeURIComponent(rec.session_id);card.append(link);target.append(card);});
    if(!items.length)target.append(C.text('p','Recommendations created in conversations appear here.','muted'));
  }
  window.addEventListener('focus',()=>{if(!busy)refresh().catch(()=>{});});
  window.addEventListener('hashchange',()=>{if(location.hash==='#recommendations'&&!busy)refresh().catch(()=>{});});
  setInterval(()=>{if(!busy&&document.visibilityState==='visible'&&location.hash==='#recommendations')refresh().catch(()=>{});},6000);
  refresh().catch(e=>notice.textContent=e.message);
})();
