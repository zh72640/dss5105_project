const {test}=require('node:test');
const assert=require('node:assert/strict');
const client=require('../app/ui/chat-common.js');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
function controller(fetch,options={}){
  const nodes=new Map(),storage=options.storage||new Map();let sequence=0;
  const location={href:options.href||'http://127.0.0.1/chat'};
  function node(id){if(!nodes.has(id))nodes.set(id,{id,value:'',textContent:'',hidden:false,disabled:false,children:[],scrollTop:0,scrollHeight:200,clientHeight:100,
    append(...items){this.children.push(...items);},replaceChildren(...items){this.children=items;},listeners:{},addEventListener(name,callback){this.listeners[name]=callback;},querySelectorAll(){return [];},classList:{toggle(){},remove(){}}});return nodes.get(id);}
  const context=vm.createContext({document:{getElementById:node,createElement:tag=>node('element-'+nodes.size),querySelectorAll:()=>[],documentElement:{dataset:{}},body:{classList:{toggle(){},remove(){}}}},
    localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},
    storage,window:{addEventListener(){}},setInterval(){},location,history:{replaceState(_state,_title,url){location.href=String(url);}},URL,
    crypto:{randomUUID:()=> sequence++?'client-key-'+sequence:'fixed-client-key'},console,fetch});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/ui/chat-common.js'),'utf8'),context);
  let source=fs.readFileSync(path.join(__dirname,'../app/ui/chat.js'),'utf8');
  source=source.replace('boot().catch(e=>status(e.message));',`globalThis.controller={boot,load,confirm,deliver,send,newSession,endRequest,controls,synchronize,button:id=>$(id),storage,location,
    restorePending:p=>{saveOperation(scope,activeId,p);},
    state:()=>({session,pending:pending(),busy:busy(),operations:scope?.operations,activeId}),
    setSession:s=>{user={username:'alice'};if(!scope)scope={key:key(),operations:{...(savedState(key()).operations||{})}};session=s;activeId=s?.session_id||null;}};`);
  vm.runInContext(source,context);
  context.controller.setSession(null);
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
const storageKey='sweaterco.chat.v2.alice';
const stored=api=>JSON.parse(api.storage.get(storageKey)||'{}');
const turnOperation=(sid='old',action='message')=>({url:`/api/chat/sessions/${sid}/turns`,body:{request_id:'old-request',expected_version:1,action,message:action==='message'?'Allocate order 45':'',...(action==='confirm'?{recommendation_id:'old-plan'}:{})}});
function chatServer(post,identity=()=>({username:'alice'})){
  return async(url,options)=>{
    if(options?.method==='POST')return post(url,JSON.parse(options.body));
    if(url==='/api/auth/me')return response(identity());
    if(url==='/api/models')return response({default_mode:'offline',default_model:null,models:[]});
    if(url.includes('/messages'))return response({items:[],next_cursor:null});
    if(url.startsWith('/api/chat/sessions?'))return response({items:['old','new'].map(id=>({session_id:id,title:id})),next_cursor:null});
    return response(snapshot(decodeURIComponent(url.split('/').at(-1))));
  };
}
function deferred(){let resolve;const promise=new Promise(done=>{resolve=done;});return {promise,resolve};}

test('Desk new entry creates an empty session instead of restoring a bound order',async()=>{
  const calls=[],storage=new Map([[storageKey,JSON.stringify({session_id:'old'})]]);
  const api=controller(chatServer((url,body)=>{calls.push({url,body});return response({session_id:'new'});}),{storage,href:'http://127.0.0.1/chat?new=1'});
  await api.boot();
  assert.equal(calls.length,1);assert.equal(calls[0].url,'/api/chat/sessions');
  assert.equal(calls[0].body.message,'');assert.equal(calls[0].body.mode,'offline');
  assert.equal(api.state().session.session_id,'new');assert.equal(api.button('chat-input').disabled,false);
  assert.equal(new URL(api.location.href).search,'?session=new');
  await api.boot();assert.equal(calls.length,1);
});

test('an ordinary visit and an explicit session link keep their existing restore behavior',async()=>{
  for(const [href,expected] of [['http://127.0.0.1/chat','old'],['http://127.0.0.1/chat?session=chosen','chosen']]){
    const storage=new Map([[storageKey,JSON.stringify({session_id:'old'})]]);
    const api=controller(chatServer(()=>{throw Error('Unexpected POST');}),{storage,href});
    await api.boot();assert.equal(api.state().session.session_id,expected);
  }
});

test('legacy pending confirmations survive new entry and retry only in the old session',async()=>{
  const operation=turnOperation('old','confirm'),calls=[];
  const storage=new Map([[storageKey,JSON.stringify({session_id:'old',pending:operation})]]);
  const api=controller(chatServer((url,body)=>{calls.push({url,body});return response({session_id:url==='/api/chat/sessions'?'new':'old'});}),{storage,href:'http://127.0.0.1/chat?new=1'});
  await api.boot();assert.equal(api.state().session.session_id,'new');assert.equal(api.state().pending,null);
  assert.deepEqual(stored(api).operations.old,operation);assert.equal(stored(api).pending,undefined);
  await api.load('old');assert.equal(api.button('chat-input').disabled,true);assert.equal(api.button('chat-end-request').hidden,true);
  await api.deliver();assert.deepEqual(calls[1],{url:operation.url,body:operation.body});
  assert.equal(stored(api).operations.old,undefined);
});

test('an unconfirmed recommendation does not prevent creating an empty session',async()=>{
  const api=controller(chatServer(()=>response({session_id:'new'})));
  api.setSession({...snapshot('old'),recommendation:{recommendation_id:'plan',status:'valid'}});
  await api.newSession();assert.equal(api.state().session.session_id,'new');
});

test('an executing old request allows a new session and cannot replace its view or URL',async()=>{
  const old=deferred(),calls=[];
  const api=controller(chatServer((url,body)=>{calls.push({url,body});return url.includes('/old/')?old.promise:response({session_id:'new'});}));
  api.setSession(snapshot('old'));
  const work=api.send('message','Allocate order 45');
  assert.equal(api.state().busy,true);api.controls();assert.equal(api.button('chat-new').disabled,false);
  await api.newSession();assert.equal(api.state().session.session_id,'new');
  await api.send('message','Allocate order 63');
  old.resolve(response({session_id:'old',assistant_message:{content:'Old result'}}));await work;
  assert.equal(api.state().session.session_id,'new');assert.equal(api.location.href,'http://127.0.0.1/chat?session=new');
  assert.equal(api.button('chat-title').textContent,'new');assert.equal(api.state().pending,null);
  assert.equal(calls[2].url,'/api/chat/sessions/new/turns');
});

test('an old failure is saved without changing the new session status',async()=>{
  const old=deferred();
  const api=controller(chatServer(url=>url.includes('/old/')?old.promise:response({session_id:'new'})));
  api.setSession({...snapshot('old'),mode:'llm'});const work=api.send('message','Allocate order 45');
  await api.newSession();const notice=api.button('chat-status').textContent;
  old.resolve({ok:false,status:503,json:async()=>({error:'MODEL_UNAVAILABLE',message:'Temporarily unavailable.',details:{session_id:'old',request_id:'fixed-client-key',expected_version:1,can_end:true,retryable:true}})});await work;
  assert.equal(api.state().session.session_id,'new');assert.equal(api.button('chat-status').textContent,notice);
  assert.ok(stored(api).operations.old);await api.load('old');
  assert.equal(api.state().pending.body.message,'Allocate order 45');assert.equal(api.button('chat-end-request').hidden,false);
});

test('same-session duplicate submissions are refused without a request queue',async()=>{
  const old=deferred();let count=0;
  const api=controller(chatServer(()=>{count++;return old.promise;}));api.setSession(snapshot('old'));
  const work=api.send('message','one');await api.send('message','two');await api.deliver();
  assert.equal(count,1);old.resolve(response({session_id:'old'}));await work;
});

test('new-session double clicks send one creation and reload retries its exact request',async()=>{
  const first=deferred(),calls=[];
  const api=controller(chatServer((url,body)=>{calls.push({url,body});return first.promise;}));
  api.setSession(snapshot('old'));const work=api.newSession();await api.newSession();assert.equal(calls.length,1);
  const href=api.location.href;first.resolve({ok:false,status:503,json:async()=>({error:'UNAVAILABLE'})});await work;
  const reloaded=controller(chatServer((url,body)=>{calls.push({url,body});return response({session_id:'new'});}),{storage:api.storage,href});
  await reloaded.boot();assert.equal(calls.length,1);assert.ok(reloaded.state().pending);
  await reloaded.deliver();assert.equal(calls.length,2);assert.deepEqual(calls[0],calls[1]);
  assert.equal(reloaded.location.href,'http://127.0.0.1/chat?session=new');
});

test('a completed creation marker recovers its session without another creation POST',async()=>{
  const storage=new Map([[storageKey,JSON.stringify({created:{'created-key':'new'},operations:{}})]]);
  const api=controller(chatServer(()=>{throw Error('Must not create twice');}),{storage,href:'http://127.0.0.1/chat?new=1&creation=created-key'});
  await api.boot();assert.equal(api.state().session.session_id,'new');assert.equal(new URL(api.location.href).search,'?session=new');
});

test('session switching restores each pending operation independently',async()=>{
  const api=controller(chatServer(()=>{throw Error('network lost');}));
  api.setSession(snapshot('old'));await api.send('message','old message');
  await api.load('new');await api.send('message','new message');
  assert.equal(Object.keys(stored(api).operations).length,2);
  await api.load('old');assert.equal(api.state().pending.body.message,'old message');
  await api.load('new');assert.equal(api.state().pending.body.message,'new message');
});

test('an acknowledged action stays cleared when loading its result fails',async()=>{
  const base=chatServer(()=>response({session_id:'new'}));
  const api=controller(async(url,options)=>url==='/api/chat/sessions/new'?Promise.reject(Error('Load unavailable')):base(url,options));
  await api.newSession();assert.equal(api.state().pending,null);
  assert.match(api.button('chat-status').textContent,/operation completed.*Refresh/);
  assert.equal(api.location.href,'http://127.0.0.1/chat?session=new');
});

test('ending an old request after switching sessions does not change the new view',async()=>{
  const ending=deferred();
  const api=controller(chatServer(url=>url.endsWith('/end')?ending.promise:response({session_id:'new'})));
  api.setSession({...snapshot('old'),mode:'llm'});api.restorePending(turnOperation());const work=api.endRequest();
  await api.newSession();ending.resolve(response({session_id:'old',session_version:2,ended:true,message:'Request ended.'}));await work;
  assert.equal(api.state().session.session_id,'new');assert.equal(stored(api).operations.old,undefined);
  assert.equal(api.location.href,'http://127.0.0.1/chat?session=new');
});

test('a failed creation does not prevent an explicit new entry',async()=>{
  const creation={url:'/api/chat/sessions',body:{request_id:'unknown-create',message:'',mode:'offline'}};
  const storage=new Map([[storageKey,JSON.stringify({active_id:'create:unknown-create',operations:{'create:unknown-create':creation}})]]);
  const api=controller(chatServer(()=>response({session_id:'new'})),{storage,href:'http://127.0.0.1/chat?new=1'});
  await api.boot();assert.equal(api.state().session.session_id,'new');
  assert.deepEqual(stored(api).operations['create:unknown-create'],creation);
});

test('account switching keeps old callbacks and request recovery scoped to their owner',async()=>{
  const old=deferred();let username='alice';
  const api=controller(chatServer(()=>old.promise,()=>({username})));
  api.setSession(snapshot('old'));const work=api.send('message','Alice request');
  username='bob';api.location.href='http://127.0.0.1/chat';await api.boot();
  old.resolve({ok:false,status:503,json:async()=>({error:'UNAVAILABLE',message:'Alice error'})});await work;
  assert.equal(api.state().session,null);assert.equal(api.button('chat-status').textContent,'');
  assert.equal(stored(api).operations.old.body.message,'Alice request');
  assert.equal(JSON.parse(api.storage.get('sweaterco.chat.v2.bob')||'{}').operations?.old,undefined);
});

test('sign-in retains the new entry and does not submit before authentication',async()=>{
  let username=null,count=0;
  const api=controller(chatServer(()=>{count++;return response({session_id:'new'});},()=>({username})),{href:'http://127.0.0.1/chat?new=1'});
  await api.boot();assert.equal(count,0);assert.equal(api.button('chat-login').hidden,false);
  username='alice';await api.boot();assert.equal(count,1);assert.equal(api.state().session.session_id,'new');
});

test('expired authentication retains the pending operation for an authenticated retry',async()=>{
  let expired=true;const calls=[];
  const api=controller(chatServer((url,body)=>{calls.push({url,body});return expired?{ok:false,status:401,json:async()=>({error:'LOGIN_REQUIRED'})}:response({session_id:'old'});}));
  api.setSession(snapshot('old'));await api.send('message','Allocate order 45');assert.ok(api.state().pending);
  expired=false;await api.deliver();assert.deepEqual(calls[0],calls[1]);assert.equal(api.state().pending,null);
});

test('a failed old session refresh cannot overwrite a newly selected session notice',async()=>{
  const old=deferred(),base=chatServer(()=>response({session_id:'new'}));
  const api=controller((url,options)=>url==='/api/chat/sessions/old'?old.promise:base(url,options));
  const work=api.load('old');await api.load('new');
  old.resolve({ok:false,status:503,json:async()=>({error:'OLD_LOAD_FAILURE'})});
  assert.equal(await work,false);assert.equal(api.state().session.session_id,'new');
  assert.equal(api.button('chat-status').textContent,'');
});

test('new creation cannot send until its recovery data is saved',async()=>{
  let count=0;const storage=new Map();
  const api=controller(chatServer(()=>{count++;return response({session_id:'new'});}),{storage});
  storage.set=()=>{throw Error('Storage unavailable');};
  await assert.rejects(api.newSession(),/Storage unavailable/);assert.equal(count,0);
});

test('a pending creation keeps its originally selected model across reload',async()=>{
  const calls=[];
  const failed=controller(chatServer((url,body)=>{calls.push(body);throw Error('Connection lost');}));
  failed.button('chat-mode').value='llm';failed.button('chat-model').value='original-model';await failed.newSession();
  const retry=controller(chatServer((url,body)=>{calls.push(body);return response({session_id:'new'});}),{storage:failed.storage,href:failed.location.href});
  await retry.boot();retry.button('chat-mode').value='offline';await retry.deliver();
  assert.deepEqual(calls[0],calls[1]);assert.equal(calls[1].model_key,'original-model');
});

test('a legacy failed first turn restores its actual session and original creation payload',async()=>{
  const operation={url:'/api/chat/sessions',body:{request_id:'legacy-create',message:'Allocate order 45',mode:'llm',model_key:'original'},run:{session_id:'old',request_id:'chat-first-legacy',expected_version:0,can_end:true,retryable:true}};
  const storage=new Map([[storageKey,JSON.stringify({pending:operation})]]),calls=[];
  const api=controller(chatServer((url,body)=>{calls.push({url,body});return response({session_id:'old'});}),{storage,href:'http://127.0.0.1/chat?new=1&creation=legacy-create'});
  await api.boot();assert.equal(api.state().session.session_id,'old');
  assert.deepEqual(stored(api).operations.old,operation);assert.equal(api.button('chat-end-request').hidden,false);
  await api.deliver();assert.deepEqual(calls[0],{url:operation.url,body:operation.body});assert.equal(api.state().pending,null);
});

test('switching accounts at an unresolved creation link cannot replay another user input',async()=>{
  const operation={url:'/api/chat/sessions',body:{request_id:'alice-create',message:'Private Alice input',mode:'llm'}};
  const storage=new Map([[storageKey,JSON.stringify({operations:{'create:alice-create':operation}})]]),calls=[];
  const api=controller(chatServer((url,body)=>{calls.push(body);return response({session_id:'bob-session'});},()=>({username:'bob'})),{storage,href:'http://127.0.0.1/chat?new=1&creation=alice-create'});
  await api.boot();assert.equal(calls.length,1);assert.equal(calls[0].message,'');assert.notEqual(calls[0].request_id,'alice-create');
  assert.equal(api.state().session.session_id,'bob-session');assert.deepEqual(stored(api).operations['create:alice-create'],operation);
});

test('a legacy failed first turn without a selected session remains accessible on ordinary boot',async()=>{
  const operation={url:'/api/chat/sessions',body:{request_id:'legacy-create',message:'Allocate order 45'},run:{session_id:'old',request_id:'chat-first-legacy',expected_version:0,can_end:true,retryable:true}};
  const storage=new Map([[storageKey,JSON.stringify({pending:operation})]]);
  const api=controller(chatServer(()=>{throw Error('Must not auto retry');}),{storage});
  await api.boot();assert.equal(api.state().session.session_id,'old');assert.ok(api.state().pending);
  assert.equal(api.button('chat-end-request').hidden,false);
});
