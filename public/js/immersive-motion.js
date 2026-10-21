/* Survivor Pool · presentation director
 * No requests, routing, state, eligibility or form handling live here.
 * Native controls are usable immediately, including while animations play.
 */
(() => {
  'use strict';
  const root = document.querySelector('#app');
  if (!root) return;

  const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)');
  const fine = window.matchMedia?.('(hover: hover) and (pointer: fine)');
  const EASE = 'cubic-bezier(.22,.8,.24,1)';
  const counters = new Map();
  const counterFrames = new Map();
  const animations = new Set();
  const ripples = new Map();
  const markers = new Map();
  let revealObserver = null;
  let renderFrame = 0, pointerFrame = 0, stageFrame = 0;
  let currentPage = null, lastSignature = null, lastViewer = null;
  let rowPositions = new Map(), cardStates = new Map();
  let hover = null, hoverBounds = null, point = null, stage = null;
  let heroPoint = {x:0,y:0};
  let disposed = false;
  const enabled = () => !reduced?.matches && !document.hidden && !disposed;
  // Nested cards own their pointer effect. Their containing panel stays level,
  // so moving onto a fixture never stacks two rotations or moves its controls.
  const widgetSelector = [
    '.panel', '.broadcast-layout>section', '.game-card', '.stat-card',
    '.inventory-team', '.pick-hero', '.rule-note', '.account-setting',
    '.season-milestones>div', '.auth-card', '.paetzold-stadium-hero',
    '.empty-state', '.notice', '.pick-strip', '.public-bets-widget', '.pool-pick-rate', '#modal'
  ].join(',');
  const revealSelectors = [
    '.page-heading', '.stats-grid .stat-card', '.broadcast-pick-title',
    '.pick-hero', '.section-heading', '.game-card', '.ranking-panel',
    '.recent-panel', '.season-panel', '.season-milestones>div',
    '.leaderboard-row', '.profile-grid>.panel', '.inventory-team',
    '.history-pick', '.account-settings-panel', '.account-setting',
    '.admin-panel', '.empty-state', '.rule-note'
  ].join(',');

  function play(node, keyframes, options) {
    if (!enabled() || !node?.isConnected || !node.animate) return;
    const animation = node.animate(keyframes, {duration:440,easing:EASE,...options});
    animations.add(animation);
    animation.finished.then(() => animations.delete(animation), () => animations.delete(animation));
    return animation;
  }

  function finishCounter(record) {
    cancelAnimationFrame(record.frame);
    if (record.text.isConnected) record.text.textContent = record.final;
    record.node.classList.remove('pm-value-updated');
    counterFrames.delete(record.node);
  }

  function stopEffects() {
    for (const animation of animations) animation.cancel();
    animations.clear();
    for (const record of counterFrames.values()) finishCounter(record);
    for (const [node, timer] of ripples) { clearTimeout(timer); node.remove(); }
    ripples.clear();
    revealObserver?.disconnect();
    root.querySelectorAll('.pm-wait').forEach(node => {
      node.classList.remove('pm-wait');node.classList.add('pm-visible');
    });
  }

  function routeSignature() {
    const form = root.querySelector('#account-form');
    if (form) return 'auth:' + form.dataset.mode;
    const active = root.querySelector('.sidebar .nav-link[aria-current="page"]');
    const route = active?.getAttribute('href') || location.hash || '#dashboard';
    const week = root.querySelector('#week-select')?.value || '';
    const filter = root.querySelector('.filter .active')?.dataset.filter || '';
    return [route,week,filter].join(':');
  }

  function animateCounter(card, route) {
    const node = card.querySelector('strong');
    if (!node) return;
    const text = Array.from(node.childNodes).find(child =>
      child.nodeType === 3 && /^\s*\d+(?:[.,]\d+)?\s*$/.test(child.textContent));
    if (!text) return;
    const final = text.textContent;
    const raw = final.trim();
    const value = Number(raw.replace(',', '.'));
    if (!Number.isFinite(value) || value > 999999) return;
    const label = card.querySelector('div>span')?.textContent || '';
    const key = route.split(':')[0] + ':' + label;
    const previous = counters.get(key);
    counters.set(key,value);
    if (!enabled() || previous === value || value === 0 && previous === undefined) return;
    const old = counterFrames.get(node);
    if (old) finishCounter(old);
    const unit = node.querySelector('small')?.textContent || '';
    // Assistive technology has the final confirmed value throughout the effect.
    node.setAttribute('aria-label',raw + (unit === '%' ? ' Prozent' : unit));
    const start = previous !== undefined && Math.abs(value-previous) < 1000 ? previous : 0;
    const digits = raw.match(/[.,](\d+)/)?.[1].length || 0;
    const comma = raw.includes(',');
    const record = {node,text,final,frame:0};
    counterFrames.set(node,record);
    node.classList.add('pm-value-updated');
    let began = null;
    const tick = timestamp => {
      if (!enabled() || !text.isConnected) {finishCounter(record);return;}
      if (began === null) began = timestamp;
      const progress = Math.min(1,(timestamp-began)/620);
      const next = (start + (value-start)*(1-Math.pow(1-progress,3))).toFixed(digits);
      text.textContent = comma ? next.replace('.',',') : next;
      if (progress < 1) record.frame = requestAnimationFrame(tick);
      else finishCounter(record);
    };
    record.frame = requestAnimationFrame(tick);
  }

  function reveal(node, index, signature) {
    node.classList.remove('pm-wait');node.classList.add('pm-visible');
    if (!enabled()) return;
    const row = node.matches('.leaderboard-row,.history-pick,.inventory-team');
    play(node,[
      {opacity:.38,translate:row ? '-5px 7px' : '0 14px'},
      {opacity:1,translate:'0 0'}
    ],{duration:row?440:540,delay:Math.min(index,5)*32,fill:'backwards'});
    if (node.matches('.stat-card')) animateCounter(node,signature);
  }

  function prepareReveals(page, signature) {
    const nodes = Array.from(page.querySelectorAll(revealSelectors)).slice(0,180);
    if ('IntersectionObserver' in window) {
      revealObserver = new IntersectionObserver((entries, observer) => {
        for (const entry of entries) {
          if (!entry.isIntersecting || !entry.target.isConnected) continue;
          const index = Number(entry.target.dataset.pmOrder || 0);
          reveal(entry.target,index,signature);
          observer.unobserve(entry.target);
        }
      },{rootMargin:'0px 0px 32px 0px',threshold:.025});
      nodes.forEach((node,index) => {
        node.classList.add('pm-reveal','pm-wait');
        node.dataset.pmOrder = String(index%6);
        revealObserver.observe(node);
      });
    } else {
      nodes.forEach((node,index) => reveal(node,index%6,signature));
    }
    for (const track of page.querySelectorAll('.public-bets-bar,.pool-pick-rate-track')) {
      for (const bar of track.children) play(bar,[{scale:'0 1'},{scale:'1 1'}],{duration:650});
    }
    const progress = root.querySelector('.season-progress i');
    if (progress) play(progress,[{scale:'0 1'},{scale:'1 1'}],{duration:700});
  }

  function positionMarker(parent, active, key, horizontal, animate) {
    if (!parent || !active || !parent.getClientRects().length) return;
    const p = parent.getBoundingClientRect(), r = active.getBoundingClientRect();
    const next = horizontal
      ? {x:r.left-p.left+9,y:0,w:Math.max(8,r.width-18),h:3}
      : {x:0,y:r.top-p.top+14,w:3,h:Math.max(8,r.height-28)};
    const marker = document.createElement('span');
    marker.setAttribute('aria-hidden','true');marker.className = 'pm-nav-indicator';
    Object.assign(marker.style,{width:next.w+'px',height:next.h+'px',transform:`translate(${next.x}px,${next.y}px)`});
    parent.querySelector('.pm-nav-indicator')?.remove();
    parent.classList.add('pm-managed-nav');parent.append(marker);
    const before = markers.get(key);
    markers.set(key,next);
    if (animate && before) play(marker,[
      {transform:`translate(${before.x}px,${before.y}px)`},
      {transform:`translate(${next.x}px,${next.y}px)`}
    ],{duration:360});
  }

  function updateIndicators(animate = true) {
    const sidebar = root.querySelector('.sidebar nav');
    positionMarker(sidebar,sidebar?.querySelector('[aria-current="page"]'),'sidebar',false,animate);
    const bottom = root.querySelector('.bottom-nav');
    positionMarker(bottom,bottom?.querySelector('[aria-current="page"]'),'bottom',true,animate);
    for (const segmented of root.querySelectorAll('.segmented')) {
      const active = segmented.querySelector('button.active');
      if (!active || !segmented.getClientRects().length) continue;
      const p = segmented.getBoundingClientRect(), r = active.getBoundingClientRect();
      const next = {x:r.left-p.left,y:r.top-p.top,w:r.width,h:r.height};
      const key = segmented.closest('.auth-card') ? 'auth' : 'filter';
      const old = markers.get(key);
      markers.set(key,next);
      const marker = document.createElement('span');
      marker.setAttribute('aria-hidden','true');marker.className = 'pm-segment-indicator';
      Object.assign(marker.style,{width:next.w+'px',height:next.h+'px',transform:`translate(${next.x}px,${next.y}px)`});
      segmented.querySelector('.pm-segment-indicator')?.remove();
      segmented.classList.add('pm-managed-segments');segmented.append(marker);
      if (animate && old) play(marker,[
        {transform:`translate(${old.x}px,${old.y}px) scaleX(${old.w/next.w})`,transformOrigin:'left'},
        {transform:`translate(${next.x}px,${next.y}px) scaleX(1)`,transformOrigin:'left'}
      ],{duration:260});
    }
  }

  function animateDataUpdates(page, sameView) {
    const positions = new Map(), states = new Map();
    for (const row of page.querySelectorAll('.leaderboard-row,.mini-player')) {
      const user = row.querySelector('.leader-player>span:last-child>small,.mini-player-name>small')?.textContent;
      if (!user) continue;
      const key = (row.matches('.leaderboard-row')?'full:':'mini:') + user;
      const rect = row.getBoundingClientRect();
      const next = {y:rect.top+window.scrollY,text:row.textContent};
      const old = rowPositions.get(key);
      positions.set(key,next);
      if (!sameView || !old) continue;
      const delta = old.y-next.y;
      if (Math.abs(delta)>1 && Math.abs(delta)<700) play(row,[{translate:`0 ${delta}px`},{translate:'0 0'}],{duration:380});
      if (old.text !== next.text) play(row.querySelector('.leader-player,.mini-player-name'),[{opacity:.4},{opacity:1}],{duration:480});
    }
    for (const card of page.querySelectorAll('.game-card')) {
      const key = card.querySelector('[data-game]')?.dataset.game;
      if (!key) continue;
      const value = card.textContent + ':' + (card.querySelector('[aria-pressed="true"]')?.dataset.team || '');
      states.set(key,value);
      if (sameView && cardStates.has(key) && cardStates.get(key) !== value) {
        play(card.querySelector('.game-card-head'),[{opacity:.45},{opacity:1}],{duration:480});
      }
    }
    rowPositions = positions;cardStates = states;
  }

  function decorateWidgets(page) {
    const widgets = Array.from(page.querySelectorAll(widgetSelector));
    if (page.matches(widgetSelector)) widgets.unshift(page);
    for (const node of widgets) {
      node.classList.add('pm-widget');
      if (node.querySelector(':scope>.pm-widget-light')) continue;
      // A separate decorative layer preserves existing pseudo-elements, status
      // colours, team logos and text. It never receives pointer or focus events.
      const light = document.createElement('span');
      light.className = 'pm-widget-light';light.setAttribute('aria-hidden','true');
      node.append(light);
    }
  }

  function decorate() {
    renderFrame = 0;
    if (disposed) return;
    const page = root.querySelector('.page-content') || root.querySelector('.auth-card');
    if (!page || page === currentPage) return;
    const signature = routeSignature();
    const changedView = signature !== lastSignature;
    const viewer = root.querySelector('.sidebar-user small')?.textContent || 'auth';
    if (viewer !== lastViewer) {counters.clear();markers.clear();rowPositions.clear();cardStates.clear();}
    lastViewer = viewer;
    stopEffects();resetHover();
    currentPage = page;
    stage = root.querySelector('.paetzold-stadium-hero');
    heroPoint = {x:0,y:0};
    decorateWidgets(page);
    updateIndicators(changedView);
    if (changedView && enabled()) {
      page.classList.add('pm-route-enter');
      if (!page.matches('.auth-card')) play(page,[{opacity:.65,translate:'0 5px'},{opacity:1,translate:'0 0'}],{duration:330});
      prepareReveals(page,signature);
      if (page.matches('.auth-card')) {
        play(page,[{opacity:.5,translate:'0 12px',scale:'.985'},{opacity:1,translate:'0 0',scale:'1'}],{duration:460});
      }
    } else {
      page.querySelectorAll('.stat-card').forEach(card => animateCounter(card,signature));
    }
    animateDataUpdates(page,!changedView);
    lastSignature = signature;
    scheduleStage();
  }

  function scheduleDecorate() {
    if (!renderFrame && !disposed) renderFrame = requestAnimationFrame(decorate);
  }
  const changes = typeof MutationObserver === 'function' ? new MutationObserver(scheduleDecorate) : null;
  changes?.observe(root,{childList:true});

  function resetHover() {
    if (hover) {
      hover.classList.remove('pm-tilting');
      for (const prop of ['--pm-tilt-x','--pm-tilt-y','--pm-light-x','--pm-light-y']) hover.style.removeProperty(prop);
    }
    hover = null;hoverBounds = null;point = null;
    if (pointerFrame) cancelAnimationFrame(pointerFrame);
    pointerFrame = 0;
  }

  function paintPointer() {
    pointerFrame = 0;
    if (!enabled() || !fine?.matches || !hover?.isConnected || !point) return;
    const r = hoverBounds;
    if (!r) return;
    const x = Math.max(0,Math.min(1,(point.x-r.left)/Math.max(1,r.width)));
    const y = Math.max(0,Math.min(1,(point.y-r.top)/Math.max(1,r.height)));
    // Use the resting rectangle, never the rotated rectangle. This avoids a
    // feedback loop at card edges. Large tables rotate less than small widgets.
    const angle = Math.max(1.6,Math.min(6,2100/Math.max(r.width,r.height)));
    hover.style.setProperty('--pm-light-x',(x*100).toFixed(1)+'%');
    hover.style.setProperty('--pm-light-y',(y*100).toFixed(1)+'%');
    hover.style.setProperty('--pm-tilt-x',((.5-y)*2*angle).toFixed(2)+'deg');
    hover.style.setProperty('--pm-tilt-y',((x-.5)*2*angle).toFixed(2)+'deg');
    hover.classList.add('pm-tilting');
  }

  function paintStage() {
    stageFrame = 0;
    if (!enabled() || !stage?.isConnected || !fine?.matches) return;
    const r = stage.getBoundingClientRect();
    if (r.bottom<0 || r.top>window.innerHeight) return;
    const offset = Math.max(-1,Math.min(1,(window.innerHeight*.48-r.top-r.height*.5)/window.innerHeight));
    stage.style.setProperty('--hero-scroll-y',(offset*9).toFixed(1)+'px');
    stage.style.setProperty('--hero-drift-x',(heroPoint.x*9).toFixed(1)+'px');
    stage.style.setProperty('--hero-drift-y',(heroPoint.y*5).toFixed(1)+'px');
    stage.style.setProperty('--hero-heading-x',(-heroPoint.x*2).toFixed(1)+'px');
  }
  function scheduleStage() {
    if (enabled() && fine?.matches && !stageFrame) stageFrame = requestAnimationFrame(paintStage);
  }

  document.addEventListener('pointermove',event => {
    if (!enabled() || !fine?.matches || event.pointerType === 'touch') return;
    let target = event.target?.closest?.('.pm-widget');
    // Native dialogs retarget backdrop pointer events to the dialog itself.
    // Treat that area as outside the widget, so it settles on backdrop hover.
    if (target?.matches('dialog')) {
      const r = target === hover && hoverBounds ? hoverBounds : target.getBoundingClientRect();
      if (event.clientX<r.left || event.clientX>r.left+r.width ||
          event.clientY<r.top || event.clientY>r.top+r.height) target = null;
    }
    if (target !== hover) {
      resetHover();hover = target;
      if (target) {
        const r = target.getBoundingClientRect();
        hoverBounds = {left:r.left,top:r.top,width:r.width,height:r.height};
      }
    }
    if (target) {
      point = {x:event.clientX,y:event.clientY};
      if (!pointerFrame) pointerFrame = requestAnimationFrame(paintPointer);
    }
    const hero = event.target?.closest?.('.paetzold-stadium-hero');
    if (hero) {
      stage = hero;
      const r = hero.getBoundingClientRect();
      heroPoint = {
        x:Math.max(-1,Math.min(1,(event.clientX-r.left)/Math.max(1,r.width)*2-1)),
        y:Math.max(-1,Math.min(1,(event.clientY-r.top)/Math.max(1,r.height)*2-1))
      };
      scheduleStage();
    }
  },{passive:true});
  document.addEventListener('pointerout',event => {
    if (hover && !hover.contains(event.relatedTarget)) resetHover();
    if (stage && !stage.contains(event.relatedTarget)) {heroPoint = {x:0,y:0};scheduleStage();}
  },{passive:true});
  function releasePointer() {resetHover();heroPoint = {x:0,y:0};scheduleStage();}
  document.addEventListener('pointercancel',releasePointer,{passive:true});
  window.addEventListener('blur',releasePointer);
  document.addEventListener('pointerup',event => {if (event.pointerType === 'touch') releasePointer();},{passive:true});
  document.addEventListener('pointerdown',event => {
    if (!enabled() || event.button>0) return;
    const target = event.target?.closest?.('button,.panel-link,.nav-link,.bottom-nav a');
    if (!target || target.matches(':disabled,[aria-disabled="true"]')) return;
    const r = target.getBoundingClientRect();
    const ripple = document.createElement('span');
    ripple.className = 'motion-tap-ripple';ripple.setAttribute('aria-hidden','true');
    Object.assign(ripple.style,{
      left:(event.clientX-r.left)+'px',top:(event.clientY-r.top)+'px',
      width:Math.max(r.width,r.height)*2+'px',height:Math.max(r.width,r.height)*2+'px'
    });
    target.append(ripple);
    const remove = () => {clearTimeout(ripples.get(ripple));ripples.delete(ripple);ripple.remove();};
    ripples.set(ripple,setTimeout(remove,650));
    ripple.addEventListener('animationend',remove,{once:true});
  },{passive:true});
  // Reset on every scrolling surface, including the horizontal season matrix.
  // A stationary pointer must not leave a card tilted after it moves away.
  document.addEventListener('scroll',() => {resetHover();scheduleStage();},{passive:true,capture:true});
  window.addEventListener('resize',() => {resetHover();updateIndicators(false);scheduleStage();},{passive:true});

  // A dialog can replace its content while already open. Watch only the native
  // dialog's shell; focus, Escape, dismissal and confirmation stay app-owned.
  const modal = document.querySelector('#modal');
  const dialogChanges = typeof MutationObserver === 'function' && modal ? new MutationObserver(records => {
    // Ignore our own inert light insertion; it must not restart dialog entry.
    if (records.every(record => record.type === 'childList' &&
      [...record.addedNodes,...record.removedNodes].every(node => node.nodeType === 1 && node.classList.contains('pm-widget-light')))) return;
    if (!modal.open) {if (hover && modal.contains(hover)) resetHover();return;}
    decorateWidgets(modal);
    if (!enabled()) return;
    play(modal,[{opacity:.3,translate:'0 14px',scale:'.975'},{opacity:1,translate:'0 0',scale:'1'}],{duration:260});
    modal.querySelectorAll('.rules-list>div').forEach((row,index) =>
      play(row,[{opacity:.5,translate:'0 7px'},{opacity:1,translate:'0 0'}],{duration:360,delay:index*35}));
  }) : null;
  dialogChanges?.observe(modal,{childList:true,attributes:true,attributeFilter:['open']});

  function preferencesChanged() {
    stopEffects();resetHover();
    if (stageFrame) cancelAnimationFrame(stageFrame);
    stageFrame = 0;
    if (stage) ['--hero-scroll-y','--hero-drift-x','--hero-drift-y','--hero-heading-x'].forEach(prop => stage.style.removeProperty(prop));
    heroPoint = {x:0,y:0};
    if (enabled()) scheduleStage();
  }
  reduced?.addEventListener?.('change',preferencesChanged);
  fine?.addEventListener?.('change',preferencesChanged);
  document.addEventListener('visibilitychange',() => {
    document.documentElement?.classList.toggle('pm-paused',document.hidden);
    if (document.hidden) {
      stopEffects();resetHover();
      if (stageFrame) cancelAnimationFrame(stageFrame);
      if (renderFrame) cancelAnimationFrame(renderFrame);
      stageFrame = renderFrame = 0;
    } else {scheduleDecorate();scheduleStage();}
  });
  window.addEventListener('pagehide',() => {
    disposed = true;stopEffects();resetHover();
    if (renderFrame) cancelAnimationFrame(renderFrame);
    if (stageFrame) cancelAnimationFrame(stageFrame);
    renderFrame = stageFrame = 0;
    changes?.disconnect();dialogChanges?.disconnect();
  });
  window.addEventListener('pageshow',event => {
    if (!event.persisted) return;
    disposed = false;currentPage = null;
    changes?.observe(root,{childList:true});
    if (modal) dialogChanges?.observe(modal,{childList:true,attributes:true,attributeFilter:['open']});
    document.documentElement?.classList.remove('pm-paused');
    scheduleDecorate();
  });
  decorate();
})();
