/* Shared Chat v2 client: both confirmation entry points use this contract. */
(function(root){
  'use strict';
  function confirmation(recommendation, requestId){
    return {request_id:requestId,expected_version:recommendation.session_version,action:'confirm',message:'',recommendation_id:recommendation.recommendation_id};
  }
  function canConfirm(recommendation){return !!recommendation&&recommendation.status==='valid'&&recommendation.task_state!=='CONFIRMED';}
  function stateLabel(status){return {valid:'Awaiting confirmation',superseded:'Superseded',confirmed:'Committed'}[status]||status;}
  function text(tag,content,className){const n=document.createElement(tag);if(content!=null)n.textContent=String(content);if(className)n.className=className;return n;}
  async function request(url,body){
    const response=await fetch(url,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});
    const data=await response.json();
    if(!response.ok&&!data.assistant_message){const error=new Error(data.message||data.error||'Request failed');error.status=response.status;error.code=data.error;throw error;}
    return data;
  }
  function card(recommendation,onConfirm){
    const result=recommendation.committed_result||recommendation.result;
    const node=text('article',null,'chat-recommendation');
    node.append(text('strong','Allocation plan · '+stateLabel(recommendation.status)));
    (result.allocation||[]).forEach(p=>node.append(text('p',`Workshop ${p.workshop_id} · ${p.workshop_name}: ${p.pieces} pieces`)));
    node.append(text('p',`Estimated completion ${result.estimated_delivery_date} · Estimated cost ${result.estimated_cost}`));
    if(result.warnings?.length)node.append(text('p',result.warnings.map(w=>({ESTIMATED_DEADLINE_MISS:'Estimated date exceeds the registered due date; the deadline is currently soft.'}[w]||w)).join('; '),'chat-notice'));
    const button=text('button',recommendation.status==='confirmed'?'Committed':'Confirm allocation','primary');
    button.disabled=!canConfirm(recommendation);
    button.type='button';
    button.addEventListener('click',()=>onConfirm(recommendation,button));
    node.append(button);
    return node;
  }
  const api={confirmation,canConfirm,stateLabel,text,request,card};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  else root.ChatV2=api;
})(typeof globalThis!=='undefined'?globalThis:this);
