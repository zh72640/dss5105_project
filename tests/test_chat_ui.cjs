const {test}=require('node:test');
const assert=require('node:assert/strict');
const client=require('../app/ui/chat-common.js');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
function controller(fetch){
  const nodes=new Map(),storage=new Map();
  function node(id){if(!nodes.has(id))nodes.set(id,{id,value:'',textContent:'',hidden:false,disabled:false,children:[],scrollTop:0,scrollHeight:200,clientHeight:100,
    append(...items){this.children.push(...items);},replaceChildren(...items){this.children=items;},addEventListener(){},querySelectorAll(){return [];},classList:{toggle(){},remove(){}}});return nodes.get(id);}
  const context=vm.createContext({document:{getElementById:node,createElement:tag=>node('element-'+nodes.size),querySelectorAll:()=>[],documentElement:{dataset:{}},body:{classList:{toggle(){},remove(){}}}},
    localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},
    window:{addEventListener(){}},setInterval(){},location:{href:'http://127.0.0.1/chat'},history:{replaceState(){}},URL,
    crypto:{randomUUID:()=> 'fixed-client-key'},console,fetch});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/ui/chat-common.js'),'utf8'),context);
  let source=fs.readFileSync(path.join(__dirname,'../app/ui/chat.js'),'utf8');
  source=source.replace('boot().catch(e=>status(e.message));',`globalThis.controller={load,confirm,deliver,state:()=>({session,pending,busy}),setSession:s=>{session=s;user={username:'alice'};}};`);
  vm.runInContext(source,context);
  return context.controller;
}
const snapshot=id=>({session_id:id,title:id,version:1,business_date:'2026-04-01',mode:'offline',status:'OPEN',task:{state:'RECOMMENDED',report:{}},recommendation:null});
const response=body=>({ok:true,status:200,json:async()=>body});
test('both entry points bind the same recommendation and session version',()=>{
  const rec={recommendation_id:'plan-one',session_id:'s',session_version:3,status:'valid'};
  const chat=client.confirmation(rec,'chat-key'),desk=client.confirmation(rec,'desk-key');
  assert.equal(chat.recommendation_id,desk.recommendation_id);
  assert.equal(chat.expected_version,3);assert.equal(desk.action,'confirm');
  assert.notEqual(chat.request_id,desk.request_id);assert.equal(chat.message,'');
});
test('confirmed or superseded recommendations cannot be accepted',()=>{
  assert.equal(client.canConfirm({status:'valid'}),true);
  assert.equal(client.canConfirm({status:'confirmed'}),false);
  assert.equal(client.canConfirm({status:'superseded'}),false);
  assert.equal(client.canConfirm(null),false);
  assert.equal(client.stateLabel('confirmed'),'Committed');
});
test('a persisted stale-plan response is delivered for UI synchronization',async()=>{
  global.fetch=async()=>({ok:false,status:409,json:async()=>({committed:false,assistant_message:{content:'重新确认'},session_version:4})});
  const value=await client.request('/api/chat/sessions/s/turns',{action:'confirm'});
  assert.equal(value.committed,false);assert.equal(value.session_version,4);
});
test('network failure remains retryable; authorization errors are explicit',async()=>{
  global.fetch=async()=>{throw Error('offline');};
  await assert.rejects(client.request('/api/chat',{}),/offline/);
  global.fetch=async()=>({ok:false,status:401,json:async()=>({error:'LOGIN_REQUIRED'})});
  await assert.rejects(client.request('/api/chat',{}),e=>e.status===401);
});
test('an older slow response cannot overwrite the newly selected session',async()=>{
  let release;
  const api=controller(async url=>{
    if(url.includes('/messages'))return response({items:[],next_cursor:null});
    if(url.endsWith('/old'))return new Promise(resolve=>release=()=>resolve(response(snapshot('old'))));
    return response(snapshot('new'));
  });
  const old=api.load('old');await api.load('new');release();await old;
  assert.equal(api.state().session.session_id,'new');
});
test('an uncertain confirmation retries the exact same persisted operation',async()=>{
  const calls=[];let failed=false;
  const api=controller(async(url,options)=>{
    if(options?.method==='POST'){
      calls.push(JSON.parse(options.body));
      if(!failed){failed=true;throw Error('offline');}
      return response({session_id:'s',assistant_message:{content:'已提交'}});
    }
    if(url.includes('/messages')||url.startsWith('/api/chat/sessions?'))return response({items:[],next_cursor:null});
    return response(snapshot('s'));
  });
  api.setSession(snapshot('s'));
  const rec={session_id:'s',session_version:1,recommendation_id:'r',status:'valid'};
  await api.confirm(rec);assert.ok(api.state().pending);
  await api.deliver();assert.equal(api.state().pending,null);
  assert.deepEqual(calls[0],calls[1]);assert.equal(calls[1].recommendation_id,'r');
});
