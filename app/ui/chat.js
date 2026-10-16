'use strict';
(() => {
  const C=ChatV2,$=id=>document.getElementById(id);
  let user=null,session=null,pending=null,busy=false,listCursor=0,epoch=0;
  const stateNames={COLLECTING:'Collecting requirements',BLOCKED:'Needs clarification',READY:'Ready to calculate',RECOMMENDED:'Awaiting confirmation',CONFIRMED:'Committed',CANCELLED:'Cancelled'};
  const objectiveNames={min_delay:'Earliest completion',min_cost:'Lowest cost',min_defects:'Lowest defect rate',hybrid:'Weighted time and quality'};
  const key=()=>`sweaterco.chat.v2.${user?.username||''}`;
  function persist(){localStorage.setItem(key(),JSON.stringify({session_id:session?.session_id,pending}));}
  function status(value){$('chat-status').textContent=value||'';}
  function endTarget(){
    if(!pending)return null;
    const isMessage=pending.body.action==='message'||(pending.url==='/api/chat/sessions'&&pending.body.message);
    if(!isMessage)return null;
    if(pending.run?.can_end)return pending.run;
    if(session?.mode==='llm'&&pending.url===`/api/chat/sessions/${session.session_id}/turns`)
      return {session_id:session.session_id,request_id:pending.body.request_id,expected_version:pending.body.expected_version};
    return null;
  }
  function pendingNotice(){
    if(pending?.run?.retryable===false){
      const message=pending.error_message||'This request cannot be retried.';
      return message+(endTarget()&&!/\bend this request\b/i.test(message)?' End this request to send a new message.':'');
    }
    return (pending?.error_message||'The last action has no confirmed result.')+' Retry uses the same request ID to prevent duplicate submission.';
  }
  function controls(){
    $('chat-send').disabled=busy||!!pending||session?.status==='ARCHIVED';
    $('chat-new').disabled=busy||!!pending;
    $('chat-input').disabled=busy||!!pending||session?.status==='ARCHIVED';
    $('chat-archive').disabled=busy||!!pending||!session||session.status==='ARCHIVED';
    $('chat-retry').hidden=!pending;$('chat-retry').disabled=busy||pending?.run?.retryable===false;
    $('chat-end-request').hidden=!endTarget();$('chat-end-request').disabled=busy;$('chat-working').hidden=!busy;
    document.querySelectorAll('.chat-recommendation button').forEach(n=>n.disabled=busy||!!pending||!C.canConfirm(session?.recommendation));
  }
  async function allPages(url){let out=[],cursor=0;do{const data=await C.request(`${url}${url.includes('?')?'&':'?'}after=${cursor}&limit=100`);out.push(...data.items);cursor=data.next_cursor;}while(cursor!=null);return out;}
  async function sessionList(append=false){
    const data=await C.request(`/api/chat/sessions?after=${append?listCursor:0}&limit=30`);
    if(!append)$('chat-session-list').replaceChildren();listCursor=data.next_cursor;
    data.items.forEach(s=>{const b=C.text('button',s.title+(s.status==='ARCHIVED'?' · Archived':''),s.session_id===session?.session_id?'selected':'');b.type='button';b.addEventListener('click',()=>{if(busy||pending)return;load(s.session_id).catch(e=>status(e.message));document.body.classList.remove('show-chat-sidebar');});$('chat-session-list').append(b);});
    $('chat-more-sessions').hidden=listCursor==null;
  }
  function renderReport(){
    const target=$('chat-validation'),report=session.task.report;target.replaceChildren();target.hidden=!Object.keys(report).length;
    if(target.hidden)return;target.append(C.text('h2',report.ready_for_planning?'Requirements checked':'Review required'));
    const dl=C.text('dl');const values={'Order':report.resolved_fields?.order_id,'Category':({TOPS:'Tops',ACCESSORIES:'Accessories'}[report.resolved_fields?.category]||report.resolved_fields?.category),'Remaining pieces':report.resolved_fields?.pieces!=null?report.resolved_fields.pieces-report.resolved_fields.completed_pieces:undefined,'Registered due date':report.resolved_fields?.due_date,'Objective':objectiveNames[report.effective_constraints?.objective],'Workshop limit':report.effective_constraints?.num_workshop_allowed,'Excluded':report.effective_constraints?.exclusion?.join(', ')||'None','Hard deadline':report.effective_constraints?.deadline_required?'Yes':'No'};
    Object.entries(values).forEach(([k,v])=>{const n=C.text('div');n.append(C.text('dt',k),C.text('dd',v??'Pending'));dl.append(n);});target.append(dl);
    (report.blocking_issues||[]).forEach(p=>target.append(C.text('p',p.question,'chat-notice')));
  }
  async function load(sid,followLatest=false){
    const token=++epoch;
    const scroll=$('chat-content');const nearBottom=scroll.scrollHeight-scroll.scrollTop-scroll.clientHeight<100;const oldId=session?.session_id;
    const [snapshot,messages]=await Promise.all([C.request('/api/chat/sessions/'+encodeURIComponent(sid)),allPages('/api/chat/sessions/'+encodeURIComponent(sid)+'/messages')]);
    if(token!==epoch)return;
    session=snapshot;session.recommendation&&Object.assign(session.recommendation,{session_version:session.version,task_state:session.task.state});
    $('chat-empty').hidden=messages.length>0;$('chat-title').textContent=session.title;
    $('chat-subtitle').textContent=`Business date ${session.business_date} · ${stateNames[session.task.state]} · ${session.mode==='offline'?'Offline rules demo':session.model_key}`;
    const lastCard=messages.filter(m=>m.role==='assistant'&&m.metadata?.recommendation_id===session.recommendation?.recommendation_id).at(-1)?.message_id;
    $('chat-messages').replaceChildren();messages.forEach(m=>{const n=C.text('article',null,'chat-message '+m.role);n.append(C.text('small',m.role==='user'?'You':'Assistant'),C.text('div',m.content));if(session.recommendation&&m.message_id===lastCard)n.append(C.card(session.recommendation,confirm));$('chat-messages').append(n);});
    renderReport();$('chat-plan').replaceChildren();$('chat-plan').hidden=!session.recommendation;
    if(session.recommendation&&!lastCard)$('chat-plan').append(C.card(session.recommendation,confirm));
    persist();controls();if(followLatest||nearBottom||oldId!==sid)scroll.scrollTop=scroll.scrollHeight;
  }
  async function deliver(){
    if(!pending||busy||pending.run?.retryable===false)return;busy=true;controls();status('');const operation=pending;
    try{
      const data=await C.request(operation.url,operation.body);pending=null;persist();
      await load(data.session_id,true);await sessionList();status(data.http_status>=400?'The issue is shown in the conversation.':data.assistant_message?'':'Session created. Enter your request.');
      const url=new URL(location.href);url.searchParams.set('session',data.session_id);history.replaceState(null,'',url);
    }catch(e){
      if(e.details?.can_end){
        operation.run=e.details;
        const phases={intent:'Understanding the request',extract:'Extracting order details',tool_loop:'Preparing the recommendation',explanation:'Explaining the recommendation',response:'Preparing the response'};
        operation.error_message=(phases[e.details.phase]?phases[e.details.phase]+': ':'')+e.message;
      }else operation.error_message=e.message;
      if(e.status&&e.status<500&&!e.details?.can_end&&e.code!=='REQUEST_EXECUTING'&&e.code!=='AGENT_RUN_IN_PROGRESS')pending=null;
      persist();
      if(session)try{await load(session.session_id);}catch{}
      status(pending?pendingNotice():e.message);
    }finally{busy=false;controls();}
  }
  async function endRequest(){
    const target=endTarget();if(!target||busy)return;
    busy=true;controls();status('Ending the request…');let result=null;
    try{
      const data=await C.request(`/api/chat/sessions/${encodeURIComponent(target.session_id)}/requests/${encodeURIComponent(target.request_id)}/end`,{expected_version:target.expected_version});
      result=data;pending=null;if(session?.session_id===data.session_id)session.version=data.session_version;persist();
      const url=new URL(location.href);url.searchParams.set('session',data.session_id);history.replaceState(null,'',url);
      await load(data.session_id,true);await sessionList();status(data.message);
    }catch(e){status(result?result.message+' Refresh the page to load the latest session.':e.message+' The request has not been confirmed as ended.');}
    finally{busy=false;controls();}
  }
  function selection(){return {mode:$('chat-mode').value,...($('chat-mode').value==='llm'?{model_key:$('chat-model').value}:{})};}
  async function newSession(message=''){
    if(busy||pending)return;pending={url:'/api/chat/sessions',body:{request_id:crypto.randomUUID(),message,...selection()}};persist();await deliver();
  }
  async function send(action='message',message=''){
    if(busy||pending)return;
    if(!session)return newSession(message);
    pending={url:`/api/chat/sessions/${session.session_id}/turns`,body:{request_id:crypto.randomUUID(),expected_version:session.version,action,message}};persist();await deliver();
  }
  async function confirm(rec){if(busy||pending)return;pending={url:`/api/chat/sessions/${rec.session_id}/turns`,body:C.confirmation(rec,crypto.randomUUID())};persist();await deliver();}
  async function boot(){
    user=await C.request('/api/auth/me');$('chat-login').hidden=!!user.username;$('chat-app').hidden=!user.username;if(!user.username)return;
    $('chat-identity').textContent=user.username;const models=await C.request('/api/models');$('chat-mode').value=models.default_mode;
    $('chat-model').replaceChildren();models.models.forEach(m=>{const o=C.text('option',m.provider+' · '+m.model_key+(m.available?'':' (not configured)'));o.value=m.model_key;o.disabled=!m.available;$('chat-model').append(o);});$('chat-model').value=models.default_model||'';
    $('chat-model-label').hidden=$('chat-mode').value==='offline';
    let saved={};try{saved=JSON.parse(localStorage.getItem(key())||'{}');}catch{}pending=saved.pending||null;
    await sessionList();const sid=new URL(location.href).searchParams.get('session')||saved.session_id;if(sid)try{await load(sid);}catch(e){status(e.message);}
    if(pending)status(pendingNotice());controls();
  }
  $('chat-composer').addEventListener('submit',async event=>{event.preventDefault();const msg=$('chat-input').value.trim();if(msg){$('chat-input').value='';await send('message',msg);}});
  $('chat-input').addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();$('chat-composer').requestSubmit();}});
  $('chat-new').addEventListener('click',()=>newSession());$('chat-retry').addEventListener('click',deliver);$('chat-end-request').addEventListener('click',endRequest);
  $('chat-archive').addEventListener('click',()=>send('archive'));
  $('chat-more-sessions').addEventListener('click',()=>sessionList(true));
  $('chat-menu').addEventListener('click',()=>document.body.classList.toggle('show-chat-sidebar'));
  $('chat-mode').addEventListener('change',()=>{$('chat-model-label').hidden=$('chat-mode').value==='offline';status('Mode selection applies to new sessions. The current session keeps its mode.');});
  $('chat-font').value=localStorage.getItem('sweaterco.text-size')||'medium';document.documentElement.dataset.textSize=$('chat-font').value;
  $('chat-font').addEventListener('change',()=>{document.documentElement.dataset.textSize=$('chat-font').value;localStorage.setItem('sweaterco.text-size',$('chat-font').value);});
  $('chat-login-form').addEventListener('submit',async event=>{event.preventDefault();try{await C.request('/api/auth/login',{username:$('chat-username').value,password:$('chat-password').value});$('chat-password').value='';await boot();}catch(e){$('chat-login-error').textContent=e.message;}});
  $('chat-signout').addEventListener('click',async()=>{await C.request('/api/auth/logout',{});location.reload();});
  async function synchronize(){
    if(busy||pending)return;const me=await C.request('/api/auth/me');
    if(me.username!==user?.username){epoch++;session=null;pending=null;$('chat-messages').replaceChildren();$('chat-validation').hidden=true;$('chat-plan').hidden=true;await boot();return;}
    if(session)await load(session.session_id);
  }
  window.addEventListener('focus',()=>synchronize().catch(e=>status(e.message)));
  setInterval(()=>{if(document.visibilityState==='visible')synchronize().catch(()=>{});},12000);
  boot().catch(e=>status(e.message));
})();
