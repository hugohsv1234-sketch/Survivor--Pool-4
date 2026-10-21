/* Real Chromium coverage with isolated demo data. Never point this test at
   production: registration and confirmed picks below are intentional QA writes. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const origin = process.env.SURVIVOR_TEST_ORIGIN || 'http://127.0.0.1:8765';
if (!['localhost','127.0.0.1'].includes(new URL(origin).hostname)) {
  throw new Error('Browser QA writes require an isolated localhost demo server.');
}
const save = path.resolve(__dirname, '../test-results');
const run = Date.now().toString(36);
fs.mkdirSync(save, {recursive:true});

async function visible(page, selector, timeout=12000) {
  const element=page.locator(selector).first();
  await element.waitFor({state:'visible',timeout});
  return element;
}
async function snapshot(page,name) {
  // Let queued route/observer work start, then capture the final presentation.
  // Infinite ambient lights do not delay screenshots.
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  await page.waitForFunction(()=>document.getAnimations().every(animation=>
    animation.playState!=='running' || animation.effect?.getComputedTiming().iterations===Infinity),null,{timeout:3000});
  await page.screenshot({path:path.join(save,name+'.png'),animations:'disabled'});
}
async function noOverflow(page,name) {
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth-document.documentElement.clientWidth);
  assert.ok(overflow<=2,name+' document overflow: '+overflow+'px');
}
async function state(page) {
  const response=await page.request.get(origin+'/api/state');
  assert.equal(response.status(),200);
  return response.json();
}
async function statsMatch(page) {
  const {me}=await state(page);
  const expected=[me.stats.wins,me.stats.losses,me.stats.total,me.stats.rate];
  await page.waitForFunction(values=>{
    const nodes=[...document.querySelectorAll('.stats-grid .stat-card>strong')];
    return nodes.length===4 && nodes.every((node,i)=>Number(node.textContent.replace('%','').trim())===values[i]);
  },expected);
}
async function navigate(page, route, target) {
  const mobile=await page.locator('.bottom-nav').isVisible();
  await page.locator((mobile?'.bottom-nav a':'.sidebar .nav-link')+'[href="#'+route+'"]').click();
  await visible(page,target);
}
async function assertQuietRefresh(page) {
  const previous=await page.locator('.page-content').elementHandle();
  const response=page.waitForResponse(r=>r.url()===origin+'/api/state' && r.status()===200);
  await page.evaluate(()=>document.dispatchEvent(new Event('visibilitychange')));
  await response;
  await page.waitForFunction(node=>!node.isConnected,previous);
  await page.waitForTimeout(80);
  assert.equal(await page.locator('.pm-route-enter').count(),0,'quiet refresh must not replay the page intro');
  await statsMatch(page);
  await previous.dispose();
}
async function assertWidgetTilt(page,selector,label,attempt=0) {
  const widget=page.locator(selector).first();
  await page.mouse.move(0,0);
  await widget.scrollIntoViewIfNeeded();
  await page.waitForFunction(()=>document.getAnimations().every(animation=>
    animation.playState!=='running' || animation.effect?.getComputedTiming().iterations===Infinity));
  const box=await widget.boundingBox();
  assert.ok(box && box.width>0 && box.height>0,label+' must remain visible');
  const surface=await widget.elementHandle();
  const y=Math.max(90,box.y+Math.min(22,box.height*.24));
  const read=()=>widget.evaluate(node=>{
    const matrix=new DOMMatrixReadOnly(getComputedStyle(node).transform);
    const light=node.querySelector(':scope>.pm-widget-light');
    return {rotation:matrix.m13,pitch:matrix.m23,lift:matrix.m42,
      lights:light?Number(getComputedStyle(light).opacity):0,
      active:document.querySelectorAll('.pm-tilting').length,
      owns:node.classList.contains('pm-tilting')};
  });
  await page.mouse.move(box.x+box.width*.18,y,{steps:4});
  await page.waitForTimeout(240);
  const left=await read();
  if (!await surface.evaluate(node=>node.isConnected)) {
    await surface.dispose();
    assert.ok(attempt<2,label+' was repeatedly replaced during the pointer probe');
    return assertWidgetTilt(page,selector,label,attempt+1);
  }
  assert.ok(left.owns && left.active===1,label+' must own the effect without rotating ancestor panels');
  assert.ok(Math.abs(left.rotation)>.008 && left.lift<-1,label+' must visibly tilt and lift');
  await page.mouse.move(box.x+box.width*.82,y,{steps:4});
  await page.waitForTimeout(240);
  const right=await read();
  // The real app refreshes its data and replaces the view every 20 seconds.
  // Re-probe a fresh surface if that happened between the two pointer positions;
  // a different DOM node has no obligation to retain the old node's rotation.
  if (!await surface.evaluate(node=>node.isConnected)) {
    await surface.dispose();
    assert.ok(attempt<2,label+' was repeatedly replaced during the pointer probe');
    return assertWidgetTilt(page,selector,label,attempt+1);
  }
  await surface.dispose();
  assert.ok(left.rotation*right.rotation<0,label+' must follow the pointer across both sides: '+JSON.stringify({left,right,box}));
  assert.ok(right.lights>.8,label+' must show the pointer light');
  if (['nested fixture','full leaderboard'].includes(label)) await snapshot(page,'desktop-tilt-'+label.replaceAll(' ','-'));
  await page.mouse.move(0,0);
  await page.waitForFunction(selector=>{
    const matrix=new DOMMatrixReadOnly(getComputedStyle(document.querySelector(selector)).transform);
    return Math.abs(matrix.m13)<.0001 && Math.abs(matrix.m23)<.0001 && Math.abs(matrix.m42)<.05;
  },selector);
  assert.equal((await read()).active,0,label+' must settle on pointer exit');
}
async function assertStaticPointer(page,selector,label) {
  await page.locator(selector).first().hover();
  await page.waitForTimeout(80);
  const result=await page.locator(selector).first().evaluate(node=>{
    const matrix=new DOMMatrixReadOnly(getComputedStyle(node).transform);
    return {rotation:Math.abs(matrix.m13)+Math.abs(matrix.m23),active:document.querySelectorAll('.pm-tilting').length};
  });
  assert.equal(result.active,0,label+' must not activate tilt');
  assert.ok(result.rotation<.0001,label+' must remain level');
  await page.mouse.move(0,0);
}
async function pointAtStatistic(page) {
  const statistic=page.locator('.stat-card').first();
  await statistic.scrollIntoViewIfNeeded();
  // Complete the scroll before moving the mouse: scrolling intentionally resets
  // tilt, and a test runner's automatic scroll can arrive after locator.hover().
  await page.waitForTimeout(100);
  const box=await statistic.boundingBox();
  await page.mouse.move(0,0);
  await page.mouse.move(box.x+box.width*.25,box.y+box.height*.5,{steps:3});
  await page.waitForFunction(()=>!!document.querySelector('.pm-tilting'),null,{timeout:2500});
}
async function pickFlow(page,config,writes) {
  await navigate(page,'profile','.profile-account-actions');
  await page.locator('.profile-account-actions [data-action="logout"]').click();
  await visible(page,'#account-form');
  await page.locator('[data-action="auth-tab"][data-tab="register"]').click();
  const username='qa_'+config.name.replaceAll('-','')+'_'+run;
  await page.locator('#username').fill(username.slice(0,24));
  await page.locator('#display_name').fill('Motion QA');
  await page.locator('#password').fill('MotionTest2026!');
  await page.locator('#confirmation').fill('MotionTest2026!');
  await page.locator('#account-form button[type="submit"]').click();
  await visible(page,'.cinematic-dashboard');
  await statsMatch(page);
  const before=await state(page);
  assert.equal(before.demo,true,'browser QA must run in demo mode');
  assert.equal(before.me.role,'player');
  assert.equal(before.picks.filter(p=>p.user_id===before.me.id).length,0);
  await navigate(page,'games','.games-grid.full');
  const choices=page.locator('.team-choice:not(.unavailable)');
  assert.ok(await choices.count()>0);
  const game=await choices.first().getAttribute('data-game');
  const team=await choices.first().getAttribute('data-team');
  await choices.first().click();
  await visible(page,'dialog[open] [data-action="confirm-pick"]');
  const staged=await state(page);
  assert.equal(staged.picks.filter(p=>p.user_id===before.me.id).length,0,'opening confirmation cannot save');
  assert.equal(writes.length,0,'visual effects cannot issue a pick request');
  await snapshot(page,config.name+'-confirmation');
  const dialogBox=await page.locator('dialog').boundingBox();
  assert.ok(dialogBox.x>=0 && dialogBox.x+dialogBox.width<=config.width+1);
  assert.ok(dialogBox.y>=0 && dialogBox.y+dialogBox.height<=config.height+1);
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('dialog[open]').count(),0,'native Escape must close the dialog');
  assert.equal(writes.length,0);
  await page.locator('.team-choice[data-game="'+game+'"][data-team="'+team+'"]').click();
  await page.locator('dialog [data-action="confirm-pick"]').click();
  await page.waitForFunction(()=>!document.querySelector('dialog').open);
  const confirmed=await state(page);
  const own=confirmed.picks.find(p=>p.user_id===before.me.id && p.week===before.current_week);
  assert.ok(own);
  assert.equal(own.team,team);assert.equal(own.game_id,game);
  assert.equal(writes.length,1,'one confirmation must produce exactly one request');
  await visible(page,'.toast.show');
  await snapshot(page,config.name+'-confirmed');

  await page.locator('#week-select').selectOption(String(before.current_week+1));
  await visible(page,'.games-grid.full .team-choice[aria-disabled="true"]');
  assert.equal(await page.locator('.team-choice:not([aria-disabled="true"])').count(),0);
  // aria-disabled choices intentionally remain explanatory controls in the
  // established UI. Force bypasses Playwright's ARIA guard, not app validation.
  await page.locator('.team-choice').first().click({force:true});
  await visible(page,'dialog[open]');
  assert.equal(await page.locator('dialog [data-action="confirm-pick"]').count(),0,'future fixtures cannot be confirmed');
  await page.keyboard.press('Escape');
  await page.locator('#week-select').selectOption(String(before.current_week));

  await navigate(page,'profile','.stats-grid');
  await statsMatch(page);
  assert.equal(await page.locator('.admin-panel').count(),0,'ordinary players must not gain admin controls');
  await page.reload();
  await visible(page,'.profile-grid');
  await statsMatch(page);
  assert.ok((await state(page)).picks.some(p=>p.user_id===before.me.id && p.team===team),'pick and session survive reload');
  await navigate(page,'games','.games-grid.full');
  assert.equal(await page.locator('.team-choice[aria-pressed="true"]').getAttribute('data-team'),team);

  await page.context().setOffline(true);
  await page.waitForFunction(()=>[...document.querySelectorAll('.team-choice')].every(node=>node.getAttribute('aria-disabled')==='true'));
  await noOverflow(page,config.name+' offline');
  assert.equal(writes.length,1);
  await page.context().setOffline(false);
  await page.waitForFunction(()=>document.querySelector('.team-choice:not([aria-disabled="true"])'));
  await navigate(page,'profile','.profile-account-actions');
  await page.locator('.profile-account-actions [data-action="logout"]').click();
  await visible(page,'#account-form');
}
async function testSize(browser,config) {
  const {name,width,height,reduced=false,noEnhancement=false}=config;
  const context=await browser.newContext({
    viewport:{width,height},reducedMotion:reduced?'reduce':'no-preference',
    isMobile:width<=430,hasTouch:width<=430,deviceScaleFactor:1,serviceWorkers:'block'
  });
  if (noEnhancement) await context.route('**/js/immersive-motion.js',route=>route.abort());
  const page=await context.newPage();
  const errors=[],writes=[];
  const checkTilt=name==='desktop';
  page.on('pageerror',error=>errors.push(error.message));
  page.on('request',request=>{if (request.method()==='POST' && new URL(request.url()).pathname==='/api/pick') writes.push(request);});
  try {
    await page.goto(origin,{waitUntil:'domcontentloaded',timeout:25000});
    await visible(page,'#account-form');
    if (checkTilt) await assertWidgetTilt(page,'.auth-card','login widget');
    if (reduced || width<=430) await assertStaticPointer(page,'.auth-card','touch / reduced login');
    await snapshot(page,name+'-login');
    await noOverflow(page,name+' login');
    if (width<=620) {
      const size=await page.locator('#username').evaluate(node=>parseFloat(getComputedStyle(node).fontSize));
      assert.ok(size>=16,'phone forms must retain at least 16px text to avoid iOS focus zoom');
    }
    await page.locator('[data-action="auth-tab"][data-tab="register"]').click();
    assert.equal(await page.locator('#display_name').count(),1);
    assert.equal(await page.locator('#confirmation').count(),1);
    await page.locator('[data-action="auth-tab"][data-tab="login"]').click();
    assert.equal(await page.locator('#confirmation').count(),0);
    await page.locator('button[data-action="demo-login"][data-user="max"]').click();
    await visible(page,'.cinematic-dashboard .paetzold-stadium-hero');
    await statsMatch(page);
    await page.waitForTimeout(800);
    const hero=await page.locator('.paetzold-stadium-hero').evaluate(node=>{
      const player=node.querySelector('.paetzold-player'), picture=getComputedStyle(player);
      const photoRect=player.getBoundingClientRect(),heroRect=node.getBoundingClientRect();
      return {
        mask:picture.maskImage,mode:picture.mixBlendMode,image:picture.backgroundImage,imageSize:picture.backgroundSize,
        overlay:getComputedStyle(node.querySelector('.hero-player-area'),'::after').backgroundImage,
        frontVisible:getComputedStyle(node.querySelector('.paetzold-player-front')).display,
        photoRect:{width:photoRect.width,height:photoRect.height},heroRect:{width:heroRect.width,height:heroRect.height},
        copyAbovePhoto:Number(getComputedStyle(node.querySelector('.stadium-banner-copy')).zIndex)>Number(getComputedStyle(node.querySelector('.hero-player-area')).zIndex)
      };
    });
    assert.equal(hero.mask,'none');assert.equal(hero.frontVisible,'none');assert.equal(hero.mode,'normal');
    assert.match(hero.image,/paetzold-player\.png/);assert.equal(hero.imageSize,'cover');assert.match(hero.overlay,/gradient/);
    assert.ok(hero.copyAbovePhoto,'headline must stay above the original photograph');
    assert.ok(hero.photoRect.width>=hero.heroRect.width && hero.photoRect.height>=hero.heroRect.height);
    assert.equal((await page.request.get(origin+'/icons/paetzold-player.png')).status(),200);
    await noOverflow(page,name+' dashboard');
    assert.equal(await page.locator('.stat-card').count(),4);
    await snapshot(page,name+'-dashboard');
    if (checkTilt) {
      for (const [selector,label] of [
        ['.stat-card','statistic'],['.paetzold-stadium-hero','photo hero'],
        ['.pick-hero','current pick'],['.game-card','nested fixture'],
        ['.ranking-panel','dashboard leaderboard'],['.recent-panel','recent picks'],
        ['.dashboard-aside>.rule-note','rules widget']
      ]) await assertWidgetTilt(page,selector,label);
      await pointAtStatistic(page);
      await page.evaluate(()=>window.scrollBy(0,40));
      await page.waitForFunction(()=>!document.querySelector('.pm-tilting'));
      await page.mouse.move(0,0);
    }
    if (reduced || width<=430) await assertStaticPointer(page,'.stat-card','touch / reduced statistic');
    if (!noEnhancement && !reduced) await assertQuietRefresh(page);

    await navigate(page,'games','.games-grid.full');
    assert.ok(await page.locator('.games-grid.full .game-card').count()>0);
    await noOverflow(page,name+' games');
    await page.evaluate(()=>window.scrollTo(0,Math.min(600,document.body.scrollHeight)));
    await page.waitForTimeout(760);
    const onScreen=await page.evaluate(()=>{
      const cards=[...document.querySelectorAll('.games-grid.full .game-card')];
      const inView=cards.filter(el=>{const r=el.getBoundingClientRect();return r.bottom>70 && r.top<innerHeight-85;});
      return {count:inView.length,visible:inView.filter(el=>Number.parseFloat(getComputedStyle(el).opacity)>.90 && getComputedStyle(el).visibility!=='hidden').length};
    });
    assert.ok(onScreen.count>0 && onScreen.visible>0,name+' blank games after swipe: '+JSON.stringify(onScreen));
    await snapshot(page,name+'-games');

    await navigate(page,'season','.season-panel');
    await noOverflow(page,name+' season');
    const matrix=await page.locator('.table-scroll').evaluate(node=>({content:node.scrollWidth,visible:node.clientWidth}));
    assert.ok(matrix.content>matrix.visible,'only the season matrix should scroll horizontally');
    await page.locator('.table-scroll').press('ArrowRight');
    await snapshot(page,name+'-season');
    if (checkTilt) {
      await assertWidgetTilt(page,'.season-panel','season matrix');
      await assertWidgetTilt(page,'.season-milestones>div','season milestone');
    }

    await navigate(page,'leaderboard','.leaderboard-panel');
    assert.ok(await page.locator('.leaderboard-row').count()>0);
    await noOverflow(page,name+' leaderboard');
    if (width<=620) {
      const centers=await page.locator('.leaderboard-row').first().evaluate(row=>
        [...row.children].map(node=>{const r=node.getBoundingClientRect();return r.top+r.height/2;}));
      assert.ok(Math.max(...centers)-Math.min(...centers)<4,'phone ranking names and values must align in one row');
    }
    assert.ok(!(await page.locator('.leaderboard-panel').innerText()).includes('Ausgeschieden'));
    await snapshot(page,name+'-leaderboard');
    if (checkTilt) await assertWidgetTilt(page,'.leaderboard-panel','full leaderboard');

    await navigate(page,'profile','.profile-grid');
    await statsMatch(page);
    assert.ok(await page.locator('.inventory-team').count()>=30);
    await noOverflow(page,name+' profile');
    await snapshot(page,name+'-profile');
    if (checkTilt) {
      for (const [selector,label] of [
        ['.inventory-team','nested team tile'],['.history-panel','pick history'],
        ['.account-setting','nested account widget']
      ]) await assertWidgetTilt(page,selector,label);
    }
    await page.locator('.page-content [data-action="rules"]').first().click();
    await visible(page,'dialog[open]');
    if (checkTilt) await assertWidgetTilt(page,'#modal','native dialog');
    await page.locator('dialog [data-action="close-modal"]').first().click();
    await page.locator('.inventory-team').first().click();
    await visible(page,'dialog[open] .team-info-row');
    await page.keyboard.press('Escape');

    if (!noEnhancement && !reduced) {
      await navigate(page,'dashboard','.stats-grid');
      if (checkTilt) {
        await pointAtStatistic(page);
      }
      await page.emulateMedia({reducedMotion:'reduce'});
      await statsMatch(page);
      // matchMedia change listeners are delivered at the next rendering update.
      // Wait for that update instead of asserting during the same task.
      await page.waitForFunction(()=>document.getAnimations().every(a=>a.playState!=='running'),null,{timeout:2500});
      const transitions=await page.locator('button,input,select').evaluateAll(nodes=>nodes.every(node=>getComputedStyle(node).transitionDuration.split(',').every(value=>parseFloat(value)===0)));
      assert.ok(transitions,'reduced motion must override legacy important control transitions');
      await assertStaticPointer(page,'.stat-card','live reduced motion preference');
      await page.emulateMedia({reducedMotion:'no-preference'});
    }
    if (reduced) {
      const moving=await page.evaluate(()=>document.getAnimations().filter(a=>a.playState==='running').length);
      assert.equal(moving,0,'reduced motion must have a fully static presentation');
    }
    await pickFlow(page,config,writes);
    assert.deepEqual(errors,[],name+' client-side errors');
    console.log('PASS',name,width+'×'+height,'reduced:',reduced,'enhancement:',!noEnhancement,'all 5 views + register / confirm / cancel / reload / offline / logout');
  } finally {await context.close();}
}
(async()=>{
  const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
  try {
    for (const config of [
      {name:'desktop',width:1440,height:1000},
      {name:'tablet',width:820,height:1180},
      {name:'phone',width:390,height:844},
      {name:'compact',width:320,height:740},
      {name:'phone-reduced',width:390,height:844,reduced:true},
      {name:'no-motion-script',width:390,height:844,noEnhancement:true}
    ]) await testSize(browser,config);
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
