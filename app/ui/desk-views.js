/* Reference-design views over the existing authenticated read APIs. */
(function(root){
  'use strict';
  const U=typeof module!=='undefined'&&module.exports?require('./design-system.js'):DispatchUI,$=id=>document.getElementById(id);
  let dashboardEpoch=0,notesEpoch=0,orderData=null,trackOrder=null,showAll=false,sortKey='order_date',sortDirection=1;
  function link(label,href,cls=''){const a=U.node('a',label,cls);a.href=href;return a;}
  function dateAfter(value,days){if(!value||!Number.isFinite(days))return '—';const d=new Date(value+'T00:00:00Z');d.setUTCDate(d.getUTCDate()+Math.ceil(days));return U.date(d.toISOString());}
  async function pages(url){let items=[],cursor=0;do{const result=await ChatV2.request(`${url}?after=${cursor}&limit=100`);items.push(...result.items);cursor=result.next_cursor;}while(cursor!=null);return items;}
  function dashboardStats(data,requests){
    const orders=data.orders||[],workshops=data.workshops||[],late=orders.filter(o=>U.overdue(o,data.business_date));
    U.kpis($('stats'),[
      ['Pending requests',requests===null?'—':String(requests.length),requests===null?'Request queue unavailable':'Your active conversations','chat'],
      ['Completed orders',String(orders.filter(o=>o.state==='COMPLETED').length),`Of ${orders.length} registered orders`,'check'],
      ['Overdue orders',String(late.length),`${U.number(late.reduce((n,o)=>n+o.pieces-o.completed_pieces,0),0)} pieces remaining`,'alert'],
      ['Average waiting time',requests?.length?`${U.number(requests.reduce((n,r)=>n+Math.max(0,(Date.now()-Date.parse(r.created_at))/3600000),0)/requests.length)} h`:requests===null?'—':'0 h','Across your pending requests','clock'],
      ['Active workshops',`${workshops.filter(w=>w.status==='ACTIVE').length} / ${workshops.length}`,'Available for new allocations','factory'],
    ]);
  }
  async function dashboard(data,user){
    const token=++dashboardEpoch;
    $('dashboard-greeting').textContent=`Welcome, ${user?.auth_required?user.username:'dispatcher'}`;
    $('dashboard-subtitle').textContent='Keep requests moving and every workshop in view.';
    $('header-business-date').textContent=U.date(data.business_date);
    $('account-avatar').textContent=(user?.username||'D').slice(0,2).toUpperCase();
    dashboardStats(data,[]);
    const workshops=data.workshops||[];
    U.table($('dashboard-workshops'),['Workshop','Queue','Next available'],workshops.map(w=>[
      U.workshop(w),w.status==='ACTIVE'?`${U.number(w.queue_days)} days`:U.badge(w.status),
      w.status==='ACTIVE'?dateAfter(data.business_date,w.queue_days):'—',
    ]));
    const late=(data.orders||[]).filter(o=>U.overdue(o,data.business_date)).sort((a,b)=>a.due_date.localeCompare(b.due_date)||a.order_id.localeCompare(b.order_id));
    U.table($('overdue-orders'),['Order','Overdue by','Customer','Due date','Status','Remaining'],late.slice(0,8).map(o=>[
      link(o.order_id,'#production?order='+encodeURIComponent(o.order_id)),
      U.badge('DELAYED',`${Math.round((Date.parse(data.business_date)-Date.parse(o.due_date))/86400000)} days`),o.customer,U.date(o.due_date),U.badge(o.state),U.number(o.pieces-o.completed_pieces,0),
    ]),'No overdue orders.');
    $('overdue-count').textContent=late.length?`Showing ${Math.min(8,late.length)} of ${late.length}`:'All orders are within their due date';
    const status=$('dashboard-order-status');status.replaceChildren();
    const groups=[['completed','Completed','#18A076'],['production','In production','#2F6DBF'],['delayed','Delayed','#C9403F'],['unassigned','Unassigned','#D99A0B'],['lapsed','Lapsed','#8A8F9C']];
    for(const [key,label,color] of groups){const count=data.orders.filter(o=>U.orderGroup(o,data.business_date)===key).length;
      const row=U.node('div',null,'status-line'),track=U.node('div',null,'status-track'),fill=U.node('div',null,'status-fill');fill.style.width=`${data.orders.length?count/data.orders.length*100:0}%`;fill.style.background=color;track.append(fill);row.append(U.node('span',label),track,U.node('b',count));status.append(row);}
    status.append(U.node('p',`${data.orders.length} registered orders. Delayed orders are counted separately from their production status.`,'status-caption'));
    try{
      const requests=U.pending(await pages('/api/chat/sessions'));if(token!==dashboardEpoch)return;
      dashboardStats(data,requests);$('request-nav-count').textContent=requests.length;$('request-nav-count').hidden=!requests.length;
      $('pending-meta').textContent=`Oldest first · ${requests.length} waiting`;
      const byId=new Map(data.orders.map(o=>[o.order_id,o]));
      U.table($('pending-requests'),['','Request / order','Product','Pieces','Status',''],requests.slice(0,4).map((r,i)=>{
        const order=byId.get(r.order_id)||{},title=U.node('div');title.append(U.node('strong',r.order_id||'New request'),U.node('small',r.title));
        return [U.node('span',i+1,'queue-position'),title,order.product||'—',U.number(order.pieces,0),U.badge(r.task_state),link('Open','/chat?session='+encodeURIComponent(r.session_id),'button secondary')];
      }),'No pending requests. Open Requests to start a conversation.');
    }catch(e){if(token!==dashboardEpoch)return;dashboardStats(data,null);$('pending-meta').textContent='Could not load requests';$('pending-requests').replaceChildren(U.node('p',e.message,'panel-body'));}
  }
  function workshopIds(order,data){return (data.workshops||[]).filter(w=>(w.orders||[]).some(a=>a.order_id===order.order_id));}
  function filteredOrders(data,{query='',groups=null,all=false,key='order_date',direction=1}={}){
    const matches=(data.orders||[]).filter(o=>[o.order_id,o.customer,o.product].join(' ').toLowerCase().includes(query.toLowerCase()));
    const open=U.oldest(matches.filter(o=>o.state!=='COMPLETED'&&(!groups||groups.includes(U.orderGroup(o,data.business_date)))));
    const sort=items=>[...items].sort((a,b)=>{const x=a[key]??'',y=b[key]??'';return (typeof x==='number'&&typeof y==='number'?x-y:String(x).localeCompare(String(y),undefined,{numeric:true}))*direction||a.order_id.localeCompare(b.order_id);});
    return {open:sort(all?open:open.slice(0,20)),completed:sort(matches.filter(o=>o.state==='COMPLETED')),total:open.length};
  }
  function renderOrders(data,onTrack){orderData=data;trackOrder=onTrack;drawOrders();}
  function drawOrders(){
    if(!orderData)return;
    const groups=[...document.querySelectorAll('[data-order-group]:checked')].map(n=>n.dataset.orderGroup);
    const result=filteredOrders(orderData,{query:$('orders-search').value.trim(),groups,all:showAll,key:sortKey,direction:sortDirection});
    function headers(){return [['Order','order_id'],['Client','customer'],['Product','product'],['Pieces','pieces'],['Received','order_date'],['Due','due_date'],['Status','state'],['Workshop',null],['Notes',null]].map(([label,key])=>{
      if(!key)return label;const b=U.button(label+(key===sortKey?(sortDirection===1?' ↑':' ↓'):''),()=>{sortDirection=sortKey===key?-sortDirection:1;sortKey=key;drawOrders();},'sort-button');b.setAttribute('aria-label','Sort by '+label.toLowerCase());return b;
    });}
    const row=o=>{const ws=workshopIds(o,orderData),name=U.node('div');if(ws.length)ws.forEach(w=>name.append(U.workshop(w)));else name.append(U.node('span',o.state==='COMPLETED'?'Not recorded':'Not assigned','muted'));
      const status=U.node('div');status.append(U.badge(o.state));if(U.overdue(o,orderData.business_date))status.append(U.badge('DELAYED','Delayed'));
      return [U.button(o.order_id,()=>trackOrder(o.order_id),'quiet'),o.customer,o.product,U.number(o.pieces,0),U.date(o.order_date),U.date(o.due_date),status,name,U.button('View',()=>notes(o),'secondary')];};
    const table=U.table($('orders-open'),headers(),result.open.map(row),'No orders match these filters.');table.className='order-register';
    const completed=U.table($('orders-completed'),headers(),result.completed.map(row),'No completed orders match.');completed.className='order-register';
    [table,completed].forEach(t=>{const index=['order_id','customer','product','pieces','order_date','due_date','state'].indexOf(sortKey);if(index>=0)t.tHead.rows[0].cells[index].setAttribute('aria-sort',sortDirection===1?'ascending':'descending');});
    $('orders-visible-count').textContent=`Showing ${result.open.length} of ${result.total} non-completed orders`;
    $('orders-show-all').hidden=result.total<=20;$('orders-show-all').textContent=showAll?'Show oldest 20':'Show all';
    $('completed-orders-title').textContent=`Completed orders (${result.completed.length})`;
  }
  async function notes(order){
    const token=++notesEpoch;$('notes-title').textContent=`Order ${order.order_id}`;$('order-notes').replaceChildren(U.node('p','Loading decisions…','muted'));$('notes-dialog').showModal();
    try{
      let items=[],page=1,total;do{const data=await ChatV2.request(`/api/audit?q=${encodeURIComponent(order.order_id)}&page=${page}&page_size=100`);items.push(...data.items);total=data.total;page++;}while(items.length<total);
      if(token!==notesEpoch)return;
      const target=$('order-notes');target.replaceChildren();target.append(U.node('p',`Current status: ${U.badge(order.state).textContent}`));
      const records=items.filter(r=>r.order_id===order.order_id);
      if(!records.length)target.append(U.node('p','No decision has been recorded for this order.','muted'));
      records.forEach(r=>{const article=U.node('article');article.append(U.node('strong',r.status),U.node('small',`${new Date(r.timestamp).toLocaleString('en-SG')} · ${r.actor||'Actor not recorded'}`),U.node('p',r.summary||r.result?.message||'No explanation recorded.'));if(r.original_message)article.append(U.node('blockquote',r.original_message));target.append(article);});
    }catch(e){if(token===notesEpoch)$('order-notes').replaceChildren(U.node('p',e.message,'notice error'));}
  }
  function decisionLog(records){return records.map(r=>[`${r.order_id||'No order'} · ${r.status} · ${r.timestamp}`,`Recorded by: ${r.actor||'Not recorded'}`,`Request: ${r.original_message||'Not recorded'}`,`Decision: ${r.summary||r.result?.message||'No explanation recorded.'}`,`Record: ${r.request_id}`].join('\n')).join('\n\n')+'\n';}
  async function download(){const button=$('download-decisions');button.disabled=true;try{const data=await ChatV2.request('/api/audit/export?format=json'),url=URL.createObjectURL(new Blob([decisionLog(data.items)],{type:'text/plain;charset=utf-8'}));const a=link('Download',url);a.download='decision_logs.txt';document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(e){$('orders-notice').textContent=e.message;}finally{button.disabled=false;}}
  function workshops(items,data){
    const active=items.filter(w=>w.status==='ACTIVE'),capacity=active.reduce((n,w)=>n+w.capacity,0),average=active.length?active.reduce((n,w)=>n+w.queue_days,0)/active.length:0;
    U.kpis($('workshop-summary'),[['Daily capacity',`${U.number(capacity,0)} pcs`,`${active.length} active workshops in this view`,'factory'],['Average queue',`${U.number(average)} days`,'Across active workshops in this view','clock'],['Earliest available',active.length?dateAfter(data.business_date,Math.min(...active.map(w=>w.queue_days))):'—','Based on the current queue','calendar'],['Not taking orders',String(items.length-active.length),'Suspended or closed workshops','alert']]);
    const table=U.table($('workshops-table'),['Workshop','Makes','Daily capacity','Queue','Pickup lead','Next available','Unit cost','Defect rate','Notes',''],items.map(w=>{
      const name=U.node('div');name.append(U.workshop(w,true),U.badge(w.status));const capability=U.node('div',w.makes.map(m=>m==='TOPS'?'Tops':'Accessories').join(', '));if(w.max_batch)capability.append(U.node('small',`Max batch ${U.number(w.max_batch,0)} pcs`));
      return [name,capability,`${U.number(w.capacity,0)} pcs`,`${U.number(w.queue_days)} d`,`${w.lead_days} d`,w.status==='ACTIVE'?dateAfter(data.business_date,w.queue_days):'—',`${U.number(w.cost,2)} units`,`${U.number(w.defect_rate*100,2)}%`,U.node('div',w.notes||'—','notes'),U.button('Show production queue',()=>workshopQueue(w,data),'secondary')];
    }),'No workshops match these filters.');table.className='workshop-table';
  }
  function workshopQueue(w,data){
    $('workshop-queue-title').textContent=`${w.name}: production queue`;
    $('workshop-queue-description').textContent=`${U.number(w.queue_days)} days of queued work. Named assignments below are shown by registered order date; imported workload may not have named orders.`;
    const byId=new Map(data.orders.map(o=>[o.order_id,o]));
    const rows=U.oldest((w.orders||[]).map(a=>({...byId.get(a.order_id),...a}))).map((o,i)=>{
      const name=U.node('div');name.append(link(o.order_id,'#production?order='+encodeURIComponent(o.order_id)));if(workshopIds(o,data).length>1)name.append(U.node('span','Split','tag info split-label'));
      return [i+1,name,o.product||'—',U.number(o.remaining_pieces,0),U.badge(o.state||'WORKING'),U.date(o.order_date),U.date(o.due_date)];
    });
    U.table($('workshop-queue-table'),['','Order','Product','Remaining','Status','Received','Due'],rows,'No active named assignments. Imported workload may still contribute to the queue.');$('workshop-queue-dialog').showModal();
  }
  function initialize(){
    $('orders-search').addEventListener('input',()=>{showAll=false;drawOrders();});document.querySelectorAll('[data-order-group]').forEach(n=>n.addEventListener('change',()=>{showAll=false;drawOrders();}));
    $('orders-show-all').addEventListener('click',()=>{showAll=!showAll;drawOrders();});$('download-decisions').addEventListener('click',download);
    $('workshop-queue-table').addEventListener('click',e=>{if(e.target.closest('a'))$('workshop-queue-dialog').close();});
  }
  const api={dashboard,renderOrders,workshops,filteredOrders,decisionLog};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;else{root.DeskViews=api;initialize();}
})(typeof globalThis!=='undefined'?globalThis:this);
