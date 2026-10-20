/* Renderer/controller unit checks with a minimal DOM adapter, NOT a browser test.
   No npm install needed. Run: node tests/test_frontend.cjs
   First run: python3 tests/export_snapshot.py */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const snapshot = JSON.parse(fs.readFileSync(process.argv[2] || path.join(__dirname, 'snapshot.json'), 'utf8'));
const makeElement = () => ({innerHTML:'',textContent:'',hidden:true,dataset:{},open:false,
  classList:{add(){},remove(){}},addEventListener(){},showModal(){this.open=true;},close(){this.open=false;}});
const elements = {'#app':makeElement(),'#modal':makeElement(),'#toast':makeElement()};
const tools = new Map(), events = new Map();
const sandbox = {console,Intl,Date,performance:{now:()=>100},AbortSignal,AbortController,
  setInterval(){},setTimeout(){},clearTimeout(){},
  matchMedia:()=>({matches:false}),
  location:{hash:'#dashboard',protocol:'http:'},navigator:{},
  window:{addEventListener(){},scrollTo(){},matchMedia:()=>({matches:false})},
  document:{title:'',hidden:false,
    querySelector:s=>elements[s]||null,querySelectorAll:()=>[],
    addEventListener:(name,fn)=>events.set(name,fn),
    modelContext:{registerTool:tool=>{tools.set(tool.name,tool);}}},
  fetch:async()=>({ok:true,json:async()=>({gated:false,authenticated:false})})};
vm.createContext(sandbox);
let source = fs.readFileSync(path.join(root,'public/js/app.js'),'utf8');
// Expose closures ONLY in this in-memory copy; the shipped app stays private.
source=source.replace('  bootstrap();\n})();', '  globalThis.testAPI={state,receive,render,renderAuth,eligibility,stagePick,showRules,showTeamInfo,demoPanel,usage};\n})();');
vm.runInContext(source,sandbox);
const t=sandbox.testAPI;
let passed=0;
function test(name,fn){fn();passed++;console.log(`PASS ${name}`);}
test('login opens without any shared pool password gate',()=>{
  t.renderAuth();
  const html=elements['#app'].innerHTML;
  assert.match(html,/Einloggen/);
  assert.match(html,/id="username"/);
  assert.match(html,/id="password"/);
  assert.doesNotMatch(html,/Pool öffnen|Gemeinsames Pool-Passwort|d2026-|mini-player/);
});
test('demo authentication and registration render required fields',()=>{
  t.state.demo=true;t.renderAuth();assert.match(elements['#app'].innerHTML,/Mit|Demo|DEMO/);assert.match(elements['#app'].innerHTML,/data-user="max"/);
  t.state.authTab='register';t.renderAuth();for(const id of ['username','display_name','password','confirmation'])assert.match(elements['#app'].innerHTML,new RegExp(`id="${id}"`));
});
t.receive(snapshot);
test('all five routes render real backend snapshot without exceptions',()=>{
  for(const route of ['dashboard','games','season','leaderboard','profile']){
    t.state.route=route;t.render();const html=elements['#app'].innerHTML;
    assert.match(html,/SURVIVOR/);assert.match(html,/id="main"/);assert.doesNotMatch(html,/undefined|NaN/);assert.match(html,/aria-current="page"/);
  }
});
test('used team and opponent cap explain the correct restriction',()=>{
  const games=Object.fromEntries(snapshot.games.map(g=>[g.id,g]));
  assert.ok(t.eligibility(games['d2026-5-1'],'KC').used);
  assert.ok(t.eligibility(games['d2026-5-2'],'MIA').blockedOpponent);
  const patriots=t.eligibility(games['d2026-5-2'],'NE');assert.equal(patriots.reasons.length,0);assert.ok(patriots.againstMax);
});
test('staging a legal pick opens confirmation without saving',()=>{
  const count=t.state.data.picks.length;t.stagePick('d2026-5-0','BAL');
  assert.ok(elements['#modal'].open);assert.match(elements['#modal'].innerHTML,/Möchtest du wirklich/);assert.match(elements['#modal'].innerHTML,/Tipp bestätigen/);assert.equal(t.state.data.picks.length,count);
});
test('blocked choice displays explanation without confirmation action',()=>{
  t.stagePick('d2026-5-1','KC');assert.match(elements['#modal'].innerHTML,/bereits verwendet/);assert.doesNotMatch(elements['#modal'].innerHTML,/confirm-pick/);
});
test('future week and Super Bowl render without selectable green teams',()=>{
  t.state.route='games';t.state.week=22;t.render();assert.match(elements['#app'].innerHTML,/Super Bowl/);assert.match(elements['#app'].innerHTML,/Noch nicht geöffnet/);assert.doesNotMatch(elements['#app'].innerHTML,/team-availability good/);
});
test('locked pick blocks switching to any later fixture',()=>{
  const copy=structuredClone(snapshot);const current=copy.games.find(g=>g.id==='d2026-5-0');
  copy.picks.push({user_id:1,week:5,team:'BAL',opponent:'CIN',game_id:current.id,result:'pending',locked:true,locked_at:copy.now});
  t.receive(copy);t.state.route='games';t.state.week=5;t.render();
  const later=copy.games.find(g=>g.week===5&&g.kickoff>current.kickoff);
  assert.ok(t.eligibility(later,later.away).reasons.some(r=>r.includes('gesperrt')));
  assert.doesNotMatch(elements['#app'].innerHTML,/team-availability good/);
});
test('display names are HTML escaped throughout all views',()=>{
  const copy=structuredClone(snapshot);copy.me.display_name='<img src=x onerror=alert(1)>';
  copy.players.find(p=>p.id===copy.me.id).display_name=copy.me.display_name;
  t.receive(copy);t.state.route='dashboard';t.render();
  assert.doesNotMatch(elements['#app'].innerHTML,/<img src=x/);assert.match(elements['#app'].innerHTML,/&lt;img/);
});
test('zero-history account and empty live feed have useful empty states',()=>{
  const copy=structuredClone(snapshot);copy.picks=[];copy.games=[];copy.me.stats={wins:0,losses:0,total:0,pending:0,pushes:0,rate:0,survivor:true,missed:[]};
  t.receive(copy);t.state.route='dashboard';t.render();assert.match(elements['#app'].innerHTML,/Noch keine Begegnungen/);assert.doesNotMatch(elements['#app'].innerHTML,/NaN|undefined/);
  t.state.route='profile';t.render();assert.match(elements['#app'].innerHTML,/Noch kein Tipp/);assert.match(elements['#app'].innerHTML,/profile-account-actions/);
});
t.receive(snapshot);
test('rules, team detail and admin demo dialogs render',()=>{
  t.showRules();assert.match(elements['#modal'].innerHTML,/Dreimal dagegen/);
  t.showTeamInfo('NE');assert.match(elements['#modal'].innerHTML,/3 \/ 3/);
  t.demoPanel();assert.match(elements['#modal'].innerHTML,/Kickoff simulieren/);assert.match(elements['#modal'].innerHTML,/Spiel beenden/);
});
test('offline state prohibits any new pick',()=>{
  t.state.online=false;const current=snapshot.games.find(g=>g.id==='d2026-5-0');
  assert.ok(t.eligibility(current,'BAL').reasons.some(r=>r.includes('Verbindung')));t.state.route='games';t.state.week=5;t.render();assert.match(elements['#app'].innerHTML,/Verbindung unterbrochen/);t.state.online=true;
});
test('optional WebMCP registration, validation and state readback',()=>{
  assert.equal(tools.size,2);const read=tools.get('read_survivor_status'),stage=tools.get('stage_survivor_pick');
  assert.equal(read.annotations.readOnlyHint,true);assert.equal(read.execute({}).week,5);
  const before=t.state.data.picks.length;assert.equal(stage.execute({game_id:'d2026-5-0',team:'BAL'}).saved,false);
  assert.ok(elements['#modal'].open);assert.equal(t.state.data.picks.length,before);
  assert.throws(()=>stage.execute({game_id:'bad',team:'BAL'}));assert.throws(()=>read.execute({injected:true}));
});
test('game cards show privacy-safe pool tip percentages after kickoff',()=>{
  const copy=structuredClone(snapshot);
  copy.pick_rates={'d2026-5-0':{total:4,percent:{BAL:75,CIN:25},counts:{BAL:3,CIN:1}}};
  t.receive(copy);t.state.route='dashboard';t.render();
  const html=elements['#app'].innerHTML;
  assert.match(html,/POOL-TIPPQUOTEN/);
  assert.match(html,/75%/);
  assert.match(html,/25%/);
  assert.match(html,/4 Tipps/);
  assert.match(html,/Nach Spielbeginn sichtbar/);
  t.receive(snapshot);
});
test('external real betting-ticket percentages show separately from pool stats',()=>{
  const copy=structuredClone(snapshot);
  const game=copy.games.find(g=>g.week===5);
  game.public_bet_percent={[game.away]:65,[game.home]:35};
  game.public_bet_source='DraftKings';
  game.public_bet_updated_at=copy.now;
  t.receive(copy);t.state.week=5;t.state.route='games';t.render();
  const html=elements['#app'].innerHTML;
  assert.match(html,/SO WIRD GEWETTET/);
  assert.match(html,/65%/);
  assert.match(html,/35%/);
  assert.match(html,/DraftKings/);
  assert.match(html,/POOL-TIPPQUOTEN/);
  assert.doesNotMatch(html,/ESPN-WETTQUOTEN|Handicap|Über \/ Unter|Moneyline · Dezimal/);
  t.receive(snapshot);
});
test('leaderboards show standings without eliminated labels or status column',()=>{
  const copy=structuredClone(snapshot);
  copy.players.forEach(player=>{player.stats.survivor=false;});
  copy.me.stats.survivor=false;
  t.receive(copy);
  t.state.route='leaderboard';t.render();
  const full=elements['#app'].innerHTML;
  const leaderboard=full.match(/<section class="panel leaderboard-panel">[\s\S]*?<\/section>/)?.[0];
  assert.ok(leaderboard);
  assert.doesNotMatch(leaderboard,/Status|Ausgeschieden|Im Rennen|rank-status/);
  assert.match(leaderboard,/Richtige/);
  assert.match(leaderboard,/Falsche/);
  assert.match(leaderboard,/Tipps/);
  t.state.route='dashboard';t.render();
  const dashboard=elements['#app'].innerHTML;
  const mini=dashboard.match(/<div class="mini-ranking">[\s\S]*?<\/div><a class="panel-link"/)?.[0];
  assert.ok(mini);
  assert.doesNotMatch(mini,/Ausgeschieden|Im Rennen/);
  assert.match(mini,/mini-player-name/);
  assert.match(mini,/rank-crown/);
  t.receive(snapshot);
});
test('moneyline ticket percentages flank center chart with original team logos',()=>{
  const copy=structuredClone(snapshot);
  const game=copy.games.find(g=>g.week===5);
  game.public_bet_percent={[game.away]:65,[game.home]:35};
  game.public_bet_updated_at=copy.now;
  t.receive(copy);t.state.route='games';t.state.week=5;t.render();
  const html=elements['#app'].innerHTML;
  assert.match(html,/public-bets-matchup/);
  assert.match(html,/public-bets-away/);
  assert.match(html,/public-bets-home/);
  assert.match(html,/team-logo-wrap tiny/);
  const chart=html.match(/<div class="public-bets-matchup">[\s\S]*?<\/div>[\s\S]*?<\/div>/)?.[0] || html;
  assert.ok(chart.indexOf('public-bets-away') < chart.indexOf('public-bets-bar'));
  assert.ok(html.indexOf('public-bets-bar') < html.indexOf('public-bets-home'));
  t.receive(snapshot);
});
test('eliminated players remain allowed to participate in later weeks',()=>{
  const copy=structuredClone(snapshot);
  copy.me.stats.survivor=false;
  copy.rules.allow_after_elimination=false;
  t.receive(copy);
  const game=copy.games.find(g=>g.id==='d2026-5-0');
  assert.ok(game);
  assert.ok(!t.eligibility(game,'CIN').reasons.some(reason=>reason.includes('ausgeschieden')));
  t.receive(snapshot);
});
test('immersive dashboard motion layers the player without changing pool data',()=>{
  t.receive(snapshot);t.state.route='dashboard';t.render();
  const html=elements['#app'].innerHTML;
  assert.match(html,/class="real-football-player paetzold-player"/);
  assert.match(html,/class="paetzold-player-front"/);
  assert.match(html,/stadium-banner-copy/);
  assert.match(html,/SURVIVOR/);
  assert.match(html,/POOL/);
  assert.match(html,/mini-ranking/);
  assert.match(html,/game-card/);
});
test('motion assets are decorative, locally served and reduced-motion safe',()=>{
  const motion=fs.readFileSync(path.join(root,'public/js/immersive-motion.js'),'utf8');
  const css=fs.readFileSync(path.join(root,'public/css/app.css'),'utf8');
  const index=fs.readFileSync(path.join(root,'public/index.html'),'utf8');
  const worker=fs.readFileSync(path.join(root,'public/service-worker.js'),'utf8');
  assert.doesNotThrow(()=>new Function(motion));
  assert.match(index,/js\/immersive-motion\.js/);
  assert.match(worker,/immersive-motion\.js/);
  assert.match(motion,/prefers-reduced-motion: reduce/);
  assert.match(motion,/IntersectionObserver/);
  assert.match(motion,/passive:true/);
  assert.match(css,/paetzold-player-front/);
  assert.match(css,/motion-reveal-item/);
  assert.match(css,/prefers-reduced-motion:reduce/);
});
test('original photo is clipped to a real vector player silhouette, not screen blended',()=>{
  const css=fs.readFileSync(path.join(root,'public/css/app.css'),'utf8');
  const svg=fs.readFileSync(path.join(root,'public/icons/paetzold-silhouette.svg'),'utf8');
  const start=css.lastIndexOf('SURVIVOR POOL • PREMIUM MOTION / TRANSPARENT PLAYER');
  assert.ok(start>0,'the final cutout overrides should be at the bottom of CSS');
  const overrides=css.slice(start);
  assert.match(overrides,/paetzold-silhouette\.svg/);
  assert.match(overrides,/mask-size:contain!important/);
  assert.match(overrides,/mix-blend-mode:normal!important/);
  assert.match(overrides,/paetzold-player-front/);
  assert.match(overrides,/clip-path:polygon/);
  assert.match(overrides,/prefers-reduced-motion:reduce/);
  assert.match(svg,/viewBox="0 0 1024 1536"/);
  assert.match(svg,/<path fill="#fff" d="M/);
  assert.ok(svg.length>2000 && svg.length<10000,'keep cutout vector compact');
  const sw=fs.readFileSync(path.join(root,'public/service-worker.js'),'utf8');
  assert.match(sw,/paetzold-silhouette\.svg/);
  assert.doesNotMatch(overrides,/background-image:url\('https?:\/\//);
});
test('touch parallax uses passive events, handles touch end, and never interferes with pool picks',()=>{
  const js=fs.readFileSync(path.join(root,'public/js/immersive-motion.js'),'utf8');
  assert.match(js,/pointerType\s*===\s*'touch'/);
  assert.match(js,/pointercancel/);
  assert.match(js,/pointerup/);
  assert.match(js,/prefers-reduced-motion: reduce/);
  assert.doesNotMatch(js,/preventDefault\(|fetch\(|\/api\/pick/);
  assert.doesNotThrow(()=>new Function(js));
});
test('premium design styles every existing route without adding APIs or remote libraries',()=>{
  const css=fs.readFileSync(path.join(root,'public/css/premium.css'),'utf8');
  const html=fs.readFileSync(path.join(root,'public/index.html'),'utf8');
  const worker=fs.readFileSync(path.join(root,'public/service-worker.js'),'utf8');
  assert.ok(css.length > 18000, 'substantial new design across all pages');
  for(const selector of [
    '.sidebar','.topbar','.bottom-nav','.page-heading',
    '.stat-card','.pick-hero','.game-card','.leaderboard-panel',
    '.season-table','.history-pick','.inventory-team',
    '.account-setting','.auth-card','dialog','.toast'
  ]) assert.ok(css.includes(selector), selector+' should be visually enhanced');
  assert.match(html,/css\/app\.css/);
  assert.match(html,/css\/premium\.css/);
  assert.ok(html.indexOf('css/app.css')<html.indexOf('css/premium.css'),
    'new overrides must load after stable existing CSS');
  assert.match(worker,/css\/premium\.css/);
  assert.match(css,/--premium-blue:/);
  assert.match(css,/--premium-red:/);
  assert.match(css,/prefers-reduced-motion:reduce/);
  assert.match(css,/@media\(max-width:760px\)/);
  assert.match(css,/@media\(max-width:430px\)/);
  assert.match(css,/paetzold-silhouette\.svg/);
  assert.match(css,/mix-blend-mode:normal!important/);
  assert.doesNotMatch(css,/@import|fonts\.googleapis|new CSSStyleSheet/);
  assert.equal((css.match(/\{/g)||[]).length, (css.match(/\}/g)||[]).length);
});
test('new motion director is accessibility and data safe with DOM unavailable',()=>{
  const code=fs.readFileSync(path.join(root,'public/js/immersive-motion.js'),'utf8');
  assert.doesNotThrow(()=>new Function(code));
  for(const phrase of [
    'IntersectionObserver','MutationObserver','requestAnimationFrame',
    'premium','prefers-reduced-motion: reduce','pointercancel',
    'pointerup','visibilitychange','pm-route-enter','pm-visible'
  ]) assert.ok(code.includes(phrase), phrase+' is required');
  assert.doesNotMatch(code,/preventDefault\s*\(|\bfetch\s*\(|XMLHttpRequest|\.submit\(|\/api\/pick/);
  const registrations=[];
  const fakeRoot={querySelector:()=>null,querySelectorAll:()=>[]};
  const mql={matches:true,addEventListener(){}};
  const sandbox2={
    document:{querySelector:key=>key==='#app'?fakeRoot:null,addEventListener:(key)=>registrations.push('document:'+key),hidden:false},
    window:{matchMedia:()=>mql,addEventListener:(key)=>registrations.push('window:'+key)},
    MutationObserver:class{observe(){}},
    requestAnimationFrame:()=>1,cancelAnimationFrame(){},
    location:{hash:'#dashboard'},
    console
  };
  assert.doesNotThrow(()=>vm.runInNewContext(code,sandbox2));
  assert.ok(registrations.some(r=>r==='window:scroll'));
  assert.ok(registrations.some(r=>r==='document:pointermove'));
});
test('public frontend contains neither shared password nor private hashes',()=>{
  const js=fs.readFileSync(path.join(root,'public/js/app.js'),'utf8');
  assert.doesNotMatch(js,/NURDERHSV|scrypt\$/);
});
console.log(`\n${passed} frontend checks passed (DOM adapter; no layout/browser coverage).`);
