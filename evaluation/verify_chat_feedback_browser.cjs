/* Real browser checks with delayed Offline responses and an isolated database. */
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const {spawn}=require('node:child_process');
const {once}=require('node:events');
const {chromium,expect}=require(process.env.PLAYWRIGHT_MODULE||'@playwright/test');
const root=path.resolve(__dirname,'..');
const output=path.resolve(process.argv[2]||path.join(root,'evaluation/live_results/chat-feedback-'+Date.now()));
fs.mkdirSync(output,{recursive:true});
const fixture=`
from datetime import date
from pathlib import Path
import json,sys,tempfile,threading
from app.core.security import set_password
from app.server import make_server
with tempfile.TemporaryDirectory(prefix='sweaterco-chat-feedback-') as folder:
    db=str(Path(folder)/'acceptance.sqlite3')
    set_password(db,'tester','Chat-feedback-test-only-2026')
    server=make_server(0,db,as_of=date(2026,4,1))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    print(json.dumps({'base':'http://127.0.0.1:'+str(server.server_port)}),flush=True)
    try: sys.stdin.readline()
    finally: server.shutdown();server.server_close();thread.join(timeout=20)
`;
const deferred=()=>{let resolve;const promise=new Promise(done=>resolve=done);return {promise,resolve};};
(async()=>{
  const server=spawn(process.env.SWEATERCO_PYTHON||(fs.existsSync(path.join(root,'.venv/bin/python'))?path.join(root,'.venv/bin/python'):'python3'),['-u','-c',fixture],{cwd:root,env:process.env,stdio:['pipe','pipe','inherit']});
  let browser;
  const checks=[],errors=[];
  try{
    const base=await new Promise((resolve,reject)=>{let buffer='';server.stdout.on('data',chunk=>{buffer+=chunk;if(buffer.includes('\n')){try{resolve(JSON.parse(buffer.split('\n')[0]).base);}catch(e){reject(e);}}});server.on('exit',code=>reject(Error('Fixture exited: '+code)));});
    browser=await chromium.launch({headless:true,...(process.env.CHROME_EXECUTABLE?{executablePath:process.env.CHROME_EXECUTABLE}:{})});
    const context=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'no-preference'});
    const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
    await context.request.post(base+'/api/auth/login',{data:{username:'tester',password:'Chat-feedback-test-only-2026'}});
    await page.goto(base+'/chat');await expect(page.locator('#chat-input')).toBeEnabled();
    const message='Allocate ORD-045 at the lowest cost, excluding W3.';
    const pending=deferred(),seen=deferred();let reply;
    const creation=async route=>{
      if(route.request().method()!=='POST')return route.continue();
      const response=await route.fetch();reply=(await response.json()).assistant_message;
      seen.resolve();await pending.promise;await route.fulfill({response});
    };
    await page.route('**/api/chat/sessions',creation);
    await page.locator('#chat-input').fill(message);await page.locator('#chat-send').click();await seen.promise;
    await expect(page.locator('#chat-pending .user')).toContainText(message);
    await expect(page.locator('.reply-dots')).toBeVisible();await expect(page.locator('#chat-empty')).toBeHidden();
    await expect(page.locator('#chat-send')).toBeDisabled();
    const dot=page.locator('.reply-dots i').first();assert.equal(await dot.evaluate(n=>getComputedStyle(n).animationName),'reply-pulse');
    await page.screenshot({path:path.join(output,'waiting-desktop.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});await page.locator('#chat-pending').scrollIntoViewIfNeeded();
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    await page.screenshot({path:path.join(output,'waiting-mobile.png'),fullPage:true});
    await page.setViewportSize({width:1440,height:1000});pending.resolve();
    await expect(page.locator('.is-typing')).toBeVisible();
    assert.ok((await page.locator('.is-typing .chat-message-body').innerText()).length<reply.content.length);
    await page.screenshot({path:path.join(output,'typing-desktop.png'),fullPage:true});
    await page.getByRole('button',{name:'Show full reply'}).click();
    await expect(page.locator('#chat-messages .assistant .chat-message-body').last()).toHaveText(reply.content);
    await expect(page.locator('#chat-pending')).toBeEmpty();await expect(page.locator('#chat-messages .user')).toHaveCount(1);
    await expect(page.locator('#chat-send')).toBeEnabled();
    checks.push('First message remains visible through delayed creation; waiting dots animate on desktop and mobile; new reply types out and can be revealed immediately.');
    await page.unroute('**/api/chat/sessions',creation);
    await page.reload();await expect(page.locator('#chat-messages .assistant .chat-message-body').last()).toHaveText(reply.content);
    await expect(page.locator('.is-typing')).toHaveCount(0);
    checks.push('Reload renders complete history without replaying typing.');

    let lost=true;const payloads=[];
    const loseReply=async route=>{
      if(route.request().method()!=='POST')return route.continue();
      payloads.push(route.request().postDataJSON());const response=await route.fetch();
      if(lost){lost=false;await route.abort('failed');}else await route.fulfill({response});
    };
    await page.route('**/api/chat/sessions/*/turns',loseReply);
    const revision='Use the fastest workshop instead.';
    await page.locator('#chat-input').fill(revision);await page.locator('#chat-send').click();
    await expect(page.locator('#chat-retry')).toBeVisible();await expect(page.locator('#chat-retry')).toBeEnabled();
    await expect(page.locator('.reply-dots')).toHaveCount(0);
    // The backend persisted this turn before the response was lost. Do not show it twice.
    await expect(page.locator('#chat-content .user').filter({hasText:revision})).toHaveCount(1);
    await page.reload();await expect(page.locator('#chat-retry')).toBeVisible();
    await expect(page.locator('#chat-content .user').filter({hasText:revision})).toHaveCount(1);
    await page.locator('#chat-retry').click();await expect(page.locator('#chat-send')).toBeEnabled();
    assert.deepEqual(payloads[0],payloads[1]);await expect(page.locator('#chat-pending')).toBeEmpty();
    await expect(page.locator('#chat-content .user').filter({hasText:revision})).toHaveCount(1);
    if(await page.getByRole('button',{name:'Show full reply'}).count())await page.getByRole('button',{name:'Show full reply'}).click();
    checks.push('Lost response and reload retain the message; retry uses the exact request ID and reconciles without duplicate messages.');
    await page.unroute('**/api/chat/sessions/*/turns',loseReply);

    await page.emulateMedia({reducedMotion:'reduce'});
    await page.locator('#chat-input').fill('What is the status of ORD-045?');await page.locator('#chat-send').click();
    await expect(page.locator('#chat-send')).toBeEnabled();await expect(page.locator('.is-typing')).toHaveCount(0);
    await expect(page.locator('#chat-messages .assistant').last()).toContainText('ORD-045');
    await page.screenshot({path:path.join(output,'complete-desktop.png'),fullPage:true});
    checks.push('Reduced-motion preference shows the full reply immediately.');
    assert.deepEqual(errors,[]);
    const report={status:'PASS',mode:'offline',live_model_calls:0,production_database_touched:false,checks,page_errors:errors};
    fs.writeFileSync(path.join(output,'browser.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify({...report,output},null,2));
  }finally{if(browser)await browser.close();server.stdin.end('\n');if(server.exitCode===null)await once(server,'exit');}
})().catch(error=>{console.error(error);process.exitCode=1;});
