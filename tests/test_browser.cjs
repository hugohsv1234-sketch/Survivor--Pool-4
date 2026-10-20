/* Real Chromium responsive smoke test. CI-only Playwright dependency. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const origin = process.env.SURVIVOR_TEST_ORIGIN || 'http://127.0.0.1:8765';
const save = path.resolve(__dirname, '../test-results');
fs.mkdirSync(save, { recursive:true });

async function visible(page,selector,timeout=12000) {
  const element=page.locator(selector).first();
  await element.waitFor({state:'visible',timeout});
  return element;
}
async function snapshot(page,name) {
  await page.screenshot({path:path.join(save,name+'.png'),animations:'disabled'});
}
async function testSize(browser, config) {
  const {name,width,height,reduced=false}=config;
  const context=await browser.newContext({
    viewport:{width,height},
    reducedMotion:reduced?'reduce':'no-preference',
    isMobile:name==='phone'||name==='phone-reduced',
    hasTouch:name==='phone'||name==='phone-reduced',
    deviceScaleFactor:1,
    serviceWorkers:'block'
  });
  const page=await context.newPage();
  const errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  try {
    await page.goto(origin,{waitUntil:'domcontentloaded',timeout:25000});
    await visible(page,'#account-form');
    await page.locator('button[data-action="demo-login"][data-user="max"]').click();
    await visible(page,'.cinematic-dashboard .paetzold-stadium-hero');
    await page.waitForTimeout(700);
    const hero=await page.locator('.paetzold-stadium-hero').evaluate(node=>{
      const player=node.querySelector('.paetzold-player');
      const front=node.querySelector('.paetzold-player-front');
      const picture=getComputedStyle(player);
      const copy=node.querySelector('.stadium-banner-copy');
      const photoRect=player.getBoundingClientRect();
      const heroRect=node.getBoundingClientRect();
      return {
        background:getComputedStyle(node).backgroundImage,
        mask:picture.maskImage,
        mode:picture.mixBlendMode,
        image:picture.backgroundImage,
        imageSize:picture.backgroundSize,
        overlay:getComputedStyle(node.querySelector('.hero-player-area'),'::after').backgroundImage,
        frontVisible:getComputedStyle(front).display,
        photoRect:{width:photoRect.width,height:photoRect.height},
        heroRect:{width:heroRect.width,height:heroRect.height},
        copyAbovePhoto:Number(getComputedStyle(copy).zIndex)>Number(getComputedStyle(node.querySelector('.hero-player-area')).zIndex)
      };
    });
    assert.equal(hero.mask,'none','new full-frame player photo must not use the old silhouette mask');
    assert.equal(hero.frontVisible,'none','only one player photo layer should appear');
    assert.equal(hero.mode,'normal');
    assert.match(hero.image,/paetzold-player\.png/);
    assert.equal(hero.imageSize,'cover');
    assert.match(hero.overlay,/gradient/);
    assert.ok(hero.copyAbovePhoto,'SURVIVOR POOL lettering must be above the photo');
    assert.ok(hero.photoRect.width>=hero.heroRect.width && hero.photoRect.height>=hero.heroRect.height,
      'photo must cover entire hero banner');
    assert.equal((await page.request.get(origin+'/icons/paetzold-player.png')).status(),200);
    const overflow=await page.evaluate(()=>
      document.documentElement.scrollWidth-document.documentElement.clientWidth);
    assert.ok(overflow<=2,name+' dashboard overflow: '+overflow+'px');
    assert.equal(await page.locator('.stat-card').count(),4);
    const statsBox=await page.locator('.stats-grid').boundingBox();
    assert.ok(statsBox && statsBox.x+statsBox.width<=width+2,
      name+' stat cards clipped on right by '+(statsBox.x+statsBox.width-width)+'px');
    await snapshot(page,name+'-dashboard');

    const nav=await page.locator('.bottom-nav a[href="#games"]').isVisible() ? '.bottom-nav a' : '.sidebar .nav-link';
    await page.locator(nav+'[href="#games"]').click();
    await visible(page,'.games-grid.full');
    assert.ok(await page.locator('.games-grid.full .game-card').count()>0);
    const gamesBox=await page.locator('.games-grid.full').boundingBox();
    assert.ok(gamesBox && gamesBox.x+gamesBox.width<=width+2,
      name+' games grid clipped on right by '+(gamesBox.x+gamesBox.width-width)+'px');
    await page.evaluate(()=>window.scrollTo(0,Math.min(600,document.body.scrollHeight)));
    await page.waitForTimeout(720);
    // Regression: offscreen reveal animations must NOT hide all cards
    // after a quick mobile swipe. The screenshot should never be blank.
    const onScreen=await page.evaluate(()=>{
      const cards=[...document.querySelectorAll('.games-grid.full .game-card')];
      const inView=cards.filter(el=>{
        const r=el.getBoundingClientRect();
        return r.bottom>65 && r.top<innerHeight-70;
      });
      return {count:inView.length, visible:inView.filter(el=>
        Number.parseFloat(getComputedStyle(el).opacity)>.90 &&
        getComputedStyle(el).visibility!=='hidden').length};
    });
    assert.ok(onScreen.count>0 && onScreen.visible>0,
      name+' shows blank games after swipe: '+JSON.stringify(onScreen));
    await snapshot(page,name+'-games');

    await page.locator(nav+'[href="#leaderboard"]').click();
    await visible(page,'.leaderboard-panel');
    assert.ok(await page.locator('.leaderboard-row').count()>0);
    const leadersBox=await page.locator('.leaderboard-panel').boundingBox();
    assert.ok(leadersBox && leadersBox.x+leadersBox.width<=width+2,
      name+' leaderboard clipped on right by '+(leadersBox.x+leadersBox.width-width)+'px');
    assert.ok(!(await page.locator('.leaderboard-panel').innerText()).includes('Ausgeschieden'));
    await snapshot(page,name+'-leaderboard');

    await page.locator(nav+'[href="#profile"]').click();
    await visible(page,'.profile-grid');
    await visible(page,'.team-inventory');
    assert.ok(await page.locator('.inventory-team').count()>=30);
    await snapshot(page,name+'-profile');
    const otherOverflow=await page.evaluate(()=>
      document.documentElement.scrollWidth-document.documentElement.clientWidth);
    assert.ok(otherOverflow<=2,name+' profile overflow: '+otherOverflow+'px');

    const trigger=page.locator('[data-action="rules"]').first();
    if(await trigger.isVisible()) {
      await trigger.click();
      await visible(page,'dialog[open]');
      await page.locator('dialog [data-action="close-modal"]').first().click();
    }
    assert.deepEqual(errors,[],name+' had client-side JavaScript errors');
    console.log('PASS',name,width+'×'+height,'reduce motion:',reduced);
  } finally {
    await context.close();
  }
}
(async()=>{
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 try {
   for(const spec of [
     {name:'desktop',width:1440,height:900},
     {name:'tablet',width:820,height:1180},
     {name:'phone',width:390,height:844},
     {name:'phone-reduced',width:390,height:844,reduced:true}
   ]) await testSize(browser,spec);
 } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
