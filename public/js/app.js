/* Survivor Pool — dependency-free UI. The backend validates every write again. */
(() => {
  'use strict';
  const $ = (s, root = document) => root.querySelector(s);
  const $$ = (s, root = document) => [...root.querySelectorAll(s)];
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const app = $('#app'), modal = $('#modal');
  const state = { data: null, csrf: '', route: 'dashboard', week: null, filter: 'all', authTab: 'login', online: true, syncAt: 0, serverNow: 0, prompt: null, installed: matchMedia('(display-mode: standalone)').matches, busy: false, epoch: 0 };
  const icons = {
    dashboard: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    games: '<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M7 3v4m10-4v4M3 11h18m-13 5h2m4 0h2"/>',
    season: '<path d="M4 20V10m5 10V4m6 16v-8m5 8V7"/>',
    leaderboard: '<path d="M8 3h8v6a4 4 0 0 1-8 0V3Zm0 2H4v3a4 4 0 0 0 4 4m8-7h4v3a4 4 0 0 1-4 4m-4 1v6m-4 2h8"/>',
    profile: '<circle cx="12" cy="8" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/>',
    logout: '<path d="M9 4H4v16h5m5-12 4 4-4 4m-6-4h11"/>',
    lock: '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3m-4 5v2"/>',
    check: '<path d="m5 12 4 4L19 6"/>',
    close: '<path d="m6 6 12 12M6 18 18 6"/>',
    chevron: '<path d="m9 5 7 7-7 7"/>',
    download: '<path d="M12 3v12m-4-4 4 4 4-4M4 17v4h16v-4"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v1"/>',
    eye: '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
    refresh: '<path d="M20 7a9 9 0 1 0 1 8M20 3v5h-5"/>',
    bolt: '<path d="m13 2-9 12h7l-1 8 10-13h-7l1-7Z"/>',
    shield: '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z"/><path d="m8 12 3 3 5-6"/>',
    ball: '<ellipse cx="12" cy="12" rx="10" ry="6" transform="rotate(-35 12 12)"/><path d="m8 15 8-6m-7 2 3 4m0-7 3 4"/>'
  };
  const icon = (name, cls = '') => `<svg class="icon ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name] || icons.info}</svg>`;
  const brand = () => `<span class="brand-symbol">S<span></span></span><span class="brand-name">SURVIVOR<span>POOL</span></span>`;
  const now = () => state.serverNow + (performance.now() - state.syncAt) / 1000;
  const teams = () => Object.fromEntries(state.data.teams.map(t => [t.id, t]));
  const ownPicks = () => state.data.picks.filter(p => p.user_id === state.data.me.id);
  const currentPick = () => ownPicks().find(p => p.week === state.data.current_week);
  const gameById = id => state.data.games.find(g => g.id === id);
  const weekLabel = n => state.data.weeks.find(w => w.number === n)?.name || `Week ${n}`;
  const date = (timestamp, opts = {}) => new Intl.DateTimeFormat('de-DE', {day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit',...opts}).format(new Date(timestamp * 1000));
  const timeOnly = timestamp => new Intl.DateTimeFormat('de-DE', {hour:'2-digit',minute:'2-digit'}).format(new Date(timestamp * 1000));
  const zone = () => Intl.DateTimeFormat().resolvedOptions().timeZone;
  const locked = p => !!p && (p.locked || isStarted(gameById(p.game_id)));
  const isStarted = g => !!g && ((g.status === 'scheduled' && g.kickoff <= now()) || ['live','final'].includes(g.status) || g.started_at != null);
  const badge = (text, tone = '') => `<span class="badge ${tone}">${text}</span>`;
  const resultText = r => ({win:'Richtig ✓',loss:'Falsch ✕',pending:'Noch offen',push:'Tie · neutral'}[r]);
  const avatar = (name, large = '') => `<span class="avatar ${large}">${esc(name.slice(0,2).toUpperCase())}</span>`;
  const teamBadge = (id, size = '') => {const t = teams()[id]; return t.logo ? `<img class="team-logo ${size}" src="${esc(t.logo)}" alt="${esc(t.full_name)}">` : `<span class="team-mark ${size}" style="--team:${esc(t.color)}">${esc(id)}</span>`;};

  async function api(path, data) {
    let response;
    try {
      response = await fetch(`/api/${path}`, {method:data === undefined ? 'GET' : 'POST', credentials:'same-origin',cache:'no-store',
        headers: data === undefined ? {} : {'Content-Type':'application/json','X-CSRF-Token':state.csrf},
        body:data === undefined ? undefined : JSON.stringify(data), signal:AbortSignal.timeout(12000)});
    } catch (_) { const e = new Error('Keine Verbindung zum Pool. Starte den lokalen Server oder prüfe deine Verbindung.'); e.network = true; throw e; }
    const body = await response.json();
    if (!response.ok) { const e = new Error(body.error || 'Das hat nicht funktioniert. Bitte erneut versuchen.'); e.status=response.status; e.code=body.code; throw e; }
    return body;
  }
  function receive(data) { state.data=data; state.serverNow=data.now; state.syncAt=performance.now(); state.online=true; if (state.week === null) state.week=data.current_week; }
  function toast(message, error = false) {
    const el=$('#toast'); el.innerHTML=`${icon(error?'info':'check')}<span>${esc(message)}</span>`; el.className=`toast show ${error?'error':''}`;
    clearTimeout(toast.timer); toast.timer=setTimeout(()=>el.classList.remove('show'),4500);
  }
  function formError(form, message) {
    const el=$('.form-error',form); el.textContent=message; el.hidden=false;
    form.classList.remove('shake'); void form.offsetWidth; form.classList.add('shake');
  }
  function closeModal(){ modal.close(); modal.innerHTML=''; }
  function showModal(content) {modal.innerHTML=content; if(!modal.open) modal.showModal();}
  function dialogHeader(title, eyebrow = '') {return `<div class="dialog-head"><div>${eyebrow?`<p class="eyebrow">${eyebrow}</p>`:''}<h2 id="modal-title">${title}</h2></div><button type="button" class="icon-button" data-action="close-modal" aria-label="Schließen">${icon('close')}</button></div>`;}
  function passwordField(id, label, autocomplete='current-password', minimum=1) {return `<label for="${id}">${label}</label><div class="password-wrap"><input id="${id}" name="${id}" type="password" required minlength="${minimum}" maxlength="128" autocomplete="${autocomplete}" placeholder="${minimum>1?'Mindestens 10 Zeichen':'Passwort eingeben'}"><button type="button" class="icon-button" data-action="toggle-password" data-target="${id}" aria-label="Passwort anzeigen">${icon('eye')}</button></div>`;}

  function renderGate(error='') {
    state.data=null;
    app.innerHTML=`<main id="main" class="auth-shell"><div class="auth-top"><a href="#" class="brand" aria-label="Survivor Pool">${brand()}</a><span class="private-label">${icon('lock')} PRIVATER POOL</span></div>
      <section class="auth-stage"><div class="auth-story"><p class="eyebrow">NFL · REGULAR SEASON & PLAYOFFS</p><h1>EIN TEAM.<br>EIN TIPP.<br><span>STAY ALIVE.</span></h1><p class="auth-description">Dein Spieltag. Deine Entscheidung.<br>Wer bleibt bis zum Super Bowl im Rennen?</p><div class="auth-rules"><span><b>01</b> Team pro Week</span><span><b>32</b> Teams zur Auswahl</span><span><b>01</b> Weg zum Titel</span></div></div>
      <section class="auth-card"><div class="gate-icon">${icon('shield')}</div><p class="eyebrow">NUR FÜR UNSERE RUNDE</p><h2>Willkommen im Pool.</h2><p>Gib das gemeinsame Pool-Passwort ein.<br>Danach meldest du dich mit deinem Account an.</p><form id="gate-form">${passwordField('password','Pool-Passwort')}<p class="form-error" role="alert" ${error?'':'hidden'}>${esc(error)}</p><button class="button primary wide" type="submit">${icon('lock')} Pool öffnen</button></form><div class="auth-foot">${icon('shield')} Dein privater Spieltag beginnt hier.</div></section></section><footer class="auth-footer"><span>SURVIVOR POOL</span><span>Ein privates Fanprojekt. Nicht mit der NFL verbunden.</span></footer></main>`;
  }
  function renderAuth() {
    const register=state.authTab==='register';
    app.innerHTML=`<main id="main" class="account-shell"><a href="#" class="brand">${brand()}</a><section class="auth-card"><p class="eyebrow">${icon('check')} POOL FREIGESCHALTET</p><h1>${register?'Dein Platz im Pool.':'Schön, dass du da bist.'}</h1><p>${register?'Ein eigener Account für deine Entscheidungen.':'Melde dich an und mach deinen nächsten Tipp.'}</p><div class="segmented"><button data-action="auth-tab" data-tab="login" class="${!register?'active':''}">Einloggen</button><button data-action="auth-tab" data-tab="register" class="${register?'active':''}">Account erstellen</button></div>
      <form id="account-form" data-mode="${register?'register':'login'}"><label for="username">Benutzername</label><input id="username" name="username" required minlength="3" maxlength="24" pattern="[A-Za-z0-9_]{3,24}" autocomplete="username" autocapitalize="none" spellcheck="false" placeholder="z. B. max">${register?'<label for="display_name">Anzeigename</label><input id="display_name" name="display_name" required maxlength="40" autocomplete="nickname" placeholder="So sieht dich dein Pool">':''}${passwordField('password','Persönliches Passwort',register?'new-password':'current-password',register?10:1)}${register?passwordField('confirmation','Passwort bestätigen','new-password',10):''}<p class="form-error" role="alert" hidden></p><button class="button primary wide" type="submit">${register?'Account erstellen':'Einloggen'}</button></form>
      ${state.demo?`<div class="demo-login"><span class="eyebrow">DEMO-ACCOUNTS</span><p>Direkt ausprobieren. Max kann Spiele simulieren.</p><div class="demo-users">${['max','lea','tim','nina','finn','ben'].map(n=>`<button data-action="demo-login" data-user="${n}">${esc(n[0].toUpperCase()+n.slice(1))}</button>`).join('')}</div><small>Passwort für alle: <code>Survivor2026!</code></small></div>`:''}<button class="text-button back-pool" data-action="logout">Pool wieder schließen</button></section><span class="muted small">Ein Account. Deine ganze Saison.</span></main>`;
  }
  const navigation = [['dashboard','Dashboard'],['games','Spieltag'],['season','Saison'],['leaderboard','Leaderboard'],['profile','Mein Profil']];
  function render() {
    if(!state.data) return;
    const d=state.data, me=d.me;
    document.title=`${navigation.find(n=>n[0]===state.route)?.[1] || 'Dashboard'} · Survivor Pool`;
    app.innerHTML=`<div class="app-shell"><aside class="sidebar"><a class="brand" href="#dashboard">${brand()}</a><div class="pool-label"><span class="tiny-ball">${icon('ball')}</span><span>Unser NFL Pool<small>SAISON ${d.season}</small></span></div><nav aria-label="Hauptnavigation">${navigation.map(([key,title])=>`<a href="#${key}" class="nav-link ${state.route===key?'active':''}" ${state.route===key?'aria-current="page"':''}>${icon(key)}<span>${title}</span>${key==='games'?`<span class="nav-count">${d.current_week}</span>`:''}</a>`).join('')}</nav><div class="sidebar-bottom"><button class="rules-link" data-action="rules">${icon('info')} So funktioniert’s</button><div class="sidebar-season"><span>DER WEG ZUM SUPER BOWL</span><div class="season-progress"><i style="width:${Math.round(d.current_week/22*100)}%"></i></div><div><b>${esc(weekLabel(d.current_week))}</b><span>22 Spieltage</span></div></div><button class="sidebar-user" data-action="profile">${avatar(me.display_name)}<span><b>${esc(me.display_name)}</b><small>@${esc(me.username)}</small></span>${icon('chevron')}</button><button class="logout-button" data-action="logout">${icon('logout')} Abmelden</button></div></aside>
      <div class="workspace"><header class="topbar"><div class="breadcrumb"><span>Unser NFL Pool</span><span>/</span><b>${navigation.find(n=>n[0]===state.route)?.[1]}</b></div><a class="mobile-brand brand" href="#dashboard">${brand()}</a><div class="header-actions">${d.demo?badge('DEMO-DATEN','demo'):''}<button class="button subtle install-button" data-action="install" aria-label="Survivor Pool installieren">${icon('download')}<span>${state.installed?'App installiert':'App installieren'}</span></button><a class="header-avatar" href="#profile" aria-label="Mein Profil">${avatar(me.display_name)}</a></div></header><main id="main" class="content"><div id="connection-banner">${connectionBanner()}</div><div class="page-content">${({dashboard:dashboard, games:gamesPage, season:seasonPage,leaderboard:leaderboardPage,profile:profilePage}[state.route]||dashboard)()}</div><footer class="page-footer"><span>${d.demo?'Fiktive Spiele & Ergebnisse · Keine Live-NFL-Daten':'Spielzeiten in deiner Zeitzone'}</span><span>${esc(zone())}</span></footer></main></div><nav class="bottom-nav" aria-label="Mobile Navigation">${navigation.map(([key,title])=>`<a href="#${key}" class="${state.route===key?'active':''}" aria-label="${title}" ${state.route===key?'aria-current="page"':''}>${icon(key)}<span>${key==='leaderboard'?'Ranking':key==='profile'?'Profil':title}</span></a>`).join('')}</nav></div>`;
    updateCountdowns();
  }
  function connectionBanner() {
    const msg=!state.online?'Verbindung unterbrochen. Du siehst den zuletzt geladenen Stand. Tipps sind bis zur Verbindung gesperrt.':state.data?.source_error;
    return msg?`<div class="notice warning">${icon('info')}<span>${esc(msg)}</span><button class="text-button" data-action="refresh">Erneut laden</button></div>`:'';
  }
  function pageHeading(eyebrow,title,description='',extra='') {return `<div class="page-heading"><div><p class="eyebrow">${eyebrow}</p><h1>${title}</h1>${description?`<p class="muted">${description}</p>`:''}</div>${extra}</div>`;}
  function statsCards() {
    const s=state.data.me.stats;
    return `<div class="stats-grid">${[['Richtige Tipps',s.wins,'check','good','GEWONNEN'],['Falsche Tipps',s.losses,'close','bad','VERLOREN'],['Abgegebene Tipps',s.total,'ball','','DEINE SAISON'],['Erfolgsquote',`${s.rate}<small>%</small>`,'bolt','lime',`${s.wins+s.losses} AUSGEWERTET`]].map(([label,value,ic,tone,small])=>`<article class="stat-card"><div><span>${label}</span>${icon(ic,tone)}</div><strong>${value}</strong><small>${small}</small></article>`).join('')}</div>`;
  }
  function pickHero() {
    const d=state.data,pick=currentPick(), game=pick?gameById(pick.game_id):null, isLocked=locked(pick), t=pick?teams()[pick.team]:null;
    const upcoming=d.games.filter(g=>g.week===d.current_week&&g.status==='scheduled'&&!isStarted(g)).sort((a,b)=>a.kickoff-b.kickoff);
    const target=game?.kickoff || upcoming[0]?.kickoff;
    return `<section class="pick-hero ${pick?'has-pick':''} ${pick?.result==='win'?'won':''}"><div class="hero-week"><span>${d.current_week<=18?'REGULAR SEASON':'PLAYOFFS'}</span><strong>${d.current_week<=18?'WEEK':esc(weekLabel(d.current_week)).toUpperCase()}</strong><b>${String(d.current_week).padStart(2,'0')}</b><span class="week-bottom">SAISON ${d.season}</span></div><div class="hero-main"><div class="hero-top"><span class="eyebrow">DEIN SURVIVOR-TIPP</span>${badge(isLocked?`${icon('lock')} Tipp gesperrt`:pick?'Tipp bestätigt':'Noch kein Tipp',isLocked?'neutral':pick?'good':'lime')}</div>${pick?`<div class="picked-team">${teamBadge(pick.team,'large')}<div><small>${esc(t.city)}</small><h2>${esc(t.name)}</h2><p>gegen ${esc(teams()[pick.opponent].full_name)}</p></div></div>`:`<h2>Wem vertraust du<br>diese Woche?</h2><p class="hero-sub">Ein Team auswählen. Bestätigen. Mitfiebern.</p>`}<div class="hero-bottom"><div>${pick&&pick.result!=='pending'?`<strong class="result-${pick.result}">${resultText(pick.result)}</strong><small>${game.away_score} : ${game.home_score} · ${esc(teams()[game.away].name)} / ${esc(teams()[game.home].name)}</small>`:target?`<span class="countdown-label">${icon('clock')} ${pick?(isLocked?'Gesperrt seit':'Änderbar bis Kickoff'):'Nächster Kickoff'}</span><strong ${!isLocked?`data-countdown="${target}"`:''}>${isLocked?date(target):'–'}</strong><small>${date(target)} · ${esc(zone())}</small>`:'<strong>Alle Spiele haben begonnen.</strong>'}</div><button class="button ${pick?'outline':'dark'}" data-action="go-games">${isLocked?'Spiele ansehen':pick?'Tipp ändern':'Team auswählen'}${icon(isLocked?'games':'ball')}</button></div></div></section>`;
  }
  function dashboard() {
    const d=state.data,s=d.me.stats;
    return `${pageHeading(`SAISON ${d.season} <span class="slash">/</span> ${esc(weekLabel(d.current_week)).toUpperCase()}`,`Dein Spieltag, ${esc(d.me.display_name)}.`, 'Ein guter Pick kann alles verändern.',`<div class="survivor-chip ${s.survivor?'alive':'out'}">${icon('shield')}<span>Survivor-Status<b>${s.survivor?'Noch im Rennen':'Ausgeschieden'}</b></span></div>`)}${pickHero()}${statsCards()}<div class="dashboard-columns"><section><div class="section-heading"><h2>Diese Woche auf dem Feld <span class="number-badge">${d.games.filter(g=>g.week===d.current_week).length}</span></h2><a href="#games">Alle Spiele ${icon('chevron')}</a></div>${legend()}<div class="games-grid compact">${d.games.filter(g=>g.week===d.current_week).slice(0,6).map(gameCard).join('')||emptyState('Noch keine Begegnungen','Sobald Spieldaten vorliegen, kannst du hier tippen.')}</div></section><aside class="dashboard-aside"><section class="panel ranking-panel"><div class="section-heading"><h2>Der Pool im Blick</h2>${icon('leaderboard')}</div><div class="mini-ranking">${d.players.slice(0,5).map((u,i)=>`<div class="mini-player ${u.id===d.me.id?'is-me':''}"><span class="rank">${String(i+1).padStart(2,'0')}</span>${avatar(u.display_name)}<span><b>${esc(u.display_name)} ${u.id===d.me.id?'<small>DU</small>':''}</b><small>${u.stats.survivor?'Im Rennen':'Ausgeschieden'}</small></span><strong>${u.stats.wins}<small>Siege</small></strong></div>`).join('')}</div><a class="panel-link" href="#leaderboard">Zur Bestenliste ${icon('chevron')}</a></section><section class="panel recent-panel"><div class="section-heading"><h2>Deine letzten Picks</h2></div>${ownPicks().slice().reverse().slice(0,4).map(p=>`<div class="recent-pick"><span class="week-small">${p.week<=18?'W'+p.week:esc(weekLabel(p.week))}</span>${teamBadge(p.team,'tiny')}<b>${esc(teams()[p.team].name)}</b><span class="result-icon result-${p.result}" title="${resultText(p.result)}">${p.result==='win'?'✓':p.result==='loss'?'✕':'–'}</span></div>`).join('')||'<p class="muted">Deine Saison beginnt mit dem ersten Tipp.</p>'}<a class="panel-link" href="#profile">Meine Saison ${icon('chevron')}</a></section><div class="rule-note">${icon('info')}<p>Jedes Team nur einmal.<br>Maximal dreimal gegen dasselbe Team.</p></div></aside></div>`;
  }
  function usage(excludedWeek) {const used={},against={}; for(const p of ownPicks()){if(p.week===excludedWeek)continue; used[p.team]=p.week;against[p.opponent]=(against[p.opponent]||0)+1;}return{used,against};}
  function eligibility(game,team) {
    const d=state.data,pick=ownPicks().find(p=>p.week===game.week), rival=team===game.home?game.away:game.home;
    const u=usage(game.week),reasons=[];
    if(u.used[team])reasons.push('Du hast dieses Team bereits verwendet.');
    if((u.against[rival]||0)>=3)reasons.push('Du hast bereits dreimal gegen dieses Team gesetzt.');
    if(locked(pick))reasons.push('Dein Tipp ist seit dem Kickoff gesperrt.');
    if(isStarted(game))reasons.push('Dieses Spiel hat bereits begonnen.');
    if(!['scheduled','live','final'].includes(game.status))reasons.push('Dieses Spiel ist aktuell nicht verfügbar.');
    if(game.week!==d.current_week)reasons.push('Tipps sind nur für den aktuellen Spieltag möglich.');
    if(!d.rules.allow_after_elimination&&!d.me.stats.survivor)reasons.push('Du bist ausgeschieden. Weitere Tipps sind deaktiviert.');
    if(!state.online)reasons.push('Zum Tippen benötigst du eine Verbindung zum Pool.');
    return{reasons,used:u.used[team],againstMax:(u.against[team]||0)>=3,blockedOpponent:(u.against[rival]||0)>=3,selected:pick?.team===team&&pick?.game_id===game.id};
  }
  function teamCard(game,id,home) {
    const t=teams()[id], e=eligibility(game,id), pick=ownPicks().find(p=>p.week===game.week);
    const tone=e.used?'used':e.selected?'selected':e.blockedOpponent?'opponent-blocked':'';
    let status=e.selected?'Dein Tipp':e.used?'Bereits verwendet':e.blockedOpponent?'Gegner-Limit erreicht':isStarted(game)?'Nicht mehr wählbar':game.week>state.data.current_week?'Noch nicht geöffnet':locked(pick)?'Tipp gesperrt':e.reasons.length?'Nicht wählbar':'Verfügbar';
    if(e.selected&&pick?.result!=='pending')status=resultText(pick.result);
    return `<button class="team-choice ${tone} ${e.againstMax?'against-cap':''} ${e.reasons.length?'unavailable':''}" data-action="pick" data-game="${esc(game.id)}" data-team="${esc(id)}" aria-label="${esc(t.full_name)} wählen. ${esc(e.reasons.join(' ')||status)}" aria-pressed="${e.selected}" ${e.reasons.length?'aria-disabled="true"':''}><span class="team-side">${home?'HEIM':'AUSWÄRTS'}${e.selected?icon('check'):''}</span>${teamBadge(id)}<span class="team-city">${esc(t.city)}</span><strong>${esc(t.name)}</strong><span class="team-availability ${e.used?'bad':e.selected?'lime':e.blockedOpponent?'orange':e.reasons.length?'':'good'}">${e.selected?icon(locked(pick)?'lock':'check'):e.used?icon('close'):e.blockedOpponent?icon('info'):e.reasons.length?icon('lock'):'<i></i>'}${esc(status)}</span>${e.againstMax?'<span class="against-label">3× dagegen · Gegner gesperrt</span>':''}</button>`;
  }
  function gameCard(game) {
    const status={scheduled:isStarted(game)?'Gestartet':'Anstehend',live:'Live',final:'Beendet',postponed:'Verschoben',cancelled:'Abgesagt'}[game.status];
    return `<article class="game-card"><div class="game-card-head"><span>${icon('clock')} ${date(game.kickoff)}</span><span class="match-status ${game.status==='live'?'live':''}">${status}</span></div><div class="matchup">${teamCard(game,game.away,false)}<span class="versus">${game.away_score!==null&&game.home_score!==null?`<b>${game.away_score}</b><small>:</small><b>${game.home_score}</b>`:'VS'}</span>${teamCard(game,game.home,true)}</div>${game.status==='final'?`<div class="game-final">Endstand · ${game.away_score} : ${game.home_score}</div>`:''}</article>`;
  }
  function legend() {return '<div class="legend"><span><i class="dot green"></i>Verfügbar</span><span><i class="dot red"></i>Schon verwendet</span><span><i class="dot orange"></i>3× dagegen</span><button data-action="rules" aria-label="Farben und Regeln erklären">'+icon('info')+'</button></div>';}
  function weekControl() {return `<div class="week-control"><button class="icon-button" data-action="prev-week" aria-label="Vorheriger Spieltag" ${state.week===1?'disabled':''}>${icon('chevron','rotate')}</button><select id="week-select" aria-label="Spieltag auswählen">${state.data.weeks.map(w=>`<option value="${w.number}" ${state.week===w.number?'selected':''}>${esc(w.name)}${w.number===state.data.current_week?' · Aktuell':''}</option>`).join('')}</select><button class="icon-button" data-action="next-week-view" aria-label="Nächster Spieltag" ${state.week===22?'disabled':''}>${icon('chevron')}</button></div>`;}
  function gamesPage() {
    const games=state.data.games.filter(g=>g.week===state.week), visible=games.filter(g=>state.filter==='all'||(state.filter==='open'&&g.status==='scheduled'&&!isStarted(g))||(state.filter==='final'&&g.status==='final'));
    return `${pageHeading(state.week<=18?'REGULAR SEASON':'ROAD TO THE SUPER BOWL',esc(weekLabel(state.week)),`${games.length} Begegnungen · Ein Survivor-Tipp.`,weekControl())}${state.week===state.data.current_week?`<div class="pick-strip">${icon('ball')}<span>${currentPick()?`Dein Tipp: <b>${esc(teams()[currentPick().team].full_name)}</b> · ${locked(currentPick())?'Gesperrt':`Änderbar bis ${date(gameById(currentPick().game_id).kickoff)}`}`:'Dein Tipp ist noch offen. Wähle ein Team für diesen Spieltag.'}</span>${currentPick()?badge(resultText(currentPick().result),currentPick().result==='win'?'good':''):''}</div>`:`<div class="notice">${icon('info')}<span>${state.week>state.data.current_week?'Vorschau: Dieser Spieltag ist noch nicht für Tipps geöffnet.':'Dieser Spieltag ist abgeschlossen. Deine bisherigen Tipps bleiben sichtbar.'}</span></div>`}<div class="games-toolbar">${legend()}<div class="segmented filter">${[['all','Alle'],['open','Anstehend'],['final','Beendet']].map(([id,label])=>`<button data-action="filter" data-filter="${id}" class="${state.filter===id?'active':''}">${label}</button>`).join('')}</div></div><div class="games-grid full">${visible.map(gameCard).join('')||emptyState('Keine Spiele in dieser Ansicht','Wähle einen anderen Filter oder Spieltag.')}</div>`;
  }
  function emptyState(title,text){return `<div class="empty-state">${icon('games')}<h2>${title}</h2><p>${text}</p></div>`;}
  function seasonPage() {
    const d=state.data;
    return `${pageHeading(`DIE GESAMTE RUNDE · SAISON ${d.season}`,'Jede Week zählt.','Alle Tipps. Die ganze Saison. Bis zum Super Bowl.',badge(`${d.players.length} Spieler`))}<div class="table-legend"><span class="good">✓ Richtig</span><span class="bad">✕ Falsch</span><span>◷ Noch offen</span><span>– Kein sichtbarer Tipp</span></div><div class="panel season-panel"><div class="table-scroll" tabindex="0" role="region" aria-label="Saisontabelle, horizontal scrollbar"><table class="season-table"><thead><tr><th class="sticky-col">Spieler</th>${d.weeks.map(w=>`<th class="${w.number===d.current_week?'current-week':''}">${w.number<=18?'WEEK '+w.number:esc(w.name)}</th>`).join('')}<th>Siege</th></tr></thead><tbody>${d.players.map(u=>`<tr class="${u.id===d.me.id?'my-row':''}"><th class="sticky-col">${avatar(u.display_name)}<span>${esc(u.display_name)}${u.id===d.me.id?'<small>DU</small>':''}</span></th>${d.weeks.map(w=>{const p=d.picks.find(p=>p.user_id===u.id&&p.week===w.number);return `<td class="${w.number===d.current_week?'current-week':''}">${p?`<span class="table-pick result-${p.result}" title="${esc(teams()[p.team].full_name)} · ${resultText(p.result)}">${esc(p.team)} <b>${p.result==='win'?'✓':p.result==='loss'?'✕':p.result==='push'?'=':'◷'}</b></span>`:u.stats.missed.includes(w.number)?'<span class="missed-cell" title="Spieltag ohne Tipp verpasst">–</span>':'<span class="dash">–</span>'}</td>`;}).join('')}<td><b class="lime">${u.stats.wins}</b></td></tr>`).join('')}</tbody></table></div></div><p class="table-hint">${icon('info')} Tipps anderer Spieler werden mit ihrem Kickoff sichtbar. Wische horizontal für weitere Weeks.</p><div class="season-milestones"><div><span>01—18</span><b>Regular Season</b></div><div><span>19—21</span><b>Playoffs</b></div><div><span>22</span><b>Super Bowl</b></div></div>`;
  }
  function leaderboardPage() {
    const d=state.data;
    return `${pageHeading(`SAISON ${d.season} · ${d.players.length} SPIELER`,'Die Bestenliste.','Sortierung: richtige Tipps, dann Anzeigename (A–Z).',`<div class="alive-count">${icon('shield')} <b>${d.players.filter(u=>u.stats.survivor).length}</b> noch im Rennen</div>`)}<section class="panel leaderboard-panel"><div class="leaderboard-header"><span>Rang / Spieler</span><span>Richtige</span><span>Falsche</span><span>Tipps</span><span>Status</span></div>${d.players.map((u,i)=>`<div class="leaderboard-row ${u.id===d.me.id?'is-me':''}"><div class="leader-player"><span class="big-rank ${i===0?'first':''}">${String(i+1).padStart(2,'0')}</span>${avatar(u.display_name)}<span><b>${esc(u.display_name)}${u.id===d.me.id?'<small>DU</small>':''}</b><small>@${esc(u.username)}</small></span></div><strong class="good"><small>Richtige</small>${u.stats.wins}</strong><strong class="${u.stats.losses?'bad':''}"><small>Falsche</small>${u.stats.losses}</strong><strong><small>Tipps</small>${u.stats.total}</strong><span class="rank-status">${badge(u.stats.survivor?'Im Rennen':'Ausgeschieden',u.stats.survivor?'good':'neutral')}</span></div>`).join('')}</section><p class="table-hint">${icon('info')} ${d.rules.allow_after_elimination?'Auch nach dem Ausscheiden zählen weitere richtige Tipps für die Bestenliste.':'Nach dem Ausscheiden sind keine weiteren Tipps möglich.'} Ein neutraler Tie zählt nicht als Sieg.</p>`;
  }
  function profilePage() {
    const d=state.data,u=usage(),s=d.me.stats, sorted=ownPicks().slice().reverse();
    return `${pageHeading(`@${esc(d.me.username)} · SAISON ${d.season}`,'Meine Saison.',`${s.survivor?'Du bist noch im Rennen.':s.missed.length?'Ausgeschieden: ein Spieltag wurde verpasst.':'Ausgeschieden: mindestens ein falscher Tipp.'} ${d.rules.allow_after_elimination&&!s.survivor?'Du kannst für die Bestenliste weiter tippen.':''}`,avatar(d.me.display_name,'large'))}${statsCards()}<div class="profile-grid"><section class="panel"><div class="section-heading"><h2>Deine Team-Bilanz</h2><span class="muted small">${Object.keys(u.used).length} / 32 verwendet</span></div>${legend()}<div class="team-inventory">${d.teams.map(t=>`<button class="inventory-team ${u.used[t.id]?'used':''} ${(u.against[t.id]||0)>=3?'against-max':''}" data-action="team-info" data-team="${esc(t.id)}" aria-label="${esc(t.full_name)}, ${u.used[t.id]?'verwendet in '+weekLabel(u.used[t.id]):'noch nicht verwendet'}, ${u.against[t.id]||0} mal dagegen">${teamBadge(t.id,'tiny')}<b>${esc(t.id)}</b><span>${u.used[t.id]?'Verwendet':'Noch frei'}</span><small>${u.against[t.id]||0}× dagegen</small></button>`).join('')}</div></section><section class="panel history-panel"><div class="section-heading"><h2>Tipp-Historie</h2><span class="number-badge">${s.total}</span></div>${sorted.map(p=>`<div class="history-pick"><div>${teamBadge(p.team,'tiny')}<span><b>${esc(teams()[p.team].full_name)}</b><small>${esc(weekLabel(p.week))} · gegen ${esc(p.opponent)}</small></span></div>${badge(resultText(p.result),p.result==='win'?'good':p.result==='loss'?'bad':'neutral')}<small>${date(gameById(p.game_id).kickoff)}</small></div>`).join('')||emptyState('Noch kein Tipp','Deine Tipp-Historie beginnt auf dem Spieltag.')}<div class="rule-note">${icon('info')}<p>${d.rules.tie_is_loss?'Ein Unentschieden zählt als falscher Tipp.':'Ein Unentschieden bleibt neutral. Das Team gilt trotzdem als verwendet.'}</p></div></section></div>${d.me.role==='admin'?adminPanel():''}<div class="profile-account-actions"><button class="button outline" data-action="logout">${icon('logout')} Abmelden</button><span class="muted small">Angemeldet als @${esc(d.me.username)}</span></div>`;
  }
  function adminPanel() {
    const d=state.data;
    return `<section class="panel admin-panel"><div class="section-heading"><div><p class="eyebrow">ADMINISTRATION${d.demo?' · DEMO':''}</p><h2>Deine Pool-Regeln</h2></div>${icon('shield')}</div><form id="settings-form"><label class="check-label"><input type="checkbox" name="tie_is_loss" ${d.rules.tie_is_loss?'checked':''}><span><b>Unentschieden zählt als falsch</b><small>Ohne Haken: neutral, kein Sieg; Teamverbrauch bleibt bestehen.</small></span></label><label class="check-label"><input type="checkbox" name="allow_after_elimination" ${d.rules.allow_after_elimination?'checked':''}><span><b>Nach dem Ausscheiden weitertippen</b><small>Weitere Tipps zählen für die Bestenliste.</small></span></label><label class="check-label"><input type="checkbox" name="missing_pick_eliminates" ${d.rules.missing_pick_eliminates?'checked':''}><span><b>Verpasster Spieltag führt zum Ausscheiden</b><small>Sobald alle nicht abgesagten Spiele begonnen haben. Erst ab Beitritt.</small></span></label><p class="form-error" role="alert" hidden></p><button class="button outline" type="submit">Regeln speichern</button><small class="muted settings-note">Änderungen gelten für den gesamten Pool und werten bestehende Tipps neu aus.</small></form>${d.demo?`<div class="demo-controls"><div><h3>Spielverlauf ausprobieren</h3><p>Die Simulation gilt für alle Demo-Accounts. Ergebnisse können erneut gesetzt werden.</p></div><button class="button primary" data-action="demo-panel">${icon('bolt')} Demo steuern</button></div>`:''}</section>`;
  }

  function showRules() {
    const d=state.data;
    showModal(`${dialogHeader('So bleibst du im Rennen.','DIE SPIELREGELN')}<div class="rules-list"><div><b>01</b><span><h3>Ein Team pro Spieltag.</h3><p>Dein Tipp gilt für die gesamte Week. Du kannst ihn bis zum Kickoff deines gewählten Spiels ändern.</p></span></div><div><b>02</b><span><h3>Jedes Team nur einmal.</h3><p>Von Week 1 bis zum Super Bowl. Rot markierte Teams hast du bereits verwendet.</p></span></div><div><b>03</b><span><h3>Dreimal dagegen. Dann ist Schluss.</h3><p>Orange markiert ein Team, gegen das du schon dreimal getippt hast. Du darfst dann seinen Gegner nicht wählen. Das orange Team selbst bleibt wählbar, sofern keine andere Regel greift.</p></span></div><div><b>04</b><span><h3>Kickoff ist die Grenze.</h3><p>Auch ein Wechsel auf ein späteres Spiel ist dann gesperrt. Grün bedeutet: aktuell wählbar. Weitere Sperrgründe werden direkt an der Auswahl erklärt.</p></span></div></div><div class="notice"><span>${d?.rules.tie_is_loss?'Ein Tie zählt als falsch.':'Ein Tie bleibt neutral und zählt nicht als Sieg.'} ${d?.rules.allow_after_elimination?'Nach dem Ausscheiden ist Weitertippen für die Bestenliste erlaubt.':''} ${d?.rules.missing_pick_eliminates?'Wer bis zum letzten Kickoff keinen Tipp hat, scheidet aus.':''}</span></div><button class="button primary wide" data-action="close-modal">Verstanden</button>`);
  }
  function stagePick(gid,team) {
    const g=gameById(gid); if(!g||!teams()[team])return;
    const e=eligibility(g,team),t=teams()[team];
    if(e.reasons.length){showModal(`${dialogHeader('Dieses Team ist gesperrt.')}<div class="blocked-team">${teamBadge(team,'large')}<h3>${esc(t.full_name)}</h3></div><ul class="reason-list">${e.reasons.map(r=>`<li>${icon('info')} ${esc(r)}</li>`).join('')}</ul><button class="button primary wide" data-action="close-modal">Verstanden</button>`);return;}
    if(e.selected){toast('Das ist bereits dein bestätigter Tipp.');return;}
    showModal(`${dialogHeader('Deine Entscheidung.','SURVIVOR PICK · '+esc(weekLabel(g.week)).toUpperCase())}<div class="confirm-team">${teamBadge(team,'large')}<h3>${esc(t.full_name)}</h3><p>gegen ${esc(teams()[team===g.home?g.away:g.home].full_name)}</p></div><p class="confirmation-question">Möchtest du wirklich auf die ${esc(t.full_name)} setzen?</p><div class="notice">${icon('clock')}<span>Änderbar bis <b>${date(g.kickoff)}</b>.<br>${currentPick()?'Dein bisheriger Tipp wird dadurch ersetzt.':'Danach wird dein Tipp automatisch gesperrt.'}</span></div><p class="modal-error form-error" role="alert" hidden></p><div class="dialog-actions"><button class="button outline" data-action="close-modal">Abbrechen</button><button class="button primary" data-action="confirm-pick" data-game="${esc(gid)}" data-team="${esc(team)}">${icon('check')} Tipp bestätigen</button></div>`);
  }
  async function confirmPick(button) {
    if(state.busy)return; state.busy=true;button.disabled=true;
    try {receive(await api('pick',{game_id:button.dataset.game,team:button.dataset.team}));closeModal();render();toast('Dein Tipp ist bestätigt. Viel Glück!');$('.pick-hero')?.classList.add('celebrate');}
    catch(e){const el=$('.modal-error');if(el){el.hidden=false;el.textContent=e.message;}else toast(e.message,true);if(e.network){state.online=false;$('#connection-banner').innerHTML=connectionBanner();}}
    finally{state.busy=false;button.disabled=false;}
  }
  function showTeamInfo(id) {
    const t=teams()[id],u=usage();
    showModal(`${dialogHeader(esc(t.full_name),'DEINE TEAM-BILANZ')}<div class="confirm-team">${teamBadge(id,'large')}</div><div class="team-info-row"><span>Als Sieger gewählt</span>${badge(u.used[id]?esc(weekLabel(u.used[id])):'Noch nicht',u.used[id]?'bad':'good')}</div><div class="team-info-row"><span>Gegen dieses Team gesetzt</span>${badge(`${u.against[id]||0} / 3`,(u.against[id]||0)>=3?'orange':'neutral')}</div><p class="muted">${(u.against[id]||0)>=3?'Du kannst keinen weiteren Gegner dieses Teams wählen.':''} ${u.used[id]?'Dieses Team steht für die restliche Saison nicht mehr zur Verfügung.':'Ob du dieses Team aktuell wählen kannst, siehst du beim jeweiligen Spiel.'}</p><button class="button primary wide" data-action="close-modal">Schließen</button>`);
  }
  function demoPanel() {
    const d=state.data,fixtures=d.games.filter(g=>g.week===d.current_week),pick=currentPick();
    showModal(`${dialogHeader('Kickoff. Ergebnis. Nächste Week.','DEMO-STEUERUNG')}<p class="muted">Teste die Regeln mit fiktiven Spielen. Alle Demo-Spieler sehen die Änderung.</p><form id="demo-form"><label for="demo-game">Begegnung</label><select id="demo-game" name="game_id">${fixtures.map(g=>`<option value="${esc(g.id)}" ${g.id===pick?.game_id?'selected':''}>${esc(g.away)} @ ${esc(g.home)} · ${g.status==='final'?'Beendet':g.status==='live'?'Live':'Anstehend'}</option>`).join('')}</select><label for="winner">Ergebnis simulieren</label><select id="winner" name="winner"><option value="away">Auswärtsteam gewinnt · 27 : 20</option><option value="home">Heimteam gewinnt · 20 : 27</option><option value="tie">Unentschieden · 24 : 24</option></select><p class="form-error" role="alert" hidden></p><div class="dialog-actions"><button type="submit" name="action" value="kickoff" class="button outline">${icon('clock')} Kickoff simulieren</button><button type="submit" name="action" value="finish" class="button primary">Spiel beenden</button></div></form><div class="demo-next"><p>„Nächste Week“ beendet offene Spiele mit 24 : 17 für das Auswärtsteam und öffnet den nächsten Spieltag.</p><button class="button subtle" data-action="advance-week" ${d.current_week===22?'disabled':''}>Nächste Week öffnen</button></div>`);
  }
  async function installApp() {
    if(state.installed){toast('Survivor Pool ist bereits als App geöffnet.');return;}
    if(state.prompt){await state.prompt.prompt();await state.prompt.userChoice;state.prompt=null;return;}
    showModal(`${dialogHeader('Survivor Pool installieren.')}<div class="install-emblem">${brand()}</div><p>Öffne den Pool im Browser und füge ihn deinem Startbildschirm hinzu.</p><div class="install-steps"><h3>iPhone & iPad</h3><p>In Safari: Teilen → „Zum Home-Bildschirm“ → „Hinzufügen“.</p><h3>Android & Desktop</h3><p>Im Browser-Menü „App installieren“ wählen. Sobald dein Browser die Installation anbietet, öffnet dieser Button den Installationsdialog.</p></div><div class="notice">${icon('info')}<span>Installation funktioniert auf <b>localhost</b> oder einer <b>HTTPS-Adresse</b>. Bei einfachem HTTP über die Netzwerk-IP ist sie nicht verfügbar.</span></div><button class="button primary wide" data-action="close-modal">Verstanden</button>`);
  }
  async function refresh(quiet=false) {
    if(!state.data||state.busy)return;
    const epoch=state.epoch;
    try {
      const before=currentPick()?.result,data=await api('state'), current=data.picks.find(p=>p.user_id===data.me.id&&p.week===data.current_week);
      if(epoch!==state.epoch||!state.data||data.me.id!==state.data.me.id||data.now<state.serverNow)return;
      const previousWeek=state.data.current_week;
      receive(data);if(state.week===previousWeek)state.week=data.current_week;
      if(!modal.open&&!$('form:focus-within'))render();else if($('#connection-banner'))$('#connection-banner').innerHTML=connectionBanner();
      if(before==='pending'&&current?.result==='win'){toast('Dein Team hat gewonnen. Richtig getippt!');$('.pick-hero')?.classList.add('celebrate');}
      if(before==='pending'&&current?.result==='loss')toast('Dein Tipp wurde als falsch ausgewertet.',true);
      if(!quiet)toast('Dein Pool ist aktuell.');
    }catch(e){if(epoch!==state.epoch)return;if(e.status===401){state.data=null;closeModal();renderGate('Deine Sitzung ist abgelaufen. Bitte melde dich erneut an.');}else{state.online=false;if($('#connection-banner'))$('#connection-banner').innerHTML=connectionBanner();if(!quiet)toast(e.message,true);}}
  }
  function updateCountdowns() {
    $$('[data-countdown]').forEach(el=>{const diff=Math.max(0,Math.floor(Number(el.dataset.countdown)-now()));const hours=Math.floor(diff/3600),minutes=Math.floor(diff%3600/60),seconds=diff%60;el.textContent=`${hours>23?Math.floor(hours/24)+'T ':''}${String(hours%24).padStart(2,'0')} : ${String(minutes).padStart(2,'0')} : ${String(seconds).padStart(2,'0')}`;if(diff===0&&!el.dataset.expired){el.dataset.expired='true';refresh(true);}});
  }
  document.addEventListener('click',async event=>{
    const button=event.target.closest('[data-action]');if(!button)return;
    const action=button.dataset.action;
    if(action==='close-modal')return closeModal();
    if(action==='toggle-password'){const input=$('#'+button.dataset.target);input.type=input.type==='password'?'text':'password';button.setAttribute('aria-label',input.type==='password'?'Passwort anzeigen':'Passwort verbergen');return;}
    if(action==='auth-tab'){state.authTab=button.dataset.tab;renderAuth();return;}
    if(action==='rules')return showRules();
    if(action==='install')return installApp();
    if(action==='refresh')return refresh();
    if(action==='profile'){location.hash='profile';return;}
    if(action==='go-games'){state.week=state.data.current_week;state.filter='all';if(location.hash==='#games')render();else location.hash='games';return;}
    if(action==='filter'){state.filter=button.dataset.filter;render();return;}
    if(action==='prev-week'||action==='next-week-view'){state.week=Math.min(22,Math.max(1,state.week+(action==='prev-week'?-1:1)));state.filter='all';render();return;}
    if(action==='pick')return stagePick(button.dataset.game,button.dataset.team);
    if(action==='confirm-pick')return confirmPick(button);
    if(action==='team-info')return showTeamInfo(button.dataset.team);
    if(action==='demo-panel')return demoPanel();
    if(action==='advance-week'){showModal(`${dialogHeader('Nächsten Spieltag öffnen?')}<p>Alle noch offenen Spiele der aktuellen Week enden mit 24 : 17 für das Auswärtsteam. Die Tipps werden ausgewertet. Dieser Schritt lässt sich nicht zurücknehmen.</p><p class="modal-error form-error" role="alert" hidden></p><div class="dialog-actions"><button class="button outline" data-action="close-modal">Abbrechen</button><button class="button primary" data-action="confirm-advance">Spieltag abschließen</button></div>`);return;}
    if(action==='confirm-advance'){
      if(state.busy)return;state.busy=true;button.disabled=true;
      try{receive(await api('demo',{action:'next_week'}));state.week=state.data.current_week;closeModal();render();toast(`${weekLabel(state.week)} ist geöffnet.`);}catch(e){$('.modal-error').hidden=false;$('.modal-error').textContent=e.message;}finally{state.busy=false;button.disabled=false;}return;
    }
    if(action==='logout'){
      button.disabled=true;try{await api('logout',{});state.epoch++;state.csrf='';state.data=null;closeModal();location.hash='';renderGate();}catch(e){toast(e.message,true);button.disabled=false;}return;
    }
    if(action==='demo-login'){
      if(state.busy)return;state.busy=true;button.disabled=true;
      try{const session=await api('login',{username:button.dataset.user,password:'Survivor2026!'});state.csrf=session.csrf;receive(await api('state'));state.route='dashboard';location.hash='dashboard';render();}catch(e){toast(e.message,true);button.disabled=false;}finally{state.busy=false;}return;
    }
  });
  document.addEventListener('change',event=>{if(event.target.id==='week-select'){state.week=Number(event.target.value);state.filter='all';render();}});
  document.addEventListener('submit',async event=>{
    const form=event.target;if(!['gate-form','account-form','settings-form','demo-form'].includes(form.id))return;event.preventDefault();if(state.busy)return;
    const values=Object.fromEntries(new FormData(form)),submitter=event.submitter;state.busy=true;if(submitter)submitter.disabled=true;
    try {
      if(form.id==='gate-form'){const session=await api('gate',{password:values.password});state.csrf=session.csrf;state.demo=session.demo;renderAuth();}
      if(form.id==='account-form'){
        const data=form.dataset.mode==='register'?values:{username:values.username,password:values.password};
        const session=await api(form.dataset.mode,data);state.csrf=session.csrf;receive(await api('state'));state.route='dashboard';location.hash='dashboard';render();
      }
      if(form.id==='settings-form'){
        const data=Object.fromEntries(['tie_is_loss','allow_after_elimination','missing_pick_eliminates'].map(k=>[k,!!form.elements[k].checked]));
        receive(await api('settings',data));render();toast('Pool-Regeln gespeichert.');
      }
      if(form.id==='demo-form'){receive(await api('demo',{...values,action:submitter.value}));closeModal();render();toast(submitter.value==='kickoff'?'Kickoff simuliert. Die Tipps sind gesperrt.':'Spiel beendet und Tipps ausgewertet.');}
    }catch(e){formError(form,e.message);}finally{state.busy=false;if(submitter)submitter.disabled=false;}
  });
  window.addEventListener('hashchange',()=>{const route=location.hash.slice(1);state.route=navigation.some(n=>n[0]===route)?route:'dashboard';if(state.data){closeModal();render();window.scrollTo({top:0,behavior:'instant'});}});
  window.addEventListener('beforeinstallprompt',event=>{event.preventDefault();state.prompt=event;});
  window.addEventListener('appinstalled',()=>{state.installed=true;state.prompt=null;if(state.data)render();toast('Survivor Pool wurde installiert.');});
  window.addEventListener('offline',()=>{state.online=false;if(state.data){render();}});
  window.addEventListener('online',()=>{if(state.data)refresh(true);else bootstrap();});
  window.addEventListener('pageshow',event=>{if(event.persisted)bootstrap();});
  document.addEventListener('visibilitychange',()=>{if(!document.hidden&&state.data)refresh(true);});
  modal.addEventListener('click',event=>{if(event.target===modal){const r=modal.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)closeModal();}});
  async function bootstrap() {
    state.epoch++;
    try{const session=await api('session');state.csrf=session.csrf;state.demo=session.demo;if(session.authenticated){receive(await api('state'));state.route=navigation.some(n=>n[0]===location.hash.slice(1))?location.hash.slice(1):'dashboard';render();}else if(session.gated){state.demo=session.demo;renderAuth();}else renderGate();}
    catch(e){renderGate(e.message);}
  }
  // Progressive enhancement. Optional agent tools use the exact same UI actions.
  if(document.modelContext?.registerTool){
    const lifecycle=new AbortController();
    for(const tool of [
      {name:'read_survivor_status',title:'Survivor-Status lesen',description:'Liest den eigenen bestätigten Tipp und die Saisonstatistik des angemeldeten Accounts.',inputSchema:{type:'object',properties:{},additionalProperties:false},annotations:{readOnlyHint:true},execute(input){if(!input||Object.keys(input).length||!state.data)throw Error('Anmeldung erforderlich oder ungültige Eingabe.');return{week:state.data.current_week,pick:currentPick()||null,stats:state.data.me.stats};}},
      {name:'stage_survivor_pick',title:'Survivor-Tipp vorbereiten',description:'Öffnet den Bestätigungsdialog für einen Tipp. Speichert keinen Tipp; der Nutzer bestätigt im sichtbaren Dialog.',inputSchema:{type:'object',properties:{game_id:{type:'string'},team:{type:'string'}},required:['game_id','team'],additionalProperties:false},annotations:{readOnlyHint:false},execute(input){if(!state.data||!input||Object.keys(input).some(k=>!['game_id','team'].includes(k))||typeof input.game_id!=='string'||typeof input.team!=='string')throw Error('Ungültige Eingabe.');const g=gameById(input.game_id);if(!g||![g.home,g.away].includes(input.team))throw Error('Ungültiges Spiel oder Team.');const e=eligibility(g,input.team);if(e.reasons.length)throw Error(e.reasons.join(' '));stagePick(input.game_id,input.team);return{staged:!e.selected,saved:false};}}
    ]){try{Promise.resolve(document.modelContext.registerTool(tool,{signal:lifecycle.signal})).catch(()=>{});}catch(_){}}
    window.addEventListener('pagehide',()=>lifecycle.abort(),{once:true});
  }
  if('serviceWorker' in navigator && ['http:','https:'].includes(location.protocol)) navigator.serviceWorker.register('/service-worker.js').catch(()=>{});
  setInterval(updateCountdowns,1000);setInterval(()=>{if(!document.hidden)refresh(true);},20000);
  bootstrap();
})();
