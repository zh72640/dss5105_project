/* Registration cards use server-saved comparisons and explicit, retryable decisions. */
(function(root){
  'use strict';
  const labels={order_id:'Order ID',customer:'Customer',product:'Product',category:'Category',pieces:'Pieces',order_date:'Order date',due_date:'Due date'};
  function card(task,onDecision){
    const text=(tag,value,cls)=>{const n=document.createElement(tag);if(value!=null)n.textContent=String(value);if(cls)n.className=cls;return n;};
    const node=text('article',null,'chat-registration-card'),review=task.review;
    node.append(text('h3','Order registration'));
    const dl=text('dl');
    Object.entries(labels).forEach(([key,label])=>{const row=text('div');row.append(text('dt',label),text('dd',task.draft[key]??'Not provided'));dl.append(row);});node.append(dl);
    (task.issues||[]).forEach(issue=>node.append(text('p',issue.question,'chat-notice')));
    if(!review){node.append(text('p',task.status==='CANCELLED'?'Registration cancelled.':'Reply in the conversation to complete or correct these details.'));return node;}
    if(review.decision){node.append(text('p',review.decision.message,'chat-notice'),text('p',`Decision: ${review.decision.outcome.replaceAll('_',' ')} · ${review.decision.actor}`),text('p',`Reason: ${review.decision.reason}`));return node;}
    if(review.match==='identical'){node.append(text('p','All fields match the registered order. No duplicate was created.','chat-notice'));return node;}
    node.append(text('p',review.match==='missing'?'This order ID is not registered. Confirm below to create it.':'This order ID exists. Verify the differences before approving changes.','chat-notice'));
    if(review.update_blocker)node.append(text('p',review.update_blocker,'chat-notice'));
    const fields=text('fieldset'),checks=[];
    fields.disabled=task.status!=='REVIEW'||!!task.issues?.length||!onDecision;
    let confirmId=null;
    if(review.match==='different'){
      review.differences.forEach(diff=>{
        const label=text('label',null,'registration-difference'),check=text('input');check.type='checkbox';check.value=diff.field;
        label.append(check,text('span',`${labels[diff.field]}: ${diff.stored} → ${diff.proposed}`));fields.append(label);checks.push(check);
      });
      const label=text('label','Retype the order ID to approve changes');confirmId=text('input');confirmId.maxLength=128;confirmId.autocomplete='off';label.append(confirmId);fields.append(label);
    }
    const reasonLabel=text('label','Reason for your decision'),reason=text('textarea');reason.rows=2;reason.maxLength=2000;reason.required=true;reasonLabel.append(reason);fields.append(reasonLabel);
    const notice=text('p',null,'chat-notice');notice.setAttribute('role','status');notice.hidden=true;
    const actions=text('div',null,'registration-actions');
    for(const [action,label] of [[review.match==='missing'?'create':'update',review.match==='missing'?'Confirm new order':'Approve verified changes'],['reject',review.match==='missing'?'Do not add order':'Keep registered values']]){
      const button=text('button',label,action==='reject'?'secondary':'primary');button.type='button';
      button.addEventListener('click',async()=>{
        const fail=message=>{notice.hidden=false;notice.textContent=message;};
        if(!reason.value.trim()){fail('Enter a reason for your decision.');reason.focus();return;}
        if(action==='update'&&(checks.some(check=>!check.checked)||confirmId.value!==review.order_id)){fail('Verify every difference and retype the exact order ID.');return;}
        fields.disabled=true;notice.hidden=true;
        try{await onDecision(review,{review_id:review.review_id,action,expected_version:review.expected_version,
          reason:reason.value.trim(),verified_fields:checks.filter(check=>check.checked).map(check=>check.value),confirmed_order_id:confirmId?.value||''});}
        catch(error){fail(error.message);fields.disabled=false;}
      });actions.append(button);
    }
    fields.append(actions,notice);node.append(fields,text('p','Every approval or rejection is saved in Registration history.'));
    return node;
  }
  const api={card};if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.ChatRegistration=api;
})(typeof globalThis!=='undefined'?globalThis:this);
