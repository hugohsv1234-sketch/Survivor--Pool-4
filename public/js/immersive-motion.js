/* Progressive enhancement: scroll-into-view, touch/scroll drift and player
   depth. Does not move pick controls, touch scrolling, focus or data. */
(() => {
  'use strict';
  const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)');
  const fine = window.matchMedia?.('(hover: hover) and (pointer: fine)');
  if (reduce?.matches) return;
  const targetSelector = [
    '.cinematic-dashboard .stat-card',
    '.cinematic-dashboard .game-card',
    '.cinematic-dashboard .mini-player',
    '.cinematic-dashboard .recent-pick',
    '.cinematic-dashboard .ranking-panel',
    '.cinematic-dashboard .recent-panel',
    '.profile-grid .panel',
    '.leaderboard-panel .leaderboard-row',
    '.season-panel .season-table',
    '.cinematic-dashboard .broadcast-pick-title',
    '.cinematic-dashboard .section-heading'
  ].join(',');
  const seen = new WeakSet();
  let observer;
  if ('IntersectionObserver' in window) {
    observer = new IntersectionObserver((entries, io) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        const item = entry.target;
        item.classList.remove('motion-pending');
        item.classList.add('motion-visible');
        io.unobserve(item);
      }
    }, {rootMargin:'0px 0px 56px 0px',threshold:0.09});
  }
  const scan = () => {
    if (!observer || reduce?.matches) return;
    const items = document.querySelectorAll(targetSelector);
    for (const item of items) {
      if (seen.has(item)) continue;
      seen.add(item);
      item.classList.add('motion-reveal-item','motion-pending');
      const index = Array.prototype.indexOf.call(item.parentElement?.children||[],item);
      item.style.setProperty('--motion-stagger',Math.min(7,Math.max(0,index))*45+'ms');
      observer.observe(item);
    }
  };
  const motion = {x:0,y:0,scroll:0};
  let frame=0,activeHero=null;
  const update = () => {
    frame=0;
    const hero=activeHero && activeHero.isConnected ? activeHero
      : document.querySelector('.paetzold-stadium-hero');
    if (!hero || reduce?.matches) return;
    activeHero=hero;
    const rect=hero.getBoundingClientRect();
    // Gentle scroll-based parallax even when the visitor uses touch.
    const progress=Math.max(-1,Math.min(1,(window.innerHeight*.55-(rect.top+rect.height*.5))/Math.max(320,window.innerHeight)));
    const y=Math.round(progress*10);
    hero.style.setProperty('--hero-scroll-y',y+'px');
    hero.style.setProperty('--hero-drift-x',(motion.x*13).toFixed(1)+'px');
    hero.style.setProperty('--hero-drift-y',(motion.y*8).toFixed(1)+'px');
    hero.style.setProperty('--hero-heading-x',(-motion.x*3).toFixed(1)+'px');
  };
  const schedule = () => {
    if (!frame) frame=window.requestAnimationFrame(update);
  };
  document.addEventListener('pointermove',event=>{
    if (!fine?.matches || reduce?.matches) return;
    const hero=event.target?.closest?.('.paetzold-stadium-hero');
    if (!hero) return;
    activeHero=hero;
    const rect=hero.getBoundingClientRect();
    motion.x=Math.max(-1,Math.min(1,(event.clientX-rect.left)/Math.max(1,rect.width)*2-1));
    motion.y=Math.max(-1,Math.min(1,(event.clientY-rect.top)/Math.max(1,rect.height)*2-1));
    schedule();
  },{passive:true});
  document.addEventListener('pointerout',event=>{
    const hero=event.target?.closest?.('.paetzold-stadium-hero');
    if (!hero || hero.contains(event.relatedTarget)) return;
    motion.x=0;motion.y=0;schedule();
  },{passive:true});
  window.addEventListener('scroll',schedule,{passive:true});
  window.addEventListener('resize',schedule,{passive:true});
  document.addEventListener('visibilitychange',()=>{
    if (!document.hidden) {scan();schedule();}
  });
  const root=document.querySelector('#app');
  if (root && 'MutationObserver' in window) {
    const changes=new MutationObserver(()=>{
      scan();
      schedule();
    });
    changes.observe(root,{childList:true,subtree:false});
    // The app replaces its content on route changes.
  }
  // React to OS accessibility setting changes during the session as well.
  reduce?.addEventListener?.('change',()=>{
    if (reduce.matches) {
      if (frame) window.cancelAnimationFrame(frame);
      frame=0;
      observer?.disconnect();
      document.querySelectorAll('.motion-pending').forEach(item=>item.classList.remove('motion-pending'));
      const hero=document.querySelector('.paetzold-stadium-hero');
      for (const key of ['--hero-scroll-y','--hero-drift-x','--hero-drift-y','--hero-heading-x']) hero?.style.removeProperty(key);
    } else {
      scan();schedule();
    }
  });
  scan();
  schedule();
})();
