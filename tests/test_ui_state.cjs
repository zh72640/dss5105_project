/* Controller tests with a minimal DOM stub, not a browser or layout test. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../app/ui/desk.js'), 'utf8');

function setup(fetch) {
  const nodes = new Map(), storage = new Map();
  const node = id => {
    if (!nodes.has(id)) nodes.set(id, {id, value:'', disabled:false, hidden:false, textContent:'',
      classList:{toggle(){}}, addEventListener(){}, replaceChildren(){}, focus(){}, close(){}, showModal(){}});
    return nodes.get(id);
  };
  const context = vm.createContext({
    document:{getElementById:node,querySelectorAll(){return [];}},
    localStorage:{setItem:(k,v)=>storage.set(k,v),getItem:k=>storage.get(k)},
    window:{addEventListener(){},scrollTo(){}},location:{hash:''},fetch,
    crypto:{randomUUID:()=> 'test-request-key'}, console, URLSearchParams,
  });
  // Omit only the page boot; use the real controller functions and persistence.
  vm.runInContext(source.slice(0, source.lastIndexOf('\nboot().catch')), context);
  vm.runInContext(`
    globalThis.controller = {state, controls, canAccept, turn, deliver, startRequest};
    state.user = {username:'alice'};
    refreshDesk = async () => {};
    loadSession = async id => { state.session = {...state.session, session_id:id}; };
    renderSession = () => {};
    renderQueue = () => {};
  `, context);
  return {api:context.controller, nodes, storage};
}
const response = (status,body) => ({status,ok:status<400,json:async()=>body});
const session = () => ({session_id:'draft-a',state:'ACTIVE',version:7,blockers:[],last_response:{result:{success:true,decision_status:'REVIEW'}}});

test('accept is disabled for missing, blocked, rejected and already closed drafts',()=>{
  const {api}=setup();
  assert.ok(!api.canAccept());
  api.state.session=session();assert.ok(api.canAccept());
  api.state.session.blockers=['RECOMMENDATION_REJECTED'];assert.ok(!api.canAccept());
  api.state.session=session();api.state.session.state='CLOSED';assert.ok(!api.canAccept());
  api.state.session=session();api.state.session.last_response.result.decision_status='REFUSE';assert.ok(!api.canAccept());
});

test('uncertain confirmation persists the same key/version and blocks another confirmation',async()=>{
  const calls=[];
  const {api,nodes,storage}=setup(async(url,options)=>{calls.push(JSON.parse(options.body));return response(503,{error:'DB_ERROR'});});
  api.state.session=session();
  await api.turn('confirm');
  assert.equal(api.state.pending.body.expected_version,7);
  assert.equal(api.state.pending.body.request_id,'test-request-key');
  assert.equal(nodes.get('accept').disabled,true);
  assert.equal(nodes.get('logout').disabled,true);
  assert.equal(JSON.parse(storage.get('sweaterco.desk.v1.alice')).pending.body.request_id,'test-request-key');
  await api.turn('confirm');assert.equal(calls.length,1);
  await api.deliver();assert.equal(calls.length,2);assert.deepEqual(calls[0],calls[1]);
});

test('session creation resumes with the original intake after a failed first turn',async()=>{
  const calls=[];
  const {api}=setup(async(url,options)=>{
    calls.push({url,body:JSON.parse(options.body)});
    return calls.length===1?response(200,{session:{session_id:'new-draft',version:0}}):response(503,{error:'DB_ERROR'});
  });
  await api.startRequest('Allocate cheapest.','min_cost');
  assert.equal(calls.length,2);
  assert.equal(api.state.pending.url,'/api/sessions/new-draft/turns');
  assert.equal(api.state.pending.body.message,'Allocate cheapest.');
  await api.deliver();
  assert.equal(calls.length,3);assert.deepEqual(calls[1],calls[2]);
});

test('a rejected HTTP version is not automatically retried as a new confirmation',async()=>{
  const {api}=setup(async()=>response(409,{result:{message:'Version conflict'}}));
  api.state.session=session();
  await api.turn('confirm');
  assert.equal(api.state.pending,null);
  assert.equal(api.state.busy,false);
});

test('two rapid confirmation clicks create only one in-flight write',async()=>{
  let resolve, count=0;
  const {api}=setup(()=>{count++;return new Promise(r=>resolve=r);});
  api.state.session=session();
  const first=api.turn('confirm');
  await api.turn('confirm');assert.equal(count,1);
  resolve(response(503,{error:'DB_ERROR'}));await first;
});
