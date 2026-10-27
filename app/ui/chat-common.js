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
    if(!response.ok&&!data.assistant_message){const error=new Error(data.message||data.error||'Request failed');error.status=response.status;error.code=data.error;error.details=data.details;throw error;}
    return data;
  }
  function card(recommendation,onConfirm){
    const result=recommendation.committed_result||recommendation.result;
    const node=text('article',null,'chat-recommendation');
    node.append(text('strong','Allocation plan · '+stateLabel(recommendation.status)));
    (result.allocation||[]).forEach(p=>node.append(text('p',`Workshop ${p.workshop_id} · ${p.workshop_name}: ${p.pieces} pieces`)));
    if(node.dataset)node.dataset.status=recommendation.status;
    if(root.DispatchUI){
      const U=root.DispatchUI,parts=result.allocation||[],total=parts.reduce((n,p)=>n+p.pieces,0),bar=text('div',null,'plan-parts');
      parts.forEach(p=>{const part=text('div',p.workshop_id,'plan-part');part.style.backgroundColor=U.color(p.workshop_id);part.style.flex=String(p.pieces/Math.max(1,total));part.append(text('small',`${U.number(p.pieces,0)} pcs`));bar.append(part);});node.append(bar);
      const metrics=text('dl',null,'plan-metrics');
      [['Completion',U.date(result.estimated_delivery_date)],['Estimated cost',`${U.number(result.estimated_cost,2)} units`],['Expected defects',typeof result.expected_defect_rate==='number'?`${U.number(result.expected_defect_rate*100,2)}%`:'—']].forEach(([label,value])=>{const item=text('div');item.append(text('dt',label),text('dd',value));metrics.append(item);});node.append(metrics);
    }else node.append(text('p',`Estimated completion ${result.estimated_delivery_date} · Estimated cost ${result.estimated_cost}`));
    if(result.warnings?.length)node.append(text('p',result.warnings.map(w=>({ESTIMATED_DEADLINE_MISS:'Estimated date exceeds the registered due date; the deadline is currently soft.'}[w]||w)).join('; '),'chat-notice'));
    if(result.candidate_plans?.length){
      const details=text('details');details.append(text('summary','Compare complete candidate plans'));
      details.append(text('p',result.candidate_plan_scope||'Plans calculated under the current requirements.'));
      result.candidate_plans.forEach((plan,index)=>{
        const item=text('section');item.append(text('strong',index===0?'Recommended plan':'Alternative plan '+(index+1)));
        item.append(text('p',plan.allocation.map(p=>`${p.workshop_id} (${p.pieces} pieces)`).join(' + ')));
        item.append(text('p',`Completion ${plan.estimated_delivery_date} · Cost ${plan.estimated_cost} · Weighted defect rate ${(100*plan.expected_defect_rate).toFixed(2)}%`));
        item.append(text('p',plan.deadline_met?'Meets the registered due date.':'Exceeds the registered due date.'));
        details.append(item);
      });
      details.append(text('p','These plans satisfy the current requirements. To choose another plan, revise your request and review its new recommendation.'));
      node.append(details);
    }
    const button=text('button',recommendation.status==='confirmed'?'Committed':'Confirm allocation','primary');
    button.disabled=!canConfirm(recommendation);
    button.type='button';
    button.addEventListener('click',()=>onConfirm(recommendation,button));
    node.append(button);
    return node;
  }
  function alternatives(options){
    const node=text('section');node.append(text('h3','Options requiring your authorization'));
    const labels={preferred_workshop:()=> 'Remove the required sole workshop',deadline_required:()=> 'Allow late delivery',num_workshop_allowed:value=>`Allow up to ${value} workshops`,objective:()=> 'Use earliest completion'};
    options.forEach(option=>{
      const plan=option.plan,item=text('section');
      item.append(text('strong',Object.entries(option.required_changes).map(([field,value])=>labels[field]?.(value)||field).join('; ')));
      item.append(text('p',plan.allocation.map(p=>`${p.workshop_id}: ${p.pieces} pieces`).join(' + ')));
      item.append(text('p',`Estimated completion ${plan.estimated_delivery_date} · Cost ${plan.estimated_cost} · Weighted defect rate ${(100*plan.expected_defect_rate).toFixed(2)}%`));
      if(option.supported_mode==='offline')item.append(text('p','Split planning is currently supported in Offline mode only.'));
      node.append(item);
    });
    node.append(text('p','Your requirements have not changed. Send the changes you authorize, then review and confirm a new recommendation.','chat-notice'));
    return node;
  }
  function reviewChanges(changes){
    const node=text('details');node.append(text('summary','What changed since your review?'));
    const labels={allocation:'Workshop allocation',objective:'Objective',estimated_days:'Estimated days',estimated_delivery_date:'Completion date',estimated_cost:'Cost',expected_defect_rate:'Weighted defect rate',deadline_met:'Due date met',warnings:'Warnings',business_facts:'Business data'};
    const display=value=>Array.isArray(value)?value.map(v=>typeof v==='object'?`${v.workshop_id}: ${v.pieces} pieces (${v.estimated_days.toFixed(2)} days, cost ${v.estimated_cost})`:v).join('; '):value==null?'Unavailable':String(value);
    const formatted=(field,value)=>typeof value==='number'?(field==='expected_defect_rate'?`${(100*value).toFixed(2)}%`:value.toFixed(2)):display(value);
    changes.forEach(change=>node.append(text('p',`${labels[change.field]||change.field}: ${formatted(change.field,change.before)} → ${formatted(change.field,change.after)}`)));
    node.append(text('p','No allocation was committed by this attempt. Review the new plan before confirming.'));
    return node;
  }
  function decisionEvents(session,messages){
    const events=[{title:'Request created',when:session.created_at}],plans=new Set();
    let submitted=false,committed=false,cancelled=false;
    for(const message of messages){
      const meta=message.metadata||{};let title=null;
      if(message.role==='user'){
        title=meta.intent==='confirm_allocation'?'Confirmation requested':meta.intent==='reject_recommendation'?'Rejection requested':meta.intent==='cancel_task'?'Closure requested':submitted?'Message sent':'Request submitted';submitted=true;
      }else if(meta.committed){title='Allocation committed';committed=true;}
      else if(meta.intent==='reject_recommendation')title='Recommendation rejected';
      else if(meta.intent==='cancel_task'){title='Request closed';cancelled=true;}
      else if(meta.recommendation_id&&!plans.has(meta.recommendation_id)){title='Recommendation prepared';plans.add(meta.recommendation_id);}
      if(title)events.push({title,when:message.created_at});
    }
    if(session.task.state==='CONFIRMED'&&!committed)events.push({title:'Allocation confirmed',when:session.updated_at});
    if(session.task.state==='CANCELLED'&&!cancelled)events.push({title:'Marked not allocated',when:session.updated_at});
    if(session.status==='ARCHIVED')events.push({title:'Request archived',when:session.updated_at});
    return events;
  }
  const api={confirmation,canConfirm,stateLabel,text,request,card,alternatives,reviewChanges,decisionEvents};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  else root.ChatV2=api;
})(typeof globalThis!=='undefined'?globalThis:this);
