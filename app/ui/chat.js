'use strict';
(() => {
  const C=ChatV2,$=id=>document.getElementById(id);
  let user=null,session=null,listCursor=0,epoch=0,listEpoch=0,scope=null,activeId=null,starting=false,loading=false;
  const executing=new Set();
  const stateNames={COLLECTING:'Collecting requirements',BLOCKED:'Needs clarification',READY:'Ready to calculate',RECOMMENDED:'Awaiting confirmation',CONFIRMED:'Committed',CANCELLED:'Cancelled'};
  const objectiveNames={min_delay:'Earliest completion',min_cost:'Lowest cost',min_defects:'Lowest defect rate',hybrid:'Weighted time and quality'};
  const key=()=>`sweaterco.chat.v2.${user?.username||''}`;
  function savedState(storageKey){
    try{return JSON.parse(localStorage.getItem(storageKey)||'{}')||{};}catch{return {};}
  }
  function operationSlot(operation,fallback){
    if(operation.run?.session_id)return operation.run.session_id;
    if(operation.url==='/api/chat/sessions')return 'create:'+operation.body.request_id;
    const match=operation.url.match(/^\/api\/chat\/sessions\/([^/]+)\/turns$/);
    return match?decodeURIComponent(match[1]):fallback;
  }
  // Keep each user's unfinished operations separate from the selected conversation.
  function restoreScope(){
    const saved=savedState(key());
    scope={key:key(),operations:{...(saved.operations||{})}};
    if(saved.pending){
      const slot=operationSlot(saved.pending,saved.session_id);
      if(slot&&!scope.operations[slot])scope.operations[slot]=saved.pending;
      const next={...saved,operations:scope.operations,active_id:saved.active_id||slot};delete next.pending;
      if(slot&&!slot.startsWith('create:'))next.session_id=slot;
      if(saved.pending.url==='/api/chat/sessions'&&saved.pending.run?.session_id)next.created={...(saved.created||{}),[saved.pending.body.request_id]:slot};
      localStorage.setItem(scope.key,JSON.stringify(next));
    }
    return savedState(scope.key);
  }
  function pending(){return scope&&activeId?savedState(scope.key).operations?.[activeId]||null:null;}
  function runningKey(ownerScope,slot){return ownerScope.key+'|'+slot;}
  function busy(){return !!scope&&executing.has(runningKey(scope,activeId));}
  function persist(){
    if(!scope)return;
    const saved=savedState(scope.key);
    localStorage.setItem(scope.key,JSON.stringify({...saved,session_id:session?.session_id,active_id:activeId}));
  }
  // Merge one operation at a time so a late result preserves other sessions.
  function saveOperation(ownerScope,slot,operation,created){
    const saved=savedState(ownerScope.key),operations={...(saved.operations||{})};
    if(operation)operations[slot]=operation;else delete operations[slot];
    const next={...saved,operations};delete next.pending;
    if(created)next.created={...(saved.created||{}),[created.request_id]:created.session_id};
    localStorage.setItem(ownerScope.key,JSON.stringify(next));
    if(operation)ownerScope.operations[slot]=operation;else delete ownerScope.operations[slot];
  }
  function isCurrent(ownerScope,slot){return scope===ownerScope&&activeId===slot;}
  function sessionURL(sid){
    const url=new URL(location.href);url.searchParams.delete('new');url.searchParams.delete('creation');
    url.searchParams.set('session',sid);history.replaceState(null,'',url);
  }
  function clearConversation(){
    session=null;loading=false;epoch++;$('chat-input').value='';$('chat-messages').replaceChildren();
    $('chat-validation').hidden=true;$('chat-plan').replaceChildren();$('chat-plan').hidden=true;
    $('chat-empty').hidden=false;$('chat-title').textContent='New request';$('chat-subtitle').textContent='Enter your request to begin.';status('');
  }
  function status(value){$('chat-status').textContent=value||'';}
  function endTarget(){
    const operation=pending();if(!operation)return null;
    const isMessage=operation.body.action==='message'||(operation.url==='/api/chat/sessions'&&operation.body.message);
    if(!isMessage)return null;
    if(operation.run?.can_end)return operation.run;
    if(session?.mode==='llm'&&operation.url===`/api/chat/sessions/${session.session_id}/turns`)
      return {session_id:session.session_id,request_id:operation.body.request_id,expected_version:operation.body.expected_version};
    return null;
  }
  function pendingNotice(){
    const operation=pending();if(!operation)return '';
    if(operation.run?.retryable===false){
      const message=operation.error_message||'This request cannot be retried.';
      return message+(endTarget()&&!/\bend this request\b/i.test(message)?' End this request to send a new message.':'');
    }
    return (operation.error_message||'The last action has no confirmed result.')+' Retry uses the same request ID to prevent duplicate submission.';
  }
  function controls(){
    const operation=pending(),working=busy(),blocked=working||!!operation||starting||loading;
    $('chat-send').disabled=blocked||session?.status==='ARCHIVED';
    $('chat-new').disabled=starting||(!session&&working&&activeId?.startsWith('create:'));
    $('chat-input').disabled=blocked||session?.status==='ARCHIVED';
    $('chat-archive').disabled=blocked||!session||session.status==='ARCHIVED';
    $('chat-retry').hidden=!operation;$('chat-retry').disabled=working||operation?.run?.retryable===false;
    $('chat-end-request').hidden=!endTarget();$('chat-end-request').disabled=working;$('chat-working').hidden=!working;
    document.querySelectorAll('.chat-recommendation button').forEach(n=>n.disabled=blocked||!C.canConfirm(session?.recommendation));
  }
  async function allPages(url){let out=[],cursor=0;do{const data=await C.request(`${url}${url.includes('?')?'&':'?'}after=${cursor}&limit=100`);out.push(...data.items);cursor=data.next_cursor;}while(cursor!=null);return out;}
  async function sessionList(append=false){
    const ownerScope=scope,token=++listEpoch;
    const data=await C.request(`/api/chat/sessions?after=${append?listCursor:0}&limit=30`);
    if(scope!==ownerScope||token!==listEpoch)return;
    if(!append)$('chat-session-list').replaceChildren();listCursor=data.next_cursor;
    data.items.forEach(s=>{const b=C.text('button',s.title+(s.status==='ARCHIVED'?' · Archived':''),s.session_id===session?.session_id?'selected':'');b.type='button';b.addEventListener('click',()=>{load(s.session_id).catch(e=>status(e.message));document.body.classList.remove('show-chat-sidebar');});$('chat-session-list').append(b);});
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
    const ownerScope=scope,oldId=session?.session_id;
    activeId=sid;
    if(oldId!==sid)clearConversation();
    const token=++epoch;loading=true;controls();status(pending()?pendingNotice():'');
    const scroll=$('chat-content');const nearBottom=scroll.scrollHeight-scroll.scrollTop-scroll.clientHeight<100;
    try{
      const [snapshot,messages]=await Promise.all([C.request('/api/chat/sessions/'+encodeURIComponent(sid)),allPages('/api/chat/sessions/'+encodeURIComponent(sid)+'/messages')]);
      if(token!==epoch||scope!==ownerScope)return false;
      session=snapshot;session.recommendation&&Object.assign(session.recommendation,{session_version:session.version,task_state:session.task.state});
      $('chat-empty').hidden=messages.length>0;$('chat-title').textContent=session.title;
      $('chat-subtitle').textContent=`Business date ${session.business_date} · ${stateNames[session.task.state]} · ${session.mode==='offline'?'Offline rules demo':session.model_key}`;
      const lastCard=messages.filter(m=>m.role==='assistant'&&m.metadata?.recommendation_id===session.recommendation?.recommendation_id).at(-1)?.message_id;
      $('chat-messages').replaceChildren();messages.forEach(m=>{const n=C.text('article',null,'chat-message '+m.role);n.append(C.text('small',m.role==='user'?'You':'Assistant'),C.text('div',m.content));if(session.recommendation&&m.message_id===lastCard)n.append(C.card(session.recommendation,confirm));$('chat-messages').append(n);});
      renderReport();$('chat-plan').replaceChildren();$('chat-plan').hidden=!session.recommendation;
      if(session.recommendation&&!lastCard)$('chat-plan').append(C.card(session.recommendation,confirm));
      persist();sessionURL(sid);controls();status(pending()?pendingNotice():'');if(followLatest||nearBottom||oldId!==sid)scroll.scrollTop=scroll.scrollHeight;return true;
    }catch(error){if(token===epoch&&scope===ownerScope)throw error;return false;}
    finally{if(token===epoch&&scope===ownerScope){loading=false;controls();}}
  }
  async function deliver(){
    const operation=pending(),ownerScope=scope,slot=activeId;
    if(!operation||busy()||operation.run?.retryable===false)return;
    const execution=runningKey(ownerScope,slot);executing.add(execution);controls();status('');
    let acknowledged=false,responseSid=null;
    try{
      const data=await C.request(operation.url,operation.body);acknowledged=true;responseSid=data.session_id;
      saveOperation(ownerScope,slot,null,operation.url==='/api/chat/sessions'?{request_id:operation.body.request_id,session_id:data.session_id}:null);
      // A result belongs to its original conversation, even after navigation.
      if(!isCurrent(ownerScope,slot))return;
      activeId=data.session_id;sessionURL(data.session_id);persist();
      if(await load(data.session_id,true)){
        await sessionList();
        if(isCurrent(ownerScope,data.session_id)&&!pending())status(data.http_status>=400?'The issue is shown in the conversation.':data.assistant_message?'':'Session created. Enter your request.');
      }
    }catch(e){
      if(acknowledged){
        if(isCurrent(ownerScope,responseSid))status('The operation completed. Refresh the page to load the latest session.');
        return;
      }
      if(e.details?.can_end){
        operation.run=e.details;
        const phases={intent:'Understanding the request',extract:'Extracting order details',tool_loop:'Preparing the recommendation',explanation:'Explaining the recommendation',response:'Preparing the response'};
        operation.error_message=(phases[e.details.phase]?phases[e.details.phase]+': ':'')+e.message;
      }else operation.error_message=e.message;
      const rejected=e.status&&e.status<500&&!e.details?.can_end&&e.code!=='REQUEST_EXECUTING'&&e.code!=='AGENT_RUN_IN_PROGRESS'&&e.status!==401;
      saveOperation(ownerScope,slot,rejected?null:operation);
      const sid=operation.url==='/api/chat/sessions'?operation.run?.session_id:null;
      const wasCurrent=isCurrent(ownerScope,slot);
      if(sid&&sid!==slot){
        saveOperation(ownerScope,sid,operation,{request_id:operation.body.request_id,session_id:sid});
        saveOperation(ownerScope,slot,null);
      }
      if(!wasCurrent)return;
      if(sid){activeId=sid;sessionURL(sid);}
      const displaySlot=activeId;
      if(sid||session)try{await load(sid||session.session_id);}catch{}
      if(isCurrent(ownerScope,displaySlot))status(pending()?pendingNotice():e.message);
    }finally{
      executing.delete(execution);if(scope===ownerScope)controls();
    }
  }
  async function endRequest(){
    const target=endTarget(),ownerScope=scope,slot=activeId,operation=pending();if(!target||busy())return;
    const execution=runningKey(ownerScope,slot);executing.add(execution);controls();status('Ending the request…');let result=null;
    try{
      const data=await C.request(`/api/chat/sessions/${encodeURIComponent(target.session_id)}/requests/${encodeURIComponent(target.request_id)}/end`,{expected_version:target.expected_version});
      result=data;saveOperation(ownerScope,slot,null);
      if(!isCurrent(ownerScope,slot))return;
      if(session?.session_id===data.session_id)session.version=data.session_version;
      activeId=data.session_id;sessionURL(data.session_id);persist();
      if(await load(data.session_id,true)){await sessionList();if(isCurrent(ownerScope,data.session_id))status(data.message);}
    }catch(e){if(scope===ownerScope&&(activeId===slot||activeId===result?.session_id))status(result?result.message+' Refresh the page to load the latest session.':e.message+' The request has not been confirmed as ended.');}
    finally{executing.delete(execution);if(scope===ownerScope)controls();}
  }
  function selection(){return {mode:$('chat-mode').value,...($('chat-mode').value==='llm'?{model_key:$('chat-model').value}:{})};}
  async function newSession(message=''){
    if(starting||(!session&&busy()&&activeId?.startsWith('create:')))return;
    const requestId=crypto.randomUUID(),slot='create:'+requestId;
    const operation={url:'/api/chat/sessions',body:{request_id:requestId,message,...selection()}};
    // Save the ID and exact payload before sending; reloads retry this creation.
    saveOperation(scope,slot,operation);activeId=slot;clearConversation();persist();
    const url=new URL(location.href);url.searchParams.delete('session');url.searchParams.set('new','1');url.searchParams.set('creation',requestId);history.replaceState(null,'',url);
    await deliver();
  }
  async function send(action='message',message=''){
    if(busy()||pending()||starting||loading)return;
    if(!session)return newSession(message);
    saveOperation(scope,activeId,{url:`/api/chat/sessions/${session.session_id}/turns`,body:{request_id:crypto.randomUUID(),expected_version:session.version,action,message}});await deliver();
  }
  async function confirm(rec){
    if(busy()||pending()||starting||loading||rec.session_id!==session?.session_id)return;
    saveOperation(scope,activeId,{url:`/api/chat/sessions/${rec.session_id}/turns`,body:C.confirmation(rec,crypto.randomUUID())});await deliver();
  }
  async function boot(){
    starting=true;scope=null;activeId=null;clearConversation();controls();
    try{
      user=await C.request('/api/auth/me');$('chat-login').hidden=!!user.username;$('chat-app').hidden=!user.username;if(!user.username)return;
      $('chat-identity').textContent=user.username;const models=await C.request('/api/models');$('chat-mode').value=models.default_mode;
      $('chat-model').replaceChildren();models.models.forEach(m=>{const o=C.text('option',m.provider+' · '+m.model_key+(m.available?'':' (not configured)'));o.value=m.model_key;o.disabled=!m.available;$('chat-model').append(o);});$('chat-model').value=models.default_model||'';
      $('chat-model-label').hidden=$('chat-mode').value==='offline';
      const saved=restoreScope(),ownerScope=scope,url=new URL(location.href);
      clearConversation();activeId=null;
      await sessionList();if(scope!==ownerScope)return;
      if(url.searchParams.get('new')==='1'){
        const requestId=url.searchParams.get('creation');
        const created=requestId&&saved.created?.[requestId];
        if(created){await load(created);return;}
        const slot=requestId?'create:'+requestId:null;
        if(slot?.startsWith('create:')&&scope.operations[slot]){
          activeId=slot;persist();controls();status(pendingNotice());return;
        }
        starting=false;await newSession();return;
      }
      const sid=url.searchParams.get('session')||saved.session_id;
      if(sid)try{await load(sid);}catch(e){status(e.message);}
      else{
        const slot=saved.active_id||Object.keys(scope.operations).find(id=>id.startsWith('create:'));
        if(slot&&scope.operations[slot])activeId=slot;
      }
      if(pending())status(pendingNotice());controls();
    }finally{starting=false;controls();}
  }
  $('chat-composer').addEventListener('submit',async event=>{
    event.preventDefault();const msg=$('chat-input').value.trim();
    if(!msg||busy()||pending()||starting||loading)return;
    const ownerScope=scope,slot=activeId;$('chat-input').value='';
    try{await send('message',msg);}catch(error){
      if(isCurrent(ownerScope,slot)){if(!$('chat-input').value)$('chat-input').value=msg;status(error.message);}
    }
  });
  $('chat-input').addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();$('chat-composer').requestSubmit();}});
  $('chat-new').addEventListener('click',()=>newSession().catch(e=>status(e.message)));$('chat-retry').addEventListener('click',deliver);$('chat-end-request').addEventListener('click',endRequest);
  $('chat-archive').addEventListener('click',()=>send('archive').catch(e=>status(e.message)));
  $('chat-more-sessions').addEventListener('click',()=>sessionList(true));
  $('chat-menu').addEventListener('click',()=>document.body.classList.toggle('show-chat-sidebar'));
  $('chat-mode').addEventListener('change',()=>{$('chat-model-label').hidden=$('chat-mode').value==='offline';status('Mode selection applies to new sessions. The current session keeps its mode.');});
  $('chat-font').value=localStorage.getItem('sweaterco.text-size')||'medium';document.documentElement.dataset.textSize=$('chat-font').value;
  $('chat-font').addEventListener('change',()=>{document.documentElement.dataset.textSize=$('chat-font').value;localStorage.setItem('sweaterco.text-size',$('chat-font').value);});
  $('chat-login-form').addEventListener('submit',async event=>{event.preventDefault();try{await C.request('/api/auth/login',{username:$('chat-username').value,password:$('chat-password').value});$('chat-password').value='';await boot();}catch(e){$('chat-login-error').textContent=e.message;}});
  $('chat-signout').addEventListener('click',async()=>{await C.request('/api/auth/logout',{});epoch++;scope=null;session=null;activeId=null;location.reload();});
  async function synchronize(){
    const me=await C.request('/api/auth/me');
    if(me.username!==user?.username){epoch++;scope=null;activeId=null;clearConversation();await boot();return;}
    if(!starting&&!loading&&!busy()&&!pending()&&session)await load(session.session_id);
  }
  window.addEventListener('focus',()=>synchronize().catch(e=>status(e.message)));
  setInterval(()=>{if(document.visibilityState==='visible')synchronize().catch(()=>{});},12000);
  boot().catch(e=>status(e.message));
})();
