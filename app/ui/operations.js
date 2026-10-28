/* Read-only visualizations. All business values are inserted as text. */
(function(root){
  'use strict';
  const palette={ACTIVE:'#217567',SUSPENDED:'#bb7a28',CLOSED:'#879498',READY:'#5e92a2',UNASSIGNED:'#bb7a28',WORKING:'#217567',COMPLETED:'#6576ac',LAPSED:'#a46b68'};
  const names={ACTIVE:'Active',SUSPENDED:'Suspended',CLOSED:'Closed',READY:'Ready to allocate',UNASSIGNED:'Unassigned',WORKING:'In production',COMPLETED:'Completed',LAPSED:'Lapsed'};
  const format=(value,digits=2)=>Number(value).toLocaleString('en-SG',{maximumFractionDigits:digits});
  const node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
  const svgNode=(tag,attrs={})=>{const n=document.createElementNS('http://www.w3.org/2000/svg',tag);Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,v));return n;};
  const paths={registered:'M8 3h8l3 3v15H5V3h3M8 10h8M8 14h8M8 18h5',allocated:'M4 6h16M4 12h10M4 18h10M17 10l4 4-4 4',production:'M3 21V10l6 4V9l6 4V4h5v17H3M7 17v1M12 17v1M17 17v1',completed:'M5 12l4 4L19 6',cancel:'M6 6l12 12M18 6L6 18',reassign:'M4 7h14l-3-3M20 17H6l3 3',lapse:'M12 3v10M12 18v2',clock:'M12 3a9 9 0 1 0 0 18 9 9 0 1 0 0-18M12 7v5l3 2'};
  function icon(key){const s=svgNode('svg',{viewBox:'0 0 24 24',width:22,height:22,fill:'none',stroke:'currentColor','stroke-width':1.7,'stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true'});s.append(svgNode('path',{d:paths[key]||paths.clock}));return s;}
  function summarize(data){
    const workshops=data.workshops||[],orders=data.orders||[];
    return {active:workshops.filter(w=>w.status==='ACTIVE').length,totalWorkshops:workshops.length,
      working:orders.filter(o=>o.state==='WORKING').length,completed:orders.filter(o=>o.state==='COMPLETED').length,
      outstanding:workshops.reduce((sum,w)=>sum+(w.orders||[]).reduce((n,o)=>n+o.remaining_pieces,0),0),
      states:Object.fromEntries(Object.keys(palette).map(k=>[k,orders.filter(o=>o.state===k).length]))};
  }
  function scales(values){const max=Math.max(0,...values.filter(Number.isFinite));return values.map(v=>max?Math.max(0,v)/max*100:0);}
  let tooltip,activeTip,activeShow;
  function hideTip(){if(tooltip)tooltip.hidden=true;if(activeTip)activeTip.removeAttribute('aria-describedby');activeTip=null;}
  function tip(target,title,lines){
    target.setAttribute('tabindex','0');target.setAttribute('aria-label',[title,...lines].join('. '));
    const show=event=>{
      if(!tooltip){tooltip=node('div',null,'ops-tooltip');tooltip.id='ops-tooltip';tooltip.setAttribute('role','tooltip');document.body.append(tooltip);
        document.addEventListener('keydown',e=>{if(e.key==='Escape')hideTip();});window.addEventListener('scroll',()=>{if(activeTip?.matches(':hover, :focus-visible'))activeShow();else hideTip();},true);window.addEventListener('resize',hideTip);}
      if(activeTip&&activeTip!==target)activeTip.removeAttribute('aria-describedby');activeTip=target;activeShow=show;
      tooltip.replaceChildren(node('strong',title),...lines.map(line=>node('span',line)));tooltip.hidden=false;
      target.setAttribute('aria-describedby',tooltip.id);
      const box=target.getBoundingClientRect(),x=event?.clientX??(box.left+box.width/2),y=event?.clientY??box.bottom;
      const width=tooltip.offsetWidth,height=tooltip.offsetHeight;
      tooltip.style.left=Math.max(8,Math.min(x+12,window.innerWidth-width-8))+'px';
      tooltip.style.top=Math.max(8,y+height+20>window.innerHeight?y-height-12:y+12)+'px';
    };
    target.addEventListener('pointerenter',show);target.addEventListener('pointermove',show);
    target.addEventListener('pointerleave',hideTip);target.addEventListener('focus',()=>show());
    target.addEventListener('blur',hideTip);target.addEventListener('click',show);
  }
  function card(title,subtitle){const c=node('section',null,'panel ops-chart'),heading=node('div',null,'ops-chart-heading');heading.append(node('h2',title),node('p',subtitle,'muted small'));c.append(heading);return c;}
  function donut(workshops){
    const c=card('Workshop availability','Operating status across the workshop network.'),body=node('div',null,'ops-donut-layout');
    const svg=svgNode('svg',{viewBox:'0 0 220 220',class:'ops-donut','aria-label':'Workshop availability chart',role:'group'});
    svg.append(svgNode('circle',{cx:110,cy:110,r:78,fill:'none',stroke:'#edf1ee','stroke-width':26}));
    const legend=node('div',null,'ops-legend'),total=workshops.length;let offset=0;
    const statuses=[...new Set(['ACTIVE','SUSPENDED','CLOSED',...workshops.map(w=>w.status)])];
    for(const status of statuses){const group=workshops.filter(w=>w.status===status),count=group.length,color=palette[status]||'#879498';
      if(count){const circle=svgNode('circle',{cx:110,cy:110,r:78,fill:'none',stroke:color,'stroke-width':26,pathLength:100,'stroke-dasharray':`${count/total*100} ${100-count/total*100}`,'stroke-dashoffset':-offset,transform:'rotate(-90 110 110)',class:'ops-segment'});
        tip(circle,names[status]||status,[`${count} of ${total} workshops · ${format(count/total*100,1)}%`,group.map(w=>`${w.workshop_id} ${w.name}`).join(', ')]);svg.append(circle);offset+=count/total*100;}
      const line=node('button',null,'ops-legend-item');line.type='button';const dot=node('span',null,'ops-dot');dot.style.background=color;
      line.append(dot,node('span',names[status]||status),node('strong',String(count)));tip(line,names[status]||status,[`${count} workshops`,group.map(w=>w.name).join(', ')||'No workshops']);legend.append(line);
    }
    const number=svgNode('text',{x:110,y:112,'text-anchor':'middle',class:'ops-donut-number'});number.textContent=String(total);
    const label=svgNode('text',{x:110,y:137,'text-anchor':'middle',class:'ops-donut-label'});label.textContent='workshops';svg.append(number,label);body.append(svg,legend);c.append(body);return c;
  }
  function bars(title,subtitle,workshops,key,unit,color,extra){
    const c=card(title,subtitle),list=node('div',null,'ops-bars'),values=workshops.map(w=>key(w)),widths=scales(values);
    if(!workshops.length)list.append(node('p','No workshops available.','muted'));
    workshops.forEach((w,i)=>{const row=node('button',null,'ops-bar-row');row.type='button';row.dataset.workshop=w.workshop_id;
      const label=node('span',null,'ops-bar-label');label.append(node('strong',w.workshop_id),node('span',w.name));
      const track=node('span',null,'ops-bar-track'),fill=node('span',null,'ops-bar-fill');fill.style.width=widths[i]+'%';fill.style.background=color;track.append(fill);
      row.append(label,track,node('span',`${format(values[i])}${unit}`,'ops-bar-value'));
      tip(row,`${w.name} · ${w.workshop_id}`,[`${format(values[i])}${unit}`,`Status: ${names[w.status]||w.status}`,...extra(w)]);list.append(row);});
    c.append(list);return c;
  }
  function renderStats(target,data){const s=summarize(data);target.replaceChildren();
    [['Active workshops',`${s.active} / ${s.totalWorkshops}`,'Available for allocation','production'],['In production',format(s.working,0),'Orders with active assignments','allocated'],['Outstanding pieces',format(s.outstanding,0),'Remaining in recorded allocations','clock'],['Completed orders',format(s.completed,0),'Includes imported completion records','completed']].forEach(([label,value,detail,key])=>{
      const c=node('div',null,'stat'),h=node('div',label,'stat-label');h.append(icon(key));c.append(h,node('strong',value),node('p',detail,'small'));target.append(c);});
  }
  function renderDashboard(target,data,onTrack){hideTip();target.replaceChildren();const workshops=data.workshops||[];
    const priority={WORKING:0,READY:1,UNASSIGNED:1,COMPLETED:2,LAPSED:3};
    const ordered=[...(data.orders||[])].sort((a,b)=>(priority[a.state]??4)-(priority[b.state]??4)||a.due_date.localeCompare(b.due_date)||a.order_id.localeCompare(b.order_id));
    const grid=node('div',null,'ops-chart-grid');grid.append(donut(workshops),
      bars('Workshop workload','Calendar days queued, including imported workload.',workshops,w=>w.queue_days,' days','#3c8276',w=>[`${format(w.capacity,0)} pieces / day`,`${(w.orders||[]).length} recorded active orders`,`${format((w.orders||[]).reduce((n,o)=>n+o.remaining_pieces,0),0)} remaining pieces`]),
      bars('Production quality','Registered expected defect rate · lower is better.',workshops,w=>w.defect_rate*100,' %','#8c9a63',w=>['Planning estimate, not measured inspection results.']),
      bars('Cost comparison','Registered unit price · cost units per piece.',workshops,w=>w.cost,' units','#6e88a6',w=>['Quoted rate, not invoiced or realized spending.']));
    target.append(grid);
    const panel=node('section',null,'panel ops-orders'),heading=node('div',null,'panel-heading');heading.append(node('div','Follow every order','ops-section-title'),node('span','Select an order to view its production trail.','muted small'));panel.append(heading);
    const controls=node('div',null,'ops-order-controls'),search=node('input'),filter=node('select');search.type='search';search.placeholder='Order ID, customer or product';search.setAttribute('aria-label','Search tracked orders');search.id='tracking-search';filter.setAttribute('aria-label','Filter tracked orders');filter.id='tracking-filter';
    for(const [value,label]of [['','All statuses'],...Object.entries(names).filter(([key])=>!['ACTIVE','SUSPENDED','CLOSED'].includes(key))]){const option=node('option',label);option.value=value;filter.append(option);}
    controls.append(search,filter);panel.append(controls);
    const stages=node('div',null,'ops-order-states'),summary=summarize(data);
    [['READY','registered'],['WORKING','production'],['COMPLETED','completed'],['LAPSED','lapse']].forEach(([key,symbol])=>{const b=node('button',null,'ops-state-button');b.type='button';b.append(icon(symbol),node('span',names[key]),node('strong',String(summary.states[key])));b.addEventListener('click',()=>{filter.value=key;limit=8;render();});stages.append(b);});panel.append(stages);
    const list=node('div',null,'ops-order-list'),footer=node('div',null,'panel-footer'),count=node('span',null,'muted small'),more=node('button','Show more','quiet');more.type='button';let limit=8;
    function render(){list.replaceChildren();const query=search.value.trim().toLowerCase(),orders=ordered.filter(o=>(!filter.value||o.state===filter.value)&&(!query||[o.order_id,o.customer,o.product].join(' ').toLowerCase().includes(query)));
      orders.slice(0,limit).forEach(o=>{const row=node('button',null,'ops-order-row');row.type='button';row.dataset.orderId=o.order_id;
        const title=node('span',null,'ops-order-name');title.append(node('strong',o.order_id),node('small',`${o.customer} · ${o.product}`));
        const progress=node('span',null,'ops-order-progress'),bar=node('progress');bar.max=o.pieces;bar.value=o.completed_pieces;bar.setAttribute('aria-label',`${o.order_id}: ${o.completed_pieces} of ${o.pieces} pieces completed`);progress.append(bar,node('small',`${format(o.completed_pieces,0)} / ${format(o.pieces,0)} pieces`));
        const status=node('span',names[o.state]||o.state,'ops-status');status.style.setProperty('--status-color',palette[o.state]||'#879498');
        row.append(title,status,progress,node('span',`Due ${o.due_date}`,'ops-order-due'),icon('allocated'));row.addEventListener('click',()=>onTrack(o.order_id));list.append(row);});
      if(!orders.length)list.append(node('p','No orders match these filters.','empty'));count.textContent=`Showing ${Math.min(limit,orders.length)} of ${orders.length} orders`;more.hidden=limit>=orders.length;
      stages.querySelectorAll('button').forEach((b,i)=>b.setAttribute('aria-pressed',String(filter.value===['READY','WORKING','COMPLETED','LAPSED'][i])));
    }
    search.addEventListener('input',()=>{limit=8;render();});filter.addEventListener('change',()=>{limit=8;render();});more.addEventListener('click',()=>{limit+=12;render();});footer.append(count,more);panel.append(list,footer);target.append(panel);render();
  }
  function when(value){if(!value)return 'Not recorded';if(/^\d{4}-\d{2}-\d{2}$/.test(value))return value;const date=new Date(value);return Number.isNaN(date.getTime())?value:date.toLocaleString('en-SG',{dateStyle:'medium',timeStyle:'short'});}
  function eventTitle(event){return {allocate:'Allocation approved',reassign:'Remaining pieces reassigned',cancel:'Allocation cancelled',lapse:'Order lapsed',complete:event.state_after==='COMPLETED'?'Order completed':'Production progress recorded'}[event.action]||event.action;}
  function renderTracking(target,order){const t=order.tracking;if(!t)return;const wrap=node('section',null,'ops-tracking');wrap.id='order-tracking';
    const head=node('div',null,'ops-tracking-heading'),title=node('div');title.append(node('p','ORDER JOURNEY','eyebrow'),node('h2',order.order_id+' · '+order.product));
    const states={awaiting_allocation:'Awaiting allocation',allocated:'Allocated · awaiting progress',production:'Production underway',completed:'Order completed',lapsed:'Order lapsed'};
    head.append(title,node('span',states[t.current],'tag '+(t.current==='lapsed'?'bad':'good')));wrap.append(head);
    const stages=node('ol',null,'ops-journey');t.stages.forEach(stage=>{const item=node('li',null,'ops-stage '+stage.status),symbol=node('span',null,'ops-stage-icon');symbol.append(icon(stage.key));
      item.append(symbol,node('strong',stage.label),node('small',{done:'Recorded',current:'Current stage',unknown:'Not recorded',pending:'Pending',paused:'Paused',blocked:'Not reached',past:'Earlier activity'}[stage.status]));if(stage.status==='current')item.setAttribute('aria-current','step');stages.append(item);});wrap.append(stages);
    const completion=node('div',null,'ops-completion'),progress=node('progress');progress.max=order.pieces;progress.value=order.completed_pieces;progress.setAttribute('aria-label',`${order.completed_pieces} of ${order.pieces} pieces completed`);
    completion.append(node('strong',`${format(t.progress_percent)}% complete`),node('span',`${format(order.completed_pieces,0)} of ${format(order.pieces,0)} pieces · ${format(order.remaining_pieces,0)} remaining`),progress);wrap.append(completion);
    if(t.history_note)wrap.append(node('p',t.history_note,'notice'));
    if(t.current==='lapsed')wrap.append(node('p','This order ended before completion. Recorded completed pieces are retained.','notice'));
    wrap.append(node('h3','Recorded production trail'));
    const trail=node('ol',null,'ops-timeline');
    function entry(symbol,title,meta,description,cls=''){const item=node('li',null,cls),mark=node('span',null,'ops-timeline-icon');mark.append(icon(symbol));const body=node('div');body.append(node('strong',title),node('small',meta));if(description)body.append(node('p',description));item.append(mark,body);trail.append(item);return body;}
    entry('registered','Order registered',when(t.registered_date)+' · Registered order date',`${order.customer} · ${format(order.pieces,0)} pieces · Due ${order.due_date}`);
    t.events.forEach(e=>{let text=e.reason||'';if(e.completed_delta)text=`${format(e.completed_delta,0)} newly completed pieces${e.workshop_id?' at '+e.workshop_id:''}. ${e.completed_total} completed in total. ${text}`;
      if(e.allocation.length)text=e.allocation.map(a=>`${a.workshop_id}: ${format(a.pieces,0)} pieces`).join(' + ')+(text?'. '+text:'');
      const meta=`${when(e.recorded_at)} · ${e.actor||'Actor not recorded'}${e.business_date?' · Business date '+e.business_date:''}`;
      const body=entry({allocate:'allocated',complete:e.state_after==='COMPLETED'?'completed':'production'}[e.action]||e.action,eventTitle(e),meta,text);
      body.append(node('small','Record '+e.id,'ops-record-id'));});
    if(order.state==='COMPLETED'&&!t.events.some(e=>e.action==='complete'&&e.state_after==='COMPLETED'))entry('completed','Imported completion record',when(t.completed_at),'Completion is recorded; intermediate milestones are unavailable.');
    if(!t.events.length&&order.state!=='COMPLETED')entry('clock','Awaiting recorded activity','No approved allocation or production event yet.','');wrap.append(trail);
    if(t.attempts.length){const details=node('details',null,'ops-attempts');details.append(node('summary',`${t.attempts.length} unsuccessful attempts · no state change`));t.attempts.forEach(e=>details.append(node('p',`${when(e.recorded_at)} · ${e.actor||'Actor not recorded'} · ${eventTitle(e)} · ${e.reason_codes.join(', ')}${e.reason?' · '+e.reason:''}`)));wrap.append(details);}
    target.append(wrap);
  }
  const api={summarize,scales,eventTitle,renderStats,renderDashboard,renderTracking,hideTip};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.Operations=api;
})(typeof globalThis!=='undefined'?globalThis:this);
