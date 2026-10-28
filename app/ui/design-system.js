/* Shared presentation only. Business facts and mutations remain on the server. */
(function(root){
  'use strict';
  const colors=['#2F6DBF','#D9622E','#18A076','#D99A0B','#D6668F','#2E8A2E','#6352C8','#C9403F'];
  const names={READY:'Unassigned',UNASSIGNED:'Unassigned',WORKING:'In production',COMPLETED:'Completed',LAPSED:'Lapsed',ACTIVE:'Active',SUSPENDED:'Suspended',CLOSED:'Closed',COLLECTING:'Collecting details',BLOCKED:'Needs clarification',READY_TO_PLAN:'Ready to calculate',RECOMMENDED:'Ready for review',CONFIRMED:'Allocated',CANCELLED:'Not allocated'};
  const paths={grid:'M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z',chat:'M21 11a8 8 0 0 1-8 8H7l-4 3V11a9 9 0 0 1 18 0ZM7 9h10M7 13h7',doc:'M8 3h8l4 4v14H4V3h4M14 3v6h6M8 13h8M8 17h5',factory:'M3 21V10l6 4V9l6 4V4h5v17H3M7 17v1M12 17v1M17 17v1',clock:'M12 3a9 9 0 1 0 0 18 9 9 0 1 0 0-18M12 7v5l3 2',check:'M5 12l4 4L19 6',alert:'m12 3 10 18H2L12 3ZM12 9v5M12 17v1',arrow:'M5 12h14m-5-5 5 5-5 5',plus:'M12 5v14M5 12h14',calendar:'M4 5h16v16H4zM8 3v4M16 3v4M4 10h16',logout:'M9 4H4v16h5M10 12h11m-4-4 4 4-4 4',shield:'m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3ZM8 12l3 3 5-6',search:'M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14m5 12 6 6',eye:'M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Zm10-3a3 3 0 1 0 0 6 3 3 0 0 0 0-6'};
  function node(tag,text,cls){const n=document.createElement(tag);if(text!=null)n.textContent=String(text);if(cls)n.className=cls;return n;}
  function icon(name){const s=document.createElementNS('http://www.w3.org/2000/svg','svg');s.setAttribute('viewBox','0 0 24 24');s.setAttribute('class','ui-icon');s.setAttribute('aria-hidden','true');const p=document.createElementNS(s.namespaceURI,'path');p.setAttribute('d',paths[name]||paths.doc);s.append(p);return s;}
  function color(id){const i=Number(String(id).replace(/^W/,''));return colors[Number.isInteger(i)&&i>0?(i-1)%colors.length:0];}
  function swatch(id,large=false){const n=node('span',null,'swatch'+(large?' swatch-large':''));n.style.setProperty('--swatch',color(id));n.setAttribute('aria-hidden','true');return n;}
  function workshop(w,large=false){const n=node('span',null,'workshop-name');n.append(swatch(w.workshop_id,large));const label=node('span');label.append(node('b',w.name||w.workshop_id));if(large)label.append(node('small',w.workshop_id));n.append(label);return n;}
  const number=(n,d=1)=>typeof n==='number'?n.toLocaleString('en-SG',{maximumFractionDigits:d}):'—';
  function date(value){if(!value)return '—';const d=new Date(String(value).slice(0,10)+'T00:00:00Z');return Number.isNaN(+d)?'—':d.toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric',timeZone:'UTC'});}
  function overdue(order,businessDate){return !!order.due_date&&!!businessDate&&!['COMPLETED','LAPSED'].includes(order.state)&&order.due_date<businessDate;}
  function orderGroup(order,businessDate){return order.state==='COMPLETED'?'completed':order.state==='LAPSED'?'lapsed':overdue(order,businessDate)?'delayed':order.state==='WORKING'?'production':'unassigned';}
  function oldest(items){return [...items].sort((a,b)=>String(a.created_at||a.order_date||'').localeCompare(String(b.created_at||b.order_date||''))||(a.cursor||0)-(b.cursor||0)||String(a.order_id||'').localeCompare(String(b.order_id||'')));}
  function pending(items){return oldest(items.filter(s=>s.status==='OPEN'&&!['CONFIRMED','CANCELLED'].includes(s.task_state)));}
  function badge(value,label){const tone=['COMPLETED','ACTIVE','CONFIRMED'].includes(value)?'good':['LAPSED','CLOSED','SUSPENDED','DELAYED'].includes(value)?'bad':['BLOCKED','UNASSIGNED','READY'].includes(value)?'warn':'info';return node('span',label||names[value]||value,'tag '+tone);}
  function table(target,headers,rows,empty='No records to display.'){
    target.replaceChildren();const t=node('table'),head=t.createTHead().insertRow();
    headers.forEach(h=>{const th=node('th');th.scope='col';th.append(typeof h==='string'?document.createTextNode(h):h);head.append(th);});
    const body=t.createTBody();rows.forEach(values=>{const row=body.insertRow();values.forEach(v=>{const cell=row.insertCell();if(v instanceof Node)cell.append(v);else cell.textContent=v??'—';});});
    if(!rows.length){const td=body.insertRow().insertCell();td.colSpan=headers.length;td.append(node('p',empty,'table-empty'));}target.append(t);return t;
  }
  function button(label,fn,cls='secondary'){const b=node('button',label,cls);b.type='button';b.addEventListener('click',fn);return b;}
  function kpis(target,values){target.replaceChildren(...values.map(([label,value,detail,symbol])=>{const cell=node('div',null,'stat'),title=node('div',null,'stat-label');title.append(icon(symbol),node('span',label));cell.append(title,node('strong',value),node('p',detail,'small'));return cell;}));}
  function initialize(){
    document.querySelectorAll('[data-icon]').forEach(n=>n.replaceChildren(icon(n.dataset.icon)));
    document.querySelectorAll('[data-password-toggle]').forEach(b=>b.addEventListener('click',()=>{const input=document.getElementById(b.dataset.passwordToggle),show=input.type==='password';input.type=show?'text':'password';b.setAttribute('aria-label',show?'Hide password':'Show password');b.setAttribute('aria-pressed',String(show));}));
  }
  const api={node,icon,color,swatch,workshop,number,date,overdue,orderGroup,oldest,pending,badge,table,button,kpis};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;else{root.DispatchUI=api;initialize();}
})(typeof globalThis!=='undefined'?globalThis:this);
