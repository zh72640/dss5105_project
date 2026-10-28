/* Isolated, offline acceptance for the UI_requirement redesign. */
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const {spawn}=require('node:child_process');
const {once}=require('node:events');
const {chromium,expect}=require(process.env.PLAYWRIGHT_MODULE||'@playwright/test');
const root=path.resolve(__dirname,'..');
const output=path.resolve(process.argv[2]||path.join(root,'evaluation/live_results/design-'+Date.now()));
fs.mkdirSync(output,{recursive:true});
const fixture=`
from datetime import date
from pathlib import Path
import json,sys,tempfile,threading
from app.core.security import set_password
from app.services.allocation.dispatch import seed_allocation
from app.services.chat import service as chat
from app.server import make_server
with tempfile.TemporaryDirectory(prefix='sweaterco-design-') as folder:
    db=str(Path(folder)/'acceptance.sqlite3')
    set_password(db,'designer','Design-test-only-2026')
    seed_allocation('Allocate ORD-045 to Nimble Needle.',db_path=db,request_id='design-seed',actor='designer')
    chat.create(owner='designer',request_id='design-pending',db_path=db,as_of=date(2026,4,1),mode='offline',message='Allocate ORD-041 at the lowest cost, using at most two workshops.')
    server=make_server(0,db,as_of=date(2026,4,1))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    print(json.dumps({'base':'http://127.0.0.1:'+str(server.server_port)}),flush=True)
    try: sys.stdin.readline()
    finally: server.shutdown();server.server_close();thread.join(timeout=20)
`;
(async()=>{
  const server=spawn(process.env.SWEATERCO_PYTHON||'python3',['-u','-c',fixture],{cwd:root,env:process.env,stdio:['pipe','pipe','inherit']});
  let browser;
  const errors=[],checks=[];
  try{
    const base=await new Promise((resolve,reject)=>{let text='';server.stdout.on('data',chunk=>{text+=chunk;if(text.includes('\n')){try{resolve(JSON.parse(text.split('\n')[0]).base);}catch(e){reject(e);}}});server.on('exit',code=>reject(Error('Fixture exited: '+code)));});
    browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_EXECUTABLE||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
    const context=await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true});
    const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error'&&/Content Security Policy|violates.*directive/i.test(m.text()))errors.push(m.text());});
    const shot=async name=>{await page.screenshot({path:path.join(output,name+'.png'),fullPage:true});};
    const fit=async()=>assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Page must fit viewport');
    await page.goto(base);await expect(page.locator('#login-screen')).toBeVisible();assert.equal(await page.locator('.auth-stripe').first().evaluate(n=>getComputedStyle(n).backgroundColor),'rgb(47, 109, 191)');assert.equal((await context.request.get(base+'/knit-large.svg')).status(),200);await shot('login-desktop');
    await page.locator('#username').fill('designer');await page.locator('#password').fill('wrong');await page.locator('#login-form button[type=submit]').click();await expect(page.locator('#login-feedback')).toContainText('Incorrect');
    await page.locator('[data-password-toggle]').click();await expect(page.locator('#password')).toHaveAttribute('type','text');await page.locator('[data-password-toggle]').click();
    await page.locator('#password').fill('Design-test-only-2026');await page.locator('#login-form button[type=submit]').click();
    await expect(page.locator('#stats .stat')).toHaveCount(5);await expect(page.locator('#pending-requests')).toContainText('ORD-041');await fit();await shot('dashboard-desktop');checks.push('Login, password visibility, five KPIs and owner-scoped pending requests.');
    await page.locator('details.analytics > summary').click();await expect(page.locator('.ops-chart')).toHaveCount(4);await page.locator('.ops-chart').filter({has:page.getByRole('heading',{name:'Production quality'})}).locator('[data-workshop=W6]').hover();await expect(page.getByRole('tooltip')).toContainText('Planning estimate');await page.keyboard.press('Escape');await page.locator('#tracking-search').fill('ORD-045');await page.locator('.ops-order-row').click();await expect(page.locator('#order-tracking')).toBeVisible();await page.goto(base);await expect(page.locator('#stats .stat')).toHaveCount(5);checks.push('Retained analytics, chart tooltips and production tracking.');
    await page.locator('[data-nav=orders]').click();await expect(page.locator('#orders-open tbody tr')).toHaveCount(20);
    await page.locator('#orders-show-all').click();assert.ok(await page.locator('#orders-open tbody tr').count()>20);await page.locator('#orders-show-all').click();
    await page.locator('#orders-search').fill('ORD-045');await expect(page.locator('#orders-open tbody tr')).toHaveCount(1);await page.locator('#orders-open button').filter({hasText:'View'}).click();await expect(page.locator('#order-notes')).toContainText('designer');await page.locator('[data-close=notes-dialog]').click();
    await page.locator('#orders-search').fill('');await page.locator('[data-order-group=unassigned]').uncheck();await page.locator('[data-order-group=delayed]').uncheck();await expect(page.locator('#orders-open')).not.toContainText('Unassigned');await page.locator('[data-order-group=unassigned]').check();await page.locator('[data-order-group=delayed]').check();
    await page.locator('#completed-orders-title').click();await expect(page.locator('#orders-completed')).toBeVisible();
    const downloadPromise=page.waitForEvent('download');await page.locator('#download-decisions').click();const download=await downloadPromise;assert.equal(download.suggestedFilename(),'decision_logs.txt');await download.saveAs(path.join(output,'decision_logs.txt'));assert.match(fs.readFileSync(path.join(output,'decision_logs.txt'),'utf8'),/design-seed/);
    await shot('orders-desktop');checks.push('Oldest 20, show all, search, status toggles, completed orders, actual decision notes and text download.');
    await page.locator('[data-nav=workshops]').click();await expect(page.locator('#workshops-table tbody tr')).toHaveCount(8);await page.locator('#workshop-search').fill('Nimble');await page.locator('#workshop-filters button').click();await expect(page.locator('#workshops-table tbody tr')).toHaveCount(1);await page.locator('#workshops-table button').click();await expect(page.locator('#workshop-queue-dialog')).toContainText('ORD-045');await shot('workshop-queue');await page.keyboard.press('Escape');
    await page.locator('#workshop-search').fill('');await page.locator('#workshop-filters button').click();await expect(page.locator('#workshops-table tbody tr')).toHaveCount(8);await fit();await shot('workshops-desktop');checks.push('Workshop summary, filters and production queue dialog.');
    await page.goto(base+'/chat');await expect(page.locator('#chat-session-list')).toContainText('ORD-041');await page.locator('#chat-session-list button').first().click();await expect(page.locator('#chat-plan .chat-recommendation')).toBeVisible();await expect(page.locator('#chat-validation')).toContainText('ORD-041');await fit();await shot('requests-desktop');
    const before=await (await context.request.get(base+'/api/orders/ORD-041')).json();assert.notEqual(before.state,'WORKING');
    await page.locator('#chat-plan button.primary').click();await expect(page.locator('#chat-plan button.primary')).toHaveText('Committed');await expect(page.locator('#chat-plan button.primary')).toBeDisabled();const after=await (await context.request.get(base+'/api/orders/ORD-041')).json();assert.equal(after.state,'WORKING');
    await page.reload();await expect(page.locator('#chat-plan button.primary')).toHaveText('Committed');await expect(page.locator('#chat-decision-timeline')).toContainText('Allocation');await shot('request-confirmed');checks.push('Three-column request view, validation, explicit confirmation and persisted result.');
    await page.locator('#chat-new').click();await expect(page.locator('#chat-input')).toBeEnabled();await page.locator('#chat-input').fill('Allocate ORD-055 fastest using at most two workshops.');await page.locator('#chat-send').click();await expect(page.locator('#chat-plan .plan-part')).toHaveCount(2);await page.locator('#chat-plan summary').click();await expect(page.locator('#chat-plan')).toContainText('Alternative plan');await shot('request-split');
    await page.locator('#chat-reject-plan').click();await expect(page.locator('#chat-subtitle')).toContainText('Needs clarification');await expect(page.locator('#chat-plan button.primary')).toBeDisabled();await page.locator('#chat-not-allocated').click();await expect(page.locator('#chat-input')).toBeDisabled();const declined=await (await context.request.get(base+'/api/orders/ORD-055')).json();assert.notEqual(declined.state,'WORKING');checks.push('Two-workshop split, candidate comparison, rejection and marking a request not allocated without a production write.');
    for(const [route,ready,name] of [['/#home','#stats','dashboard'],['/#orders','#orders-open','orders'],['/#workshops','#workshops-table','workshops'],['/chat','#chat-app','requests']]){
      await page.setViewportSize({width:390,height:844});await page.goto(base+route);await expect(page.locator(ready)).toBeVisible();await fit();if(name==='requests'){await page.locator('.timeline-title').scrollIntoViewIfNeeded();assert.ok(await page.locator('.request-review').evaluate(n=>n.scrollHeight<=n.clientHeight+1));}await shot(name+'-mobile');
    }
    await page.locator('#chat-menu').click();await expect(page.locator('#chat-sidebar')).toBeVisible();await page.keyboard.press('Escape');await expect(page.locator('#chat-sidebar')).toBeHidden();
    await page.goto(base+'/#home');await page.locator('.text-preferences summary').click();await page.locator('[data-text-size=large]').click();await page.locator('.text-preferences summary').click();await fit();await shot('dashboard-large-mobile');
    await page.locator('#logout').click();await expect(page.locator('#login-screen')).toBeVisible();await fit();await shot('login-mobile');checks.push('390px layouts, mobile session menu, large text and sign-out.');
    assert.deepEqual(errors,[]);
    const report={status:'PASS',checked_at:new Date().toISOString(),mode:'offline',live_model_calls:0,production_database_touched:false,checks,page_errors:errors};fs.writeFileSync(path.join(output,'browser.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify({...report,output},null,2));
  }finally{if(browser)await browser.close();server.stdin.end('\n');if(server.exitCode===null)await once(server,'exit');}
})().catch(e=>{console.error(e);process.exitCode=1;});
