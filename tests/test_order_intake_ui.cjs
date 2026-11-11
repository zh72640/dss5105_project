/* Behavioral controller tests with a DOM stub; not a browser layout test. */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../app/ui/order-intake.js'),'utf8');
const facts={order_id:'ORD-901',customer:'Test customer',product:'Vest',category:'TOPS',pieces:120,order_date:'2026-04-01',due_date:'2026-05-01'};
function review(match='missing'){
  return {review_id:'review-1',order_id:facts.order_id,proposed:{...facts},match,expected_version:match==='missing'?null:3,
    existing:match==='missing'?null:{...facts,pieces:match==='different'?100:120,version:3},
    differences:match==='different'?[{field:'pieces',stored:100,proposed:120}]:[],decision:null};
}
function setup({api,fetch,storage=new Map()}={}){
  const nodes=new Map();let next=0,refreshes=0;
  class Node{
    constructor(){this.value='';this.hidden=false;this.disabled=false;this.children=[];this.listeners={};this.classList={toggle(){}};}
    addEventListener(name,handler){this.listeners[name]=handler;}
    append(...children){this.children.push(...children);}
    replaceChildren(...children){this.children=children;}
    querySelectorAll(){return this.children.flatMap(c=>c.children).filter(c=>c.type==='checkbox'&&c.checked);}
    showModal(){this.open=true;}
    reset(){for(const field of Object.keys(facts))node('intake-'+field).value='';}
    reportValidity(){return !!this.value;}
  }
  const node=id=>{if(!nodes.has(id))nodes.set(id,new Node());return nodes.get(id);};
  const context=vm.createContext({$:node,el:(tag,text)=>{const n=new Node();n.textContent=text;return n;},
    table:(target,headers,rows)=>{target.rows=rows;},stamp:s=>s,state:{user:{username:'alice'}},
    sessionStorage:{setItem:(k,v)=>storage.set(k,v),getItem:k=>storage.get(k)},
    crypto:{randomUUID:()=>`request-${++next}`},api,fetch,showLogin(){context.state.user=null;},
    refreshDesk:async()=>{refreshes++;},location:{hash:''},console});
  vm.runInContext(source,context);
  return {node,storage,context,refreshes:()=>refreshes,
    click:async id=>node(id).listeners.click(),
    submit:async id=>node(id).listeners.submit({preventDefault(){}}),
    fill:()=>Object.entries(facts).forEach(([k,v])=>node('intake-'+k).value=v),
    saved:()=>JSON.parse(storage.get('sweaterco.order-intake.alice')||'{}')};
}
const response=(status,body)=>({status,ok:status<400,json:async()=>body});

test('checking a missing order does not submit a creation; a reason and explicit click do',async()=>{
  const checks=[],decisions=[];
  const ui=setup({api:async(url,options)=>{checks.push(JSON.parse(options.body));return review();},
    fetch:async(url,options)=>{decisions.push(JSON.parse(options.body));return response(200,{outcome:'CREATED',applied:true,message:'Registered',actor:'alice'});}});
  await ui.click('order-intake-open');ui.fill();await ui.submit('intake-form');
  assert.equal(checks.length,1);assert.equal(decisions.length,0);assert.equal(ui.node('intake-fields').disabled,true);
  await ui.click('intake-approve');assert.equal(decisions.length,0);
  ui.node('intake-reason').value='Customer confirmed';await ui.click('intake-approve');
  assert.equal(decisions.length,1);assert.equal(decisions[0].action,'create');assert.equal(decisions[0].expected_version,null);
  assert.equal(ui.refreshes(),1);assert.equal(ui.saved().pending,null);assert.equal(ui.node('intake-decision-form').hidden,true);
});

test('matching orders have no approval form and cannot create a duplicate',async()=>{
  const ui=setup({api:async()=>review('identical')});
  await ui.click('order-intake-open');ui.fill();await ui.submit('intake-form');
  assert.equal(ui.node('intake-decision-form').hidden,true);assert.equal(ui.node('intake-chat').hidden,false);
  assert.match(ui.node('intake-review-title').textContent,/all fields match/);
});

test('approval requires checking all differences and retyping the order ID',async()=>{
  const decisions=[];
  const ui=setup({api:async()=>review('different'),fetch:async(url,options)=>{decisions.push(JSON.parse(options.body));return response(200,{outcome:'UPDATED',applied:true,message:'Updated',actor:'alice'});}});
  await ui.click('order-intake-open');ui.fill();await ui.submit('intake-form');ui.node('intake-reason').value='Verified quantity';
  await ui.click('intake-approve');assert.equal(decisions.length,0);
  ui.node('intake-verify-fields').children[0].children[0].checked=true;
  await ui.click('intake-approve');assert.equal(decisions.length,0);
  ui.node('intake-confirm-id').value=facts.order_id;await ui.click('intake-approve');
  assert.deepEqual(decisions[0].verified_fields,['pieces']);assert.equal(decisions[0].action,'update');assert.equal(decisions[0].expected_version,3);
});

test('rejecting a mismatch records a reason without requiring approval checkboxes',async()=>{
  let body;
  const ui=setup({api:async()=>review('different'),fetch:async(url,options)=>{body=JSON.parse(options.body);return response(200,{outcome:'REJECTED',applied:false,message:'Kept original',actor:'alice'});}});
  await ui.click('order-intake-open');ui.fill();await ui.submit('intake-form');ui.node('intake-reason').value='Wrong customer instruction';
  await ui.click('intake-reject');assert.equal(body.action,'reject');assert.deepEqual(body.verified_fields,[]);assert.equal(ui.refreshes(),0);
});

test('lost decision responses keep exactly the same payload across reload and retry',async()=>{
  const requests=[],storage=new Map();
  const first=setup({storage,api:async()=>review(),fetch:async(url,options)=>{requests.push(options.body);throw Error('Connection lost');}});
  await first.click('order-intake-open');first.fill();await first.submit('intake-form');first.node('intake-reason').value='Confirmed';await first.click('intake-approve');
  assert.equal(first.node('intake-another').disabled,true);assert.equal(first.node('intake-retry').hidden,false);
  const restored=setup({storage,api:async()=>review(),fetch:async(url,options)=>{requests.push(options.body);return response(200,{outcome:'CREATED',applied:true,message:'Replayed',actor:'alice'});}});
  await restored.click('order-intake-open');await restored.click('intake-retry');
  assert.equal(requests[0],requests[1]);assert.equal(restored.saved().pending,null);
});

test('reopening a decided review clears pending recovery without another write',async()=>{
  const storage=new Map([['sweaterco.order-intake.alice',JSON.stringify({review_id:'review-1',pending:{request_id:'uncertain'}})]]);
  const ui=setup({storage,api:async()=>({...review(),decision:{outcome:'CREATED',applied:true,message:'Already registered',actor:'alice'}}),fetch:()=>{throw Error('must not resubmit');}});
  await ui.click('order-intake-open');assert.equal(ui.saved().pending,null);assert.equal(ui.node('intake-decision-form').hidden,true);
});

test('a recorded version conflict closes the decision and permits a fresh check',async()=>{
  const ui=setup({api:async()=>review('different'),fetch:async()=>response(409,{outcome:'ORDER_CHANGED',applied:false,message:'Check the latest order',actor:'alice'})});
  await ui.click('order-intake-open');ui.fill();await ui.submit('intake-form');ui.node('intake-reason').value='Verified';
  ui.node('intake-verify-fields').children[0].children[0].checked=true;ui.node('intake-confirm-id').value=facts.order_id;
  await ui.click('intake-approve');assert.equal(ui.saved().pending,null);assert.equal(ui.node('intake-another').disabled,false);
  await ui.click('intake-another');assert.equal(ui.node('intake-fields').disabled,false);assert.equal(ui.node('intake-review').hidden,true);
});

test('a rejected input unlocks the form while a lost check retains its request ID',async()=>{
  const checks=[];let invalid=false;
  const ui=setup({api:async(url,options)=>{checks.push(options.body);throw Error(invalid?'INVALID_FIELDS':'Connection lost');}});
  await ui.click('order-intake-open');ui.fill();await ui.submit('intake-form');
  assert.equal(ui.node('intake-fields').disabled,true);
  await ui.submit('intake-form');assert.equal(checks[0],checks[1]);
  invalid=true;await ui.submit('intake-form');assert.equal(ui.node('intake-fields').disabled,false);assert.equal(ui.saved().checkRequest,null);
});

test('another account does not restore the previous owner input or pending decision',async()=>{
  const storage=new Map([['sweaterco.order-intake.alice',JSON.stringify({review_id:'private-review',pending:{request_id:'private'}})]]);
  const ui=setup({storage,api:()=>{throw Error('must not read another owner review');}});ui.context.state.user={username:'bob'};
  ui.node('intake-customer').value='Previous account input';await ui.click('order-intake-open');
  assert.equal(ui.node('intake-customer').value,'');assert.equal(ui.node('intake-review').hidden,true);assert.equal(ui.node('intake-fields').disabled,false);
});

test('corrupt browser recovery data still opens an editable form and shows a notice',async()=>{
  const ui=setup({storage:new Map([['sweaterco.order-intake.alice','broken JSON']])});
  await ui.click('order-intake-open');
  assert.equal(ui.node('order-intake-dialog').open,true);assert.equal(ui.node('intake-fields').disabled,false);
  assert.match(ui.node('intake-feedback').textContent,/recovery data is unavailable/);
});
