/* Controller tests with a minimal DOM stub, not a browser or layout test. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../app/ui/desk.js'), 'utf8');

function setup(fetch) {
  const nodes = new Map(), storage = new Map();
  const href = {value: ''};
  const node = id => {
    if (!nodes.has(id)) nodes.set(id, {id, value:'', disabled:false, hidden:false, textContent:'',
      classList:{toggle(){}}, listeners:{}, addEventListener(name,callback){this.listeners[name]=callback;}, replaceChildren(){}, focus(){}, close(){}, showModal(){}, scrollIntoView(){}});
    return nodes.get(id);
  };
  const context = vm.createContext({
    document:{documentElement:{dataset:{}},getElementById:node,querySelectorAll(selector){return selector==='[data-action="new"]'?['recommendations-new','empty-new'].map(node):[];}},
    localStorage:{setItem:(k,v)=>storage.set(k,v),getItem:k=>storage.get(k)},
    sessionStorage:{setItem(){},getItem(){return null}},
    window:{addEventListener(){},scrollTo(){}},
    location:{hash:'', get href(){return href.value;}, set href(v){href.value=v;}},
    fetch, crypto:{randomUUID:()=>'test-request-key'}, console, URLSearchParams,
  });
  vm.runInContext(source.slice(0, source.lastIndexOf('\nboot().catch')), context);
  vm.runInContext(`
    globalThis.controller = {state, controls, canAccept, turn, deliver, startRequest, openConversation, editDraft, setTextSize, initTextSize, renderIdentity, showLogin, boot};
    state.user = {username:'alice'};
    refreshDesk = async () => {};
    renderSession = () => {};
    renderQueue = () => {};
  `, context);
  return {api:context.controller, nodes, storage, href};
}
const response = (status,body) => ({status,ok:status<400,json:async()=>body});
const session = () => ({session_id:'draft-a',state:'ACTIVE',version:7,blockers:[],last_response:{result:{success:true,decision_status:'REVIEW'}}});

test('admin badge follows authenticated role and disappears on account switch or expired login',()=>{
  const {api,nodes}=setup();
  api.state.user={username:'admin',role:'admin',auth_required:true};
  api.renderIdentity();assert.equal(nodes.get('admin-badge').hidden,false);
  api.state.user={username:'student',role:'user',auth_required:true};
  api.renderIdentity();assert.equal(nodes.get('admin-badge').hidden,true);
  api.state.user={username:'admin',role:'admin',auth_required:true};
  api.renderIdentity();api.showLogin();
  assert.equal(nodes.get('admin-badge').hidden,true);assert.equal(api.state.user,null);
});

test('reload restores badge from server identity and demo mode remains regular',async()=>{
  const {api,nodes}=setup(async url=>response(200,url==='/api/auth/me'
    ?{username:'admin',role:'admin',auth_required:true,setup_required:false}
    :url==='/api/health'?{backend:'offline',version:'test'}:{configured:false,models:[]}));
  // boot may call /api/models; stub returns empty catalog shape when needed
  try { await api.boot(); } catch (_) { /* models stub may lack fields */ }
  api.renderIdentity({username:'admin',role:'admin',auth_required:true});
  assert.equal(nodes.get('admin-badge').hidden,false);
  api.renderIdentity({username:'local-demo',role:'user',auth_required:false});
  assert.equal(nodes.get('admin-badge').hidden,true);assert.equal(nodes.get('logout').hidden,true);
});

test('accept is disabled for missing, blocked, rejected and already closed drafts',()=>{
  const {api}=setup();
  assert.ok(!api.canAccept());
  api.state.session=session();assert.ok(api.canAccept());
  api.state.session.blockers=['RECOMMENDATION_REJECTED'];assert.ok(!api.canAccept());
  api.state.session=session();api.state.session.state='CLOSED';assert.ok(!api.canAccept());
  api.state.session=session();api.state.session.last_response.result.decision_status='REFUSE';assert.ok(!api.canAccept());
});

test('new request and session turns redirect to Chat v2',async()=>{
  const {api,href}=setup();
  await api.startRequest('Allocate cheapest.');
  assert.equal(href.value,'/chat?new=1');
  href.value='';
  await api.turn('message','ORD-045');
  assert.equal(href.value,'/chat');
});

test('deliver retries only production event pending writes',async()=>{
  const calls=[];
  const {api}=setup(async(url,options)=>{
    calls.push({url,body:JSON.parse(options.body)});
    return response(503,{error:'DB_ERROR'});
  });
  api.state.pending={kind:'event',url:'/api/events',body:{action:'cancel',order_id:'ORD-045',event_id:'e1'}};
  await api.deliver();
  assert.equal(calls.length,1);
  assert.equal(calls[0].url,'/api/events');
  await api.deliver();
  assert.equal(calls.length,2);
  assert.deepEqual(calls[0],calls[1]);
});

test('non-event pending is cleared and user is sent to chat',async()=>{
  const {api,href}=setup();
  api.state.pending={kind:'session',url:'/api/sessions/x/turns',body:{}};
  await api.deliver();
  assert.equal(api.state.pending,null);
  assert.equal(href.value,'/chat');
});

test('text size persists across initialization and invalid storage uses medium',()=>{
  const {api,storage}=setup();
  assert.equal(api.setTextSize('large'),'large');
  api.initTextSize();assert.equal(storage.get('sweaterco.text-size'),'large');
  storage.set('sweaterco.text-size','invalid');api.initTextSize();
  assert.equal(storage.get('sweaterco.text-size'),'medium');
});

test('all existing New request buttons route directly to a new Chat session even with a pending Desk operation',async()=>{
  const {api,nodes,href}=setup();api.state.pending={kind:'event'};api.state.busy=true;api.controls();
  for(const id of ['recommendations-new','empty-new']){
    assert.equal(nodes.get(id).disabled,false);await nodes.get(id).listeners.click();
    assert.equal(href.value,'/chat?new=1');href.value='';
  }
  const html=fs.readFileSync(path.join(__dirname,'../app/ui/index.html'),'utf8');
  const entries=html.match(/<button[^>]*data-action="new"[^>]*>/g);
  assert.equal(entries.length,2);
  assert.doesNotMatch(html.split('id="page-home"')[1].split('id="page-recommendations"')[0], /data-action="new"/);assert.ok(entries.every(entry=>!entry.includes('data-mutate')));
  assert.doesNotMatch(html,/id="new-dialog"|id="new-request-form"/);
  assert.doesNotMatch(source,/sweaterco\.chat\.draft|new-message|new-objective/);
});
