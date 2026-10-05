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
  window:{addEventListener(){},scrollTo(){}},
  document:{title:'',hidden:false,
    querySelector:s=>elements[s]||null,querySelectorAll:()=>[],
    addEventListener:(name,fn)=>events.set(name,fn),
    modelContext:{registerTool:tool=>{tools.set(tool.name,tool);}}},
  fetch:async()=>({ok:true,json:async()=>({gated:false,authenticated:false})})};
vm.createContext(sandbox);
let source = fs.readFileSync(path.join(root,'public/js/app.js'),'utf8');
// Expose closures ONLY in this in-memory copy; the shipped app stays private.
source=source.replace('  bootstrap();\n})();', '  globalThis.testAPI={state,receive,render,renderGate,renderAuth,eligibility,stagePick,showRules,showTeamInfo,demoPanel,usage};\n})();');
vm.runInContext(source,sandbox);
const t=sandbox.testAPI;
let passed=0;
function test(name,fn){fn();passed++;console.log(`PASS ${name}`);}
test('gate exposes no games or private player data',()=>{
  t.renderGate();assert.match(elements['#app'].innerHTML,/Pool öffnen/);assert.doesNotMatch(elements['#app'].innerHTML,/d2026-|Survivor2026|NURDERHSV|mini-player/);
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
test('public frontend contains neither shared password nor private hashes',()=>{
  const js=fs.readFileSync(path.join(root,'public/js/app.js'),'utf8');
  assert.doesNotMatch(js,/NURDERHSV|scrypt\$/);
});
console.log(`\n${passed} frontend checks passed (DOM adapter; no layout/browser coverage).`);
