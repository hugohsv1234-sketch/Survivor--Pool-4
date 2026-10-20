/* Turn the user's 8x4 NFL sprite into 32 genuine transparent team crests.
   No external images, no changes to pool logic, and no persistent data stored. */
(() => {
  'use strict';
  if (!('Image' in window) || !('MutationObserver' in window)) return;
  const teams = ['BAL','CIN','CLE','PIT','HOU','IND','JAX','TEN','BUF','MIA','NE','NYJ','DEN','KC','LV','LAC','CHI','DET','GB','MIN','ATL','CAR','NO','TB','DAL','NYG','PHI','WAS','ARI','LAR','SF','SEA'];
  const photos = new Array(32);
  let updatePending = false;

  function displayLogos() {
    updatePending = false;
    document.querySelectorAll('.team-logo-wrap .reference-logo').forEach(label => {
      const match = /(?:^|\s)reference-logo-(\d+)(?:\s|$)/.exec(label.className);
      if (!match) return;
      const index = Number(match[1]);
      if (index < 0 || index >= teams.length) return;
      const src = photos[index];
      if (src) {
        const image = document.createElement('img');
        image.className = 'team-logo logo-loaded transparent-nfl-logo';
        image.src = src;
        image.alt = '';
        image.draggable = false;
        label.replaceWith(image);
      } else if (label.textContent !== teams[index]) {
        // No white background while processing, or if the source is unavailable.
        label.textContent = teams[index];
      }
    });
  }

  function scheduleDisplay() {
    if (updatePending) return;
    updatePending = true;
    requestAnimationFrame(displayLogos);
  }

  const app = document.getElementById('app');
  if (app) new MutationObserver(scheduleDisplay).observe(app, {childList:true, subtree:true});
  scheduleDisplay();

  function extractLogo(sheetContext, tileContext, size, index) {
    const pixels = sheetContext.getImageData((index % 8) * size, Math.floor(index / 8) * size, size, size);
    const rgba = pixels.data;
    const count = size * size;
    const center = (size - 1) / 2;
    const seedRadiusSquared = Math.pow(size * 41 / 98, 2);
    const outerRadius = size * 42.5 / 98;
    const feather = size * 2.5 / 98;
    const connectedBackground = new Uint8Array(count);
    const queue = new Int32Array(count);
    let first = 0, last = 0;

    const nearWhite = pixel => {
      const i = pixel * 4;
      const red = rgba[i], green = rgba[i+1], blue = rgba[i+2];
      return Math.min(red, green, blue) >= 214 && Math.max(red, green, blue) - Math.min(red, green, blue) < 55;
    };
    const visit = pixel => {
      if (connectedBackground[pixel] || !nearWhite(pixel)) return;
      connectedBackground[pixel] = 1;
      queue[last++] = pixel;
    };

    // Start from the white region surrounding each logo.
    for (let pixel = 0; pixel < count; pixel++) {
      const x = pixel % size, y = Math.floor(pixel / size);
      const dx = x - center, dy = y - center;
      if (dx*dx + dy*dy >= seedRadiusSquared) visit(pixel);
    }
    // Flood-fill outward-connected white, retaining enclosed white logo details.
    while (first < last) {
      const pixel = queue[first++];
      const x = pixel % size;
      if (x > 0) visit(pixel-1);
      if (x < size-1) visit(pixel+1);
      if (pixel >= size) visit(pixel-size);
      if (pixel < count-size) visit(pixel+size);
    }
    // Remove the black and yellow framing ring with anti-aliased edges.
    for (let pixel = 0; pixel < count; pixel++) {
      const x = pixel % size, y = Math.floor(pixel / size);
      const distance = Math.hypot(x-center, y-center);
      const fade = Math.max(0, Math.min(1, (outerRadius-distance) / feather));
      const alpha = pixel*4+3;
      rgba[alpha] = connectedBackground[pixel] ? 0 : Math.round(rgba[alpha]*fade);
    }
    tileContext.putImageData(pixels, 0, 0);
  }

  const sprite = new Image();
  sprite.onload = () => {
    try {
      const size = sprite.naturalWidth / 8;
      if (!Number.isInteger(size) || sprite.naturalHeight !== size*4 || size < 40 || size > 512) throw new Error('Bildmaße stimmen nicht.');
      const sheet = document.createElement('canvas');
      sheet.width = sprite.naturalWidth;
      sheet.height = sprite.naturalHeight;
      const ctx = sheet.getContext('2d', {willReadFrequently:true});
      const tile = document.createElement('canvas');
      tile.width = size;
      tile.height = size;
      const tileCtx = tile.getContext('2d', {willReadFrequently:true});
      if (!ctx || !tileCtx) throw new Error('Canvas nicht unterstützt.');
      ctx.drawImage(sprite, 0, 0);
      let nextIndex = 0;
      function nextBatch() {
        try {
          const stop = Math.min(nextIndex+4, 32);
          for (; nextIndex < stop; nextIndex++) {
            extractLogo(ctx, tileCtx, size, nextIndex);
            photos[nextIndex] = tile.toDataURL('image/png');
          }
          scheduleDisplay();
          if (nextIndex < 32) requestAnimationFrame(nextBatch);
        } catch (error) {
          console.warn('Teamlogos konnten nicht transparent gemacht werden:', error);
        }
      }
      nextBatch();
    } catch (error) {
      console.warn('Logo-Datei konnte nicht verarbeitet werden:', error);
    }
  };
  sprite.onerror = () => console.warn('Die hochgeladene NFL-Logo-Datei ist nicht erreichbar.');
  sprite.src = '/icons/nfl-logo-sprite.png';
})();
