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
    if(recommendation.result.resolved_differences?.length)node.append(registeredDifferences(recommendation.result.resolved_differences));
    (result.allocation||[]).forEach(p=>node.append(text('p',`Workshop ${p.workshop_id} · ${p.workshop_name}: ${p.pieces} pieces`)));
    if(node.dataset)node.dataset.status=recommendation.status;
    if(root.DispatchUI){
      const U=root.DispatchUI,parts=result.allocation||[],total=parts.reduce((n,p)=>n+p.pieces,0),bar=text('div',null,'plan-parts');
      parts.forEach(p=>{const part=text('div',p.workshop_id,'plan-part');part.style.backgroundColor=U.color(p.workshop_id);part.style.flex=String(p.pieces/Math.max(1,total));part.append(text('small',`${U.number(p.pieces,0)} pcs`));bar.append(part);});node.append(bar);
      const metrics=text('dl',null,'plan-metrics');
      [['Completion',U.date(result.estimated_delivery_date)],['Estimated cost',`${U.number(result.estimated_cost,2)} units`],['Expected defects',typeof result.expected_defect_rate==='number'?`${U.number(result.expected_defect_rate*100,2)}%`:'—']].forEach(([label,value])=>{const item=text('div');item.append(text('dt',label),text('dd',value));metrics.append(item);});node.append(metrics);
    }else node.append(text('p',`Estimated completion ${result.estimated_delivery_date} · Estimated cost ${result.estimated_cost}`));
    if(result.warnings?.length)node.append(text('p',result.warnings.map(w=>({ESTIMATED_DEADLINE_MISS:'Estimated date exceeds the registered due date; the deadline is currently soft.',DUE_DATE_UNCONFIRMED:'No confirmed due date is available. Lateness and on-time delivery cannot be assessed.'}[w]||w)).join('; '),'chat-notice'));
    if(result.candidate_plans?.length){
      const details=text('details');details.append(text('summary','Compare complete candidate plans'));
      details.append(text('p',result.candidate_plan_scope||'Plans calculated under the current requirements.'));
      result.candidate_plans.forEach((plan,index)=>{
        const item=text('section');item.append(text('strong',index===0?'Recommended plan':'Alternative plan '+(index+1)));
        item.append(text('p',plan.allocation.map(p=>`${p.workshop_id} (${p.pieces} pieces)`).join(' + ')));
        item.append(text('p',`Completion ${plan.estimated_delivery_date} · Cost ${plan.estimated_cost} · Weighted defect rate ${(100*plan.expected_defect_rate).toFixed(2)}%`));
        item.append(text('p',plan.deadline_met==null?'No confirmed due date; deadline compliance cannot be assessed.':plan.deadline_met?'Meets the registered due date.':'Exceeds the registered due date.'));
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
  function inlineText(node,content){
    // Create text nodes only: model-supplied HTML and URLs are never executable.
    const parts=String(content).split(/(\*\*[^*\n]+\*\*|`[^`\n]+`)/g);
    parts.forEach(part=>node.append(part.startsWith('**')&&part.endsWith('**')?text('strong',part.slice(2,-2)):part.startsWith('`')&&part.endsWith('`')?text('code',part.slice(1,-1)):text('span',part)));
  }
  /** Render supported Markdown into a container; supplied HTML stays literal text. */
  function richText(node,content){
    content=String(content??'');
    node.replaceChildren();node.textContent='';
    if(!/[|]|\*\*|`/.test(content)){node.textContent=content;return;}
    const lines=String(content).split('\n'),cells=line=>line.trim().replace(/^\||\|$/g,'').split('|').map(v=>v.trim());
    const separator=line=>/^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line||'');
    for(let i=0;i<lines.length;i++){
      if(lines[i].includes('|')&&separator(lines[i+1])){
        const wrap=text('div',null,'chat-table-scroll'),table=text('table'),head=text('thead'),row=text('tr');
        table.setAttribute('aria-label','Comparison');
        cells(lines[i]).forEach(value=>{const cell=text('th');cell.setAttribute('scope','col');inlineText(cell,value);row.append(cell);});
        head.append(row);table.append(head);const body=text('tbody');i+=2;
        while(i<lines.length&&lines[i].includes('|')&&lines[i].trim()){
          const tr=text('tr');cells(lines[i]).forEach(value=>{const cell=text('td');inlineText(cell,value);tr.append(cell);});body.append(tr);i++;
        }
        i--;table.append(body);wrap.append(table);node.append(wrap);
      }else{const line=text('div');inlineText(line,lines[i]||'\u00a0');node.append(line);}
    }
  }
  /** Display verified offers; selection requests a fresh preview, never commitment. */
  function workshopOptions(options,onSelect){
    const node=text('section'),wrap=text('div',null,'chat-table-scroll'),table=text('table',null,'chat-options-table');
    node.append(text('h3','Other workshop options'));table.setAttribute('aria-label','Workshop alternatives');
    const head=text('thead'),header=text('tr');
    ['Option / workshop','Pieces','Estimated delivery','Against due date','Cost','Defect rate','Required changes',''].forEach(label=>{const th=text('th',label);th.setAttribute('scope','col');header.append(th);});
    head.append(header);table.append(head);const body=text('tbody');
    options.forEach((option,index)=>{
      const p=option.plan,part=p.allocation[0],row=text('tr');
      const changes=Object.entries(option.required_changes).map(([field,value])=>({preferred_workshop:value?`Use ${value} as the sole workshop`:'Remove the sole-workshop requirement',deadline_required:'Allow late delivery',objective:'Use earliest completion',num_workshop_allowed:`Allow up to ${value} workshops`}[field]||'Review this requirement')).join('; ');
      const timing=p.delay_days==null?'Due date unconfirmed':p.delay_days===0?'On time':`${Math.abs(p.delay_days)} day(s) ${p.delay_days<0?'early':'late'}`;
      [`Option ${index+1}: ${part.workshop_name||part.workshop_id} (${part.workshop_id})`,part.pieces,p.estimated_delivery_date,timing,Number(p.estimated_cost).toFixed(2),`${(100*p.expected_defect_rate).toFixed(2)}%`,changes].forEach(value=>row.append(text('td',value)));
      const action=text('td'),button=text('button',`Use option ${index+1}`,'secondary');button.type='button';button.disabled=!onSelect;
      button.addEventListener('click',()=>onSelect?.(option,index));action.append(button);row.append(action);body.append(row);
    });
    table.append(body);wrap.append(table);node.append(wrap);
    node.append(text('p','Your requirements have not changed. Select an option to generate a fresh recommendation, then review and confirm it.','chat-notice'));
    return node;
  }
  function alternatives(options,onSelect){
    if(options.length&&options.every(o=>o.offer_type==='workshop_candidate'))return workshopOptions(options,onSelect);
    const node=text('section');node.append(text('h3','Options requiring your authorization'));
    const labels={preferred_workshop:()=> 'Remove the required sole workshop',deadline_required:()=> 'Allow late delivery',num_workshop_allowed:value=>`Allow up to ${value} workshops`,objective:()=> 'Use earliest completion'};
    options.forEach((option,index)=>{
      const plan=option.plan,item=text('section');
      item.append(text('strong',`Option ${index+1}: `+Object.entries(option.required_changes).map(([field,value])=>labels[field]?.(value)||field).join('; ')));
      item.append(text('p',plan.allocation.map(p=>`${p.workshop_id}: ${p.pieces} pieces`).join(' + ')));
      item.append(text('p',`Estimated completion ${plan.estimated_delivery_date} · Cost ${plan.estimated_cost} · Weighted defect rate ${(100*plan.expected_defect_rate).toFixed(2)}%`));
      if(option.supported_mode==='offline')item.append(text('p','Split planning is currently supported in Offline mode only.'));
      node.append(item);
    });
    node.append(text('p','Your requirements have not changed. Accept a specific option to generate a fresh recommendation, then review and confirm it.','chat-notice'));
    return node;
  }
  function registeredDifferences(differences){
    const node=text('section',null,'chat-notice');
    node.append(text('strong','Registered order details used'));
    const labels={customer:'Customer',product:'Product',category:'Category',pieces:'Quantity',order_date:'Order date',due_date:'Due date'};
    differences.forEach(d=>node.append(text('p',`${labels[d.field]||d.field}: your message ${d.supplied}; registered value ${d.recorded}.`)));
    node.append(text('p','This plan uses the registered values. Check that this is the intended order before confirming.'));
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
      else if(meta.intent==='order_registration')title=({CREATED:'Order registered',UPDATED:'Order details updated',REJECTED:'Order changes declined'}[meta.order_decision_outcome]||(meta.order_decision_outcome?'Order decision recorded':{REVIEW:'Order details checked',COLLECTING:'Order details requested',COMPLETED:'Existing order matched',CANCELLED:'Order registration cancelled'}[meta.registration_status]));
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
  const api={richText,confirmation,canConfirm,stateLabel,text,request,card,alternatives,registeredDifferences,reviewChanges,decisionEvents};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  else root.ChatV2=api;
})(typeof globalThis!=='undefined'?globalThis:this);
