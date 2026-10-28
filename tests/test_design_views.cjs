const {test}=require('node:test');
const assert=require('node:assert/strict');
const ui=require('../app/ui/design-system.js');
const views=require('../app/ui/desk-views.js');
const chat=require('../app/ui/chat-common.js');

test('pending requests are FIFO even if a newer request was updated earlier',()=>{
  const items=[{cursor:3,status:'OPEN',task_state:'RECOMMENDED',created_at:'2026-04-03',updated_at:'2026-04-03'},
    {cursor:1,status:'OPEN',task_state:'BLOCKED',created_at:'2026-04-01',updated_at:'2026-04-10'},
    {cursor:2,status:'OPEN',task_state:'CONFIRMED',created_at:'2026-04-02'},
    {cursor:4,status:'ARCHIVED',created_at:'2026-03-01'}];
  assert.deepEqual(ui.pending(items).map(r=>r.cursor),[1,3]);
  assert.equal(items[0].cursor,3);
});
test('overdue grouping excludes completed and lapsed orders and uses the business date',()=>{
  const base={due_date:'2026-04-01',state:'WORKING'};
  assert.equal(ui.orderGroup(base,'2026-04-01'),'production');
  assert.equal(ui.orderGroup(base,'2026-04-02'),'delayed');
  assert.equal(ui.overdue({...base,state:'COMPLETED'},'2026-04-02'),false);
  assert.equal(ui.overdue({...base,state:'LAPSED'},'2026-04-02'),false);
  assert.equal(ui.orderGroup({...base,state:'READY'},'2026-04-01'),'unassigned');
});
test('default order register chooses the oldest twenty before changing display sort',()=>{
  const orders=Array.from({length:30},(_,i)=>({order_id:`ORD-${String(i).padStart(3,'0')}`,order_date:`2026-03-${String(i+1).padStart(2,'0')}`,due_date:'2026-05-01',state:'READY',pieces:30-i})).reverse();
  const data={orders,business_date:'2026-04-01'};
  const result=views.filteredOrders(data,{key:'pieces'});
  assert.equal(result.open.length,20);assert.equal(result.total,30);
  assert.equal(result.open[0].order_id,'ORD-019');assert.equal(result.open.at(-1).order_id,'ORD-000');
  assert.equal(views.filteredOrders(data,{all:true}).open.length,30);
});
test('search and status switches affect open records while completed records remain separate',()=>{
  const data={business_date:'2026-04-01',orders:[
    {order_id:'A',customer:'A&B',state:'READY',due_date:'2026-05-01'},
    {order_id:'B',customer:'A&B',state:'WORKING',due_date:'2026-03-01'},
    {order_id:'C',customer:'A&B',state:'COMPLETED',due_date:'2026-03-01'},
    {order_id:'D',customer:'Other',state:'READY',due_date:'2026-05-01'},
  ]};
  const result=views.filteredOrders(data,{query:'a&b',groups:['unassigned']});
  assert.deepEqual(result.open.map(o=>o.order_id),['A']);assert.deepEqual(result.completed.map(o=>o.order_id),['C']);
  assert.equal(views.filteredOrders(data,{groups:[]}).open.length,0);
});
test('decision text export includes actual records, authors and explanations',()=>{
  const log=views.decisionLog([{order_id:'ORD-045',status:'ALLOCATE',timestamp:'2026-04-01',actor:'operator',original_message:'Allocate cheapest.',summary:'W3: 150 pieces',request_id:'audit-1'}]);
  assert.match(log,/Recorded by: operator/);assert.match(log,/Decision: W3: 150 pieces/);assert.match(log,/Record: audit-1/);
  assert.doesNotMatch(log,/under construction/);
});

test('decision timeline does not present retained recommendation IDs as new plans after rejection',()=>{
  const session={created_at:'2026-04-01',updated_at:'2026-04-02',task:{state:'CANCELLED'},status:'ARCHIVED'};
  const events=chat.decisionEvents(session,[
    {role:'user',metadata:{intent:'new_request'}},
    {role:'assistant',metadata:{recommendation_id:'plan-1'}},
    {role:'user',metadata:{intent:'reject_recommendation'}},
    {role:'assistant',metadata:{intent:'reject_recommendation',recommendation_id:'plan-1'}},
    {role:'assistant',metadata:{intent:'cancel_task',recommendation_id:'plan-1'}},
  ]);
  assert.equal(events.filter(e=>e.title==='Recommendation prepared').length,1);
  assert.ok(events.some(e=>e.title==='Recommendation rejected'));
  assert.ok(events.some(e=>e.title==='Request closed'));
  assert.equal(events.at(-1).title,'Request archived');
  assert.ok(!events.some(e=>/committed|confirmed/.test(e.title)));
});
