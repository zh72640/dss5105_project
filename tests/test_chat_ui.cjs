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
  source=source.replace('boot().catch(e=>status(e.message));',`globalThis.controller={load,confirm,deliver,send,newSession,endRequest,controls,button:id=>$(id),restorePending:p=>{pending=p;},state:()=>({session,pending,busy}),setSession:s=>{session=s;user={username:'alice'};}};`);
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


test('model diagnostics survive the shared HTTP client',async()=>{
  const details={retryable:true,can_end:true,phase:'extract',model_error:{upstream_status:503}};
  global.fetch=async()=>({ok:false,status:503,json:async()=>({error:'MODEL_UNAVAILABLE',message:'Gemini is temporarily unavailable (HTTP 503).',details})});
  await assert.rejects(client.request('/api/chat',{}),e=>e.details===details&&e.code==='MODEL_UNAVAILABLE'&&e.status===503);
});

test('ending a failed model request retries the same end operation and releases the composer',async()=>{
  const ends=[];let lost=true;
  const api=controller(async(url,options)=>{
    if(options?.method==='POST'){
      if(url.endsWith('/end')){
        ends.push({url,body:JSON.parse(options.body)});
        if(lost){lost=false;throw Error('connection lost');}
        return response({session_id:'s',ended:true,message:'Request ended.'});
      }
      return {ok:false,status:503,json:async()=>({error:'MODEL_UNAVAILABLE',message:'Gemini is temporarily unavailable (HTTP 503).',details:{session_id:'s',request_id:'fixed-client-key',expected_version:1,can_end:true,retryable:true,phase:'tool_loop'}})};
    }
    if(url.includes('/messages')||url.startsWith('/api/chat/sessions?'))return response({items:[],next_cursor:null});
    return response({...snapshot('s'),mode:'llm',version:2});
  });
  api.setSession({...snapshot('s'),mode:'llm'});
  await api.send('message','Allocate order 45');
  assert.ok(api.state().pending);assert.equal(api.button('chat-end-request').hidden,false);
  assert.match(api.button('chat-status').textContent,/Preparing the recommendation.*HTTP 503/);
  await api.endRequest();assert.ok(api.state().pending);
  await api.endRequest();assert.equal(api.state().pending,null);
  assert.deepEqual(ends[0],ends[1]);assert.equal(ends[0].body.expected_version,1);
  assert.equal(api.state().session.version,2);assert.equal(api.button('chat-input').disabled,false);
});

test('nonretryable model errors keep an end action without repeating the model request',async()=>{
  let calls=0;
  const api=controller(async(url,options)=>{
    if(options?.method==='POST'){
      calls++;
      return {ok:false,status:502,json:async()=>({error:'MODEL_REQUEST_FAILED',message:'Check the model credentials.',details:{session_id:'s',request_id:'fixed-client-key',expected_version:1,can_end:true,retryable:false,phase:'intent'}})};
    }
    if(url.includes('/messages'))return response({items:[],next_cursor:null});
    return response({...snapshot('s'),mode:'llm'});
  });
  api.setSession({...snapshot('s'),mode:'llm'});
  await api.send('message','Allocate order 45');await api.deliver();
  assert.equal(calls,1);assert.ok(api.state().pending);
  assert.equal(api.button('chat-retry').disabled,true);assert.equal(api.button('chat-end-request').hidden,false);
  assert.match(api.button('chat-status').textContent,/End this request/);
});

test('initial-message failures can end the actual backend request before a session is loaded',async()=>{
  const calls=[];
  const api=controller(async(url,options)=>{
    if(options?.method==='POST'){
      calls.push(url);
      if(url.endsWith('/end'))return response({session_id:'created',ended:true,message:'Request ended.'});
      return {ok:false,status:400,json:async()=>({error:'MODEL_NOT_CONFIGURED',message:'Configure the model.',details:{session_id:'created',request_id:'chat-first-actual-key',expected_version:0,can_end:true,retryable:false}})};
    }
    if(url.includes('/messages')||url.startsWith('/api/chat/sessions?'))return response({items:[],next_cursor:null});
    return response({...snapshot('created'),mode:'llm'});
  });
  await api.newSession('Allocate order 45');assert.ok(api.state().pending);
  assert.equal(api.button('chat-end-request').hidden,false);
  await api.endRequest();assert.equal(calls[1],'/api/chat/sessions/created/requests/chat-first-actual-key/end');
  assert.equal(api.state().pending,null);assert.equal(api.state().session.session_id,'created');
});

test('an uncertain confirmation cannot be ended as a model request',async()=>{
  let calls=0;
  const api=controller(async(url,options)=>{
    if(options?.method==='POST'){calls++;throw Error('offline');}
    if(url.includes('/messages'))return response({items:[],next_cursor:null});
    return response({...snapshot('s'),mode:'llm'});
  });
  api.setSession({...snapshot('s'),mode:'llm'});
  await api.confirm({session_id:'s',session_version:1,recommendation_id:'r',status:'valid'});
  assert.ok(api.state().pending);assert.equal(api.button('chat-end-request').hidden,true);
  await api.endRequest();assert.equal(calls,1);
});

test('restored pending model requests can be ended without new error metadata',()=>{
  const api=controller();api.setSession({...snapshot('s'),mode:'llm'});
  api.restorePending({url:'/api/chat/sessions/s/turns',body:{request_id:'old-key',expected_version:1,action:'message',message:'Allocate order 45'}});
  api.controls();assert.equal(api.button('chat-end-request').hidden,false);assert.equal(api.button('chat-input').disabled,true);
});


test('an acknowledged end remains ended if refreshing the session fails',async()=>{
  const api=controller(async(url,options)=>{
    if(options?.method==='POST')return response({session_id:'s',ended:true,session_version:2,message:'Request ended.'});
    throw Error('refresh unavailable');
  });
  api.setSession({...snapshot('s'),mode:'llm'});
  api.restorePending({url:'/api/chat/sessions/s/turns',body:{request_id:'old-key',expected_version:1,action:'message',message:'Allocate order 45'}});
  await api.endRequest();
  assert.equal(api.state().pending,null);assert.equal(api.state().session.version,2);
  assert.match(api.button('chat-status').textContent,/Request ended.*Refresh the page/);
  assert.doesNotMatch(api.button('chat-status').textContent,/not been confirmed/);
});


test('model input errors show one end instruction, including older server messages',async()=>{
  for(const message of ['The model request is missing required message content.',
      'The model request could not be completed. End this request and check the model configuration or input.']){
    const api=controller(async(url,options)=>{
      if(options?.method==='POST')return {ok:false,status:502,json:async()=>({error:'MODEL_REQUEST_FAILED',message,
        details:{session_id:'s',request_id:'fixed-client-key',expected_version:1,can_end:true,retryable:false,phase:'explanation'}})};
      if(url.includes('/messages'))return response({items:[],next_cursor:null});
      return response({...snapshot('s'),mode:'llm'});
    });
    api.setSession({...snapshot('s'),mode:'llm'});
    await api.send('message','Allocate order 45');
    const notice=api.button('chat-status').textContent;
    assert.match(notice,/^Explaining the recommendation:/);
    assert.equal((notice.match(/End this request/g)||[]).length,1);
    assert.equal(api.button('chat-end-request').hidden,false);
  }
});
