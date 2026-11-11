/* Registration UI behavior with a DOM stub; visual acceptance is separate. */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const ui=require('../app/ui/chat-registration.js');

class Element{
  constructor(tag){this.tag=tag;this.children=[];this.value='';this.checked=false;this.listeners={};}
  append(...nodes){this.children.push(...nodes);}
  setAttribute(){}
  addEventListener(name,fn){this.listeners[name]=fn;}
  focus(){}
}
global.document={createElement:tag=>new Element(tag)};
const all=node=>[node,...node.children.flatMap(all)];
const select=(node,tag)=>all(node).filter(n=>n.tag===tag);
const facts={order_id:'ORD-901',customer:'ABC',product:'Vest',category:'TOPS',pieces:300,order_date:'2026-11-11',due_date:'2026-11-25'};
const task=(match='missing')=>({status:'REVIEW',draft:facts,issues:[],review:{review_id:'r1',order_id:'ORD-901',match,expected_version:match==='missing'?null:2,
  differences:match==='different'?[{field:'pieces',stored:200,proposed:300}]:[]}});

test('new order requires explicit confirmation and a nonblank reason',async()=>{
  const calls=[],card=ui.card(task(),async(r,d)=>calls.push(d));
  const button=select(card,'button')[0];assert.equal(button.textContent,'Confirm new order');
  assert.equal(calls.length,0);await button.listeners.click();assert.equal(calls.length,0);
  select(card,'textarea')[0].value='Customer order verified';await button.listeners.click();
  assert.equal(calls[0].action,'create');assert.equal(calls[0].review_id,'r1');assert.equal(calls[0].expected_version,null);
});
test('corrections require every difference checkbox and the exact ID',async()=>{
  const calls=[],card=ui.card(task('different'),async(r,d)=>calls.push(d));
  select(card,'textarea')[0].value='Corrected customer quantity';
  const [checkbox,id]=select(card,'input'),approve=select(card,'button')[0];
  await approve.listeners.click();assert.equal(calls.length,0);
  checkbox.checked=true;id.value='WRONG';await approve.listeners.click();assert.equal(calls.length,0);
  id.value='ORD-901';await approve.listeners.click();assert.equal(calls.length,1);
  assert.deepEqual(calls[0].verified_fields,['pieces']);assert.equal(calls[0].expected_version,2);
});
test('keeping original values requires a reason but no approval evidence',async()=>{
  let decision;const card=ui.card(task('different'),async(r,d)=>decision=d);
  select(card,'textarea')[0].value='Original order is correct';await select(card,'button')[1].listeners.click();
  assert.equal(decision.action,'reject');assert.deepEqual(decision.verified_fields,[]);
});
test('matching and decided reviews have no mutable controls',()=>{
  assert.equal(select(ui.card(task('identical'),()=>{}),'button').length,0);
  const done=task();done.status='COMPLETED';done.review.decision={message:'Registered',outcome:'CREATED',actor:'alice',reason:'Verified'};
  const card=ui.card(done,()=>{});assert.equal(select(card,'button').length,0);
  assert.ok(all(card).some(n=>n.textContent==='Reason: Verified'));
});
test('unresolved details disable decision controls and data stays literal text',()=>{
  const current=task('different');current.draft={...facts,customer:'<img src=x onerror=alert(1)>'};current.issues=[{question:'Clarify the date.'}];
  const card=ui.card(current,()=>{});
  assert.equal(select(card,'fieldset')[0].disabled,true);
  assert.ok(select(card,'dd').some(n=>n.textContent==='<img src=x onerror=alert(1)>'));
  assert.equal(select(card,'img').length,0);
});
test('a local save failure surfaces an error and lets the user retry',async()=>{
  const card=ui.card(task(),async()=>{throw Error('Recovery storage unavailable');});select(card,'textarea')[0].value='Verified';
  await select(card,'button')[0].listeners.click();assert.equal(select(card,'fieldset')[0].disabled,false);
  assert.ok(all(card).some(n=>n.textContent==='Recovery storage unavailable'));
});
