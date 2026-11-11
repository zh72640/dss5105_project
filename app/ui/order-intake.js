/* Explicit manual decisions use the saved server comparison, never editable form facts. */
'use strict';
(() => {
  const names={order_id:'Order ID',customer:'Customer',product:'Product',category:'Category',pieces:'Pieces',order_date:'Order date',due_date:'Due date'};
  let review=null,checkRequest=null,pending=null,busy=false,owner=null,historyOffset=0;
  const key=()=>`sweaterco.order-intake.${owner}`;
  function message(text,error=false){const n=$('intake-feedback');n.hidden=!text;n.textContent=text;n.classList.toggle('error',error);}
  function save(){try{sessionStorage.setItem(key(),JSON.stringify({checkRequest,pending,review_id:review?.review_id}));}catch{message('Browser recovery storage is unavailable. Keep this tab open and retry here if the connection fails.',true);}}
  function controls(){
    $('intake-form').hidden=!!review;
    $('intake-fields').disabled=busy||!!checkRequest;
    $('intake-check').hidden=!!review;
    $('intake-check').disabled=busy;
    $('intake-check').textContent=checkRequest?'Retry saved check':'Check order';
    $('intake-review').hidden=!review;
    $('intake-decision-form').hidden=!review||review.match==='identical'||!!review.decision;
    $('intake-decision-fields').disabled=busy||!!pending;
    $('intake-another').disabled=busy||!!pending;
    $('intake-retry').hidden=!pending;
    $('intake-retry').disabled=busy;
    $('intake-chat').hidden=!(review?.match==='identical'||review?.decision?.applied);
  }
  function comparison(target,r){table(target,['Field','Registered value','Entered value'],Object.entries(names).map(([field,label])=>[label,r.existing?.[field]??'Not registered',r.proposed[field]]));}
  function render(){
    if(!review){controls();return;}
    for(const field of Object.keys(names))$('intake-'+field).value=review.proposed[field];
    $('intake-review-title').textContent={missing:'Order not found — confirm creation',identical:'Order already registered — all fields match',different:'Existing order — differences need verification'}[review.match];
    $('intake-review-help').textContent=review.match==='missing'?'No order with this ID exists. Confirm to register it, or record a decision not to add it.':review.match==='identical'?'The matching check has been recorded. No duplicate was created.':review.update_blocker||'Review the registered and entered values. Check each difference and retype the order ID to approve changes. Both approval and rejection are recorded.';
    comparison($('intake-comparison'),review);
    $('intake-verification').hidden=review.match!=='different';
    $('intake-verify-fields').replaceChildren(...review.differences.map(diff=>{
      const label=el('label',null,'checkbox'),input=el('input');input.type='checkbox';input.value=diff.field;
      label.append(input,el('span',`${names[diff.field]}: ${diff.stored} → ${diff.proposed}`));return label;
    }));
    $('intake-confirm-id').value='';$('intake-reason').value='';
    $('intake-approve').textContent=review.match==='missing'?'Confirm new order':'Approve verified changes';
    $('intake-reject').textContent=review.match==='missing'?'Do not add order':'Keep registered values';
    if(review.decision)message(`${review.decision.message} Recorded by ${review.decision.actor}.`,!['CREATED','UPDATED','REJECTED'].includes(review.decision.outcome));
    controls();
  }
  function reset(){review=null;checkRequest=null;pending=null;$('intake-form').reset();message('');save();controls();}
  async function open(){
    if(!state.user?.username)return;
    if(busy){if(owner===state.user.username&&!$('order-intake-dialog').open)$('order-intake-dialog').showModal();return;}
    owner=state.user.username;review=null;checkRequest=null;pending=null;message('');
    $('intake-form').reset();
    $('order-intake-dialog').showModal();
    let saved={};
    try{saved=JSON.parse(sessionStorage.getItem(key())||'{}')||{};}catch{message('Saved browser recovery data is unavailable. Review registration history before starting another check.',true);}
    try{checkRequest=saved.checkRequest||null;pending=saved.pending||null;
      if(checkRequest)for(const field of Object.keys(names))$('intake-'+field).value=checkRequest.order[field];
      if(saved.review_id){busy=true;controls();review=await api('/api/order-intake/reviews/'+encodeURIComponent(saved.review_id));
        if(review.decision){pending=null;save();}render();}
    }catch(error){message(error.message,true);}
    finally{busy=false;controls();}
  }
  async function check(event){
    event.preventDefault();if(busy)return;
    if(!checkRequest){const order=Object.fromEntries(Object.keys(names).map(field=>[field,$('intake-'+field).value]));order.pieces=Number(order.pieces);checkRequest={request_id:crypto.randomUUID(),order};save();}
    busy=true;controls();message('Checking the order register…');
    try{review=await api('/api/order-intake/reviews',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(checkRequest)});message('');save();render();}
    catch(error){message(error.message+' Retry the saved check if the response was lost.',true);
      // A validation rejection is definite; allow correcting the submitted form.
      if(error.message==='INVALID_FIELDS'){checkRequest=null;save();message('Check the order ID, required fields, quantity and dates. Due date must not precede order date.',true);}}
    finally{busy=false;controls();}
  }
  async function decide(action){
    if(busy||pending||!review||review.decision)return;
    const reason=$('intake-reason').value.trim();if(!reason){$('intake-reason').reportValidity();message('Enter a reason for this decision.',true);return;}
    const verified=[...$('intake-verify-fields').querySelectorAll('input:checked')].map(n=>n.value);
    const confirmed=$('intake-confirm-id').value;
    if(action==='update'&&(confirmed!==review.order_id||verified.length!==review.differences.length)){message('Check every changed field and retype the exact order ID before approving.',true);return;}
    pending={request_id:crypto.randomUUID(),action,reason,expected_version:review.expected_version,confirmed_order_id:confirmed,verified_fields:verified};save();await deliver();
  }
  async function deliver(){
    if(!pending||busy||!review)return;busy=true;controls();message('Saving your decision…');
    try{
      const response=await fetch('/api/order-intake/reviews/'+encodeURIComponent(review.review_id)+'/decision',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(pending)});
      const data=await response.json();
      if(response.status===401){showLogin();throw Error('Sign in with the same account and reopen Add order to retry.');}
      if(!data.outcome){
        if(response.status===409&&data.error==='REVIEW_ALREADY_DECIDED'){
          review=await api('/api/order-intake/reviews/'+encodeURIComponent(review.review_id));pending=null;save();render();return;
        }
        throw Error(data.message||data.error||'The decision could not be saved.');
      }
      review.decision=data;pending=null;save();render();
      if(data.applied){await refreshDesk();if(location.hash==='#orders'){$('orders-search').value=review.order_id;DeskViews.renderOrders(state.desk,trackFromRegister);}}
    }catch(error){message(error.message+(pending?' Use Retry saved decision; it cannot apply twice.':''),true);}
    finally{busy=false;controls();}
  }
  async function history(){
    $('intake-history-feedback').textContent='Loading registration history…';
    $('intake-history-prev').disabled=true;$('intake-history-next').disabled=true;
    try{
      const order=$('intake-history-order').value.trim();
      const data=await api(`/api/order-intake/history?limit=20&offset=${historyOffset}&order_id=${encodeURIComponent(order)}`);
      $('intake-history-items').replaceChildren(...data.items.map(r=>{
        const entry=el('details'),outcome=r.decision?.outcome||(r.match==='identical'?'MATCHED':'AWAITING DECISION');
        entry.append(el('summary',`${r.order_id} · ${outcome.replaceAll('_',' ')} · ${stamp(r.created_at)}`));
        entry.append(el('p',`Checked by ${r.actor}. ${r.decision?`Decision by ${r.decision.actor} at ${stamp(r.decision.created_at)}.`:'No order changes from this check.'}`));
        const grid=el('div',null,'table-wrap');comparison(grid,r);entry.append(grid);
        if(r.decision){entry.append(el('p',`Reason: ${r.decision.reason}`),el('p',r.decision.message));
          const evidence=r.decision.evidence;
          if(evidence){const snapshots=el('details');snapshots.append(el('summary','Recorded verification and final values'));
            snapshots.append(el('p',`Verified fields: ${evidence.verified_fields.map(f=>names[f]||f).join(', ')||'None'}. Confirmed order ID: ${evidence.confirmed_order_id||'None'}.`));
            const final=el('div',null,'table-wrap');table(final,['Field','Before decision','After decision'],Object.entries(names).map(([field,label])=>[label,evidence.before?.[field]??'Not registered',evidence.after?.[field]??'Not registered']));snapshots.append(final);entry.append(snapshots);}}
        entry.append(el('small',`Review reference: ${r.review_id}`));return entry;
      }));
      $('intake-history-feedback').textContent=data.total?`${historyOffset+1}–${Math.min(historyOffset+data.items.length,data.total)} of ${data.total} checks`:'No registration checks found.';
      $('intake-history-prev').disabled=historyOffset===0;$('intake-history-next').disabled=historyOffset+data.items.length>=data.total;
    }catch(error){$('intake-history-feedback').textContent=error.message;}
  }
  $('order-intake-open').addEventListener('click',open);
  $('intake-form').addEventListener('submit',check);
  $('intake-decision-form').addEventListener('submit',event=>event.preventDefault());
  $('intake-approve').addEventListener('click',()=>decide(review.match==='missing'?'create':'update'));
  $('intake-reject').addEventListener('click',()=>decide('reject'));
  $('intake-retry').addEventListener('click',deliver);
  $('intake-another').addEventListener('click',reset);
  $('order-intake-history').addEventListener('click',()=>{historyOffset=0;$('intake-history-order').value='';$('intake-history-dialog').showModal();history();});
  $('intake-history-form').addEventListener('submit',event=>{event.preventDefault();historyOffset=0;history();});
  $('intake-history-prev').addEventListener('click',()=>{historyOffset=Math.max(0,historyOffset-20);history();});
  $('intake-history-next').addEventListener('click',()=>{historyOffset+=20;history();});
})();
