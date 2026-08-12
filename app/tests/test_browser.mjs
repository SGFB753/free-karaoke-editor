// A real browser, not jsdom: jsdom draws nothing, so the troubles you meet “on
// opening” — a broken layout, an invisible button, a stray scrollbar, the wrong
// font size — pass straight through it unnoticed.
//
// What is needed once:
//   npm install puppeteer && npx puppeteer browsers install chrome
//
// How to run it (the studio must be up on 8770, with a built page next to it,
// karaoke.html; the path to it can also be passed the second way below):
//   node tests/test_browser.mjs
//   node tests/test_browser.mjs --shots      screenshots into shots/ as well
//   PAGE=/path/to/song_karaoke.html node tests/test_browser.mjs
import puppeteer from 'puppeteer';
import fs from 'fs';
import path from 'path';

const API = process.env.KARAOKE_API || 'http://127.0.0.1:8770';
const PAGE = path.resolve(process.env.PAGE || 'stems.html');
const SHOTS = process.argv.includes('--shots');
const shotDir = path.resolve('shots');
if (SHOTS && !fs.existsSync(shotDir)) fs.mkdirSync(shotDir);

let fail = 0;
const ok = (n, c, e = '') => { console.log((c ? '  ✓ ' : '  ✗ ') + n + (e ? ' — ' + e : '')); if (!c) fail++; };
const sleep = ms => new Promise(r => setTimeout(r, ms));

// The common troubles of the first screen, the same for any page.
async function firstScreen(page, name, errs){
  const r = await page.evaluate(() => {
    const el = document.documentElement;
    const over = [];
    // Elements sticking out past the right edge — the most visible kind of mess.
    // Those clipped by an overflow:hidden ancestor do not count: the timeline is
    // deliberately wider than the screen, its blocks simply run off and get clipped.
    const clippedByParent = e => {
      for (let p = e.parentElement; p; p = p.parentElement){
        const st = getComputedStyle(p);
        if (st.overflow !== 'visible' || st.overflowX !== 'visible') return true;
      }
      return false;
    };
    for (const e of document.querySelectorAll('body *')){
      const s = getComputedStyle(e);
      if (s.display === 'none' || s.visibility === 'hidden' || !e.offsetParent) continue;
      const b = e.getBoundingClientRect();
      if (b.width && b.right > innerWidth + 1 && !clippedByParent(e))
        over.push(e.id || e.className || e.tagName);
    }
    // text that did not fit its box vertically
    const clipped = [];
    for (const e of document.querySelectorAll('button, .howto, .hint, h1, h2, h3')){
      if (!e.offsetParent) continue;
      if (e.scrollHeight > e.clientHeight + 3 && getComputedStyle(e).overflow !== 'auto')
        clipped.push((e.id || e.tagName) + ': ' + e.textContent.trim().slice(0, 24));
    }
    return {
      scrollX: el.scrollWidth > el.clientWidth,
      over: over.slice(0, 5),
      clipped: clipped.slice(0, 5),
      // the background may be a gradient — then the colour is transparent but an image is there
      bodyBg: getComputedStyle(document.body).backgroundColor,
      bodyImg: getComputedStyle(document.body).backgroundImage,
      title: document.title,
    };
  });
  ok(`${name}: no sideways scrolling`, !r.scrollX);
  ok(`${name}: nothing ran off the window edge`, r.over.length === 0, r.over.join(', '));
  ok(`${name}: the labels fit inside the buttons`, r.clipped.length === 0, r.clipped.join(' | '));
  const painted = (r.bodyImg && r.bodyImg !== 'none') ||
                  (r.bodyBg !== 'rgba(0, 0, 0, 0)' && r.bodyBg !== 'rgb(255, 255, 255)');
  ok(`${name}: the background is painted, not the default white`, painted,
     r.bodyBg + ' / ' + (r.bodyImg || '').slice(0, 40));
  ok(`${name}: no errors in the console`, errs.length === 0, errs.slice(0, 3).join(' | '));
  return r;
}


// Whether the lyrics are visible on stage: have they run off the edges, are they near the centre.
// That is exactly what broke — paddings in fractions of the window on a stage shorter than it.
async function stageText(page, name, sel){
  const r = await page.evaluate((sel) => {
    const stage = document.querySelector(sel.stage).getBoundingClientRect();
    const lines = [...document.querySelectorAll(sel.line)];
    const seen = lines.filter(l => { const b = l.getBoundingClientRect();
      return b.height > 0 && b.bottom > stage.top + 4 && b.top < stage.bottom - 4; });
    const mid = stage.top + stage.height / 2;
    const nearest = seen.map(l => { const b = l.getBoundingClientRect();
      return Math.abs((b.top + b.bottom) / 2 - mid); }).sort((a,b)=>a-b)[0];
    return {seen: seen.length, total: lines.length, nearest: nearest ?? 1e9,
            h: stage.height,
            first: seen.length ? seen[0].textContent.trim().slice(0, 28) : ''};
  }, sel);
  ok(`${name}: the lyrics are visible on stage`, r.seen >= 2,
     `visible ${r.seen} of ${r.total}, stage ${r.h.toFixed(0)}px`);
  ok(`${name}: the line sits close to the centre of the stage`, r.nearest < r.h * 0.3,
     `${r.nearest.toFixed(0)}px from the centre with a height of ${r.h.toFixed(0)}px`);
  return r;
}

const browser = await puppeteer.launch({
  headless: 'new',
  args: ['--no-sandbox', '--disable-dev-shm-usage', '--autoplay-policy=no-user-gesture-required'],
});

try {
  /* ===================== 1. Студия ===================== */
  console.log('=== the studio: how it opens ===');
  let page = await browser.newPage();
  await page.setViewport({width: 1280, height: 800});
  const errs = [];
  page.on('pageerror', e => errs.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
  page.on('requestfailed', r => errs.push('did not load: ' + r.url()));

  await page.goto(API + '/', {waitUntil: 'networkidle0'});
  await sleep(700);
  if (SHOTS) await page.screenshot({path: path.join(shotDir, '1-list.png')});
  await firstScreen(page, 'song list', errs);

  const list = await page.evaluate(() => ({
    screen: [...document.querySelectorAll('.screen')].filter(s => !s.classList.contains('hide'))
                .map(s => s.id),
    cards: document.querySelectorAll('.card').length,
    addVisible: !!document.getElementById('btnAdd')?.offsetParent,
  }));
  ok('exactly one screen is open', list.screen.length === 1, list.screen.join(', '));
  ok('it is the list of songs', list.screen[0] === 'scrList', list.screen[0]);
  ok('the “Add a song” button is in plain sight', list.addVisible);
  ok('the song is in the list', list.cards >= 1, 'cards ' + list.cards);

  /* ---- the add-a-song screen ---- */
  console.log('\n=== the add-a-song screen ===');
  await page.click('#btnAdd'); await sleep(400);
  if (SHOTS) await page.screenshot({path: path.join(shotDir, '2-add.png')});
  await firstScreen(page, 'add a song', errs);
  const add = await page.evaluate(() => ({
    model: document.getElementById('selModel').selectedOptions[0].textContent,
    note: document.getElementById('modelNote').textContent.trim(),
    noteVisible: !!document.getElementById('modelNote').offsetParent,
    warn: document.getElementById('newWarn').textContent.trim(),
  }));
  // ui.js keeps caps in a module-scope binding, so we ask the server instead.
  add.whisper = !!(await page.evaluate(async () =>
    ((await (await fetch('/api/state')).json()).caps || {}).whisper));
  ok('the model shows a note about downloading', /уже скачана|скачается/.test(add.model), add.model);
  // Without stable-ts there is nothing to say about a model download — the
  // window switches to timing by loudness and explains that instead.
  ok('the hint under the picker is shown',
     add.whisper ? (add.noteVisible && add.note.length > 10) : add.warn.length > 10,
     (add.note || add.warn).slice(0, 50));

  /* ---- the editor ---- */
  console.log('\n=== the editor: the main working screen ===');
  await page.click('#btnBackNew'); await sleep(400);
  await page.click('.card'); await sleep(2500);
  if (SHOTS) await page.screenshot({path: path.join(shotDir, '3-editor.png')});
  await firstScreen(page, 'editor', errs);

  const ed = await page.evaluate(() => {
    const vis = s => { const e = document.querySelector(s);
      return !!(e && e.offsetParent && e.getBoundingClientRect().height > 0); };
    const wave = document.getElementById('wave');
    const cur = document.querySelector('#scroll .ln');
    return {
      stage: document.querySelectorAll('#scroll .ln').length,
      blocks: document.querySelectorAll('.blk').length,
      waveShown: wave.getBoundingClientRect().height > 20,
      waveDrawn: (() => { const c = wave.getContext('2d');
        const d = c.getImageData(0, 0, wave.width, Math.max(1, wave.height)).data;
        let ink = 0; for (let i = 3; i < d.length; i += 4) if (d[i] > 8) ink++;
        return ink > 200; })(),
      lineSize: cur ? parseFloat(getComputedStyle(cur).fontSize) : 0,
      timeline: vis('.timeline'), side: vis('.side'), howto: vis('.howto'),
      saved: document.getElementById('savedNote').textContent.trim(),
      savedShown: parseFloat(getComputedStyle(document.getElementById('savedNote')).opacity),
      words: document.querySelectorAll('.wrd').length,
      title: document.getElementById('edTitle').textContent.trim(),
    };
  });
  ok('the lyrics are on stage', ed.stage >= 3, ed.stage + ' lines');
  ok('the song title is in the header', ed.title.length > 0, ed.title);
  ok('there are blocks on the timeline', ed.blocks === ed.stage, `${ed.blocks} against ${ed.stage}`);
  ok('the timeline is visible', ed.timeline && ed.waveShown);
  ok('the voice waveform is actually drawn', ed.waveDrawn);
  ok('the “Check” panel is visible', ed.side);
  ok('the hint about the order of work is visible', ed.howto);
  ok('the line is readable: at least 18px', ed.lineSize >= 18, ed.lineSize + 'px');
  ok('the save state is visible right away', ed.savedShown > 0.5 && ed.saved.length > 0,
     `“${ed.saved}”, opacity ${ed.savedShown}`);
  ok('before a line is picked there is no word row', ed.words === 0, ed.words + ' chips');
  await stageText(page, 'editor', {stage: '.stage', line: '#scroll .ln'});

  /* ---- picking a line: the word row shows up ---- */
  console.log('\n=== picking a line and the word row ===');
  await page.evaluate(() => document.querySelectorAll('#scroll .ln')[2].click());
  await sleep(600);
  if (SHOTS) await page.screenshot({path: path.join(shotDir, '4-words.png')});
  const wr = await page.evaluate(() => {
    const chips = [...document.querySelectorAll('.wrd')];
    const wrap = document.getElementById('tlwrap').getBoundingClientRect();
    const blk = document.querySelector('.blk.sel')?.getBoundingClientRect();
    return {
      n: chips.length,
      inside: chips.every(c => { const b = c.getBoundingClientRect();
        return b.top >= wrap.top - 1 && b.bottom <= wrap.bottom + 1; }),
      overlapBlocks: blk ? chips.some(c => {
        const b = c.getBoundingClientRect();
        return b.top < blk.bottom - 2 && b.bottom > blk.top + 2; }) : false,
      ordered: chips.every((c, i) => i === 0 ||
        c.getBoundingClientRect().left >= chips[i-1].getBoundingClientRect().left - 1),
      readable: chips.every(c => c.getBoundingClientRect().height >= 8),
      note: document.getElementById('selNote').textContent.trim(),
    };
  });
  ok('the words of the selected line are shown', wr.n >= 2, wr.n + ' words');
  ok('the word row is inside the timeline, not past its edges', wr.inside);
  ok('the row does not overlap the line blocks', !wr.overlapBlocks);
  ok('the words go left to right', wr.ordered);
  ok('the chips are of a visible size', wr.readable);
  ok('the caption shows the selected line', /строка \d/.test(wr.note), wr.note);

  /* ---- the sound really starts ---- */
  console.log('\n=== the sound ===');
  await page.click('#btnPlay'); await sleep(1200);
  const snd = await page.evaluate(() => {
    const t = document.getElementById('tCur')?.textContent || '';
    return {t, head: document.getElementById('phead')?.getBoundingClientRect().left};
  });
  await sleep(1200);
  const snd2 = await page.evaluate(() => (document.getElementById('tCur')||{}).textContent || '');
  ok('time runs, the song plays', snd.t !== snd2, `${snd.t} → ${snd2}`);
  await page.click('#btnPlay'); await sleep(300);

  /* ---- a narrow window: a laptop, not a monitor ---- */
  console.log('\n=== a narrow window, 1024×640 ===');
  await page.setViewport({width: 1024, height: 640});
  await sleep(700);
  if (SHOTS) await page.screenshot({path: path.join(shotDir, '5-narrow.png')});
  await firstScreen(page, 'narrow window', errs);
  const narrow = await page.evaluate(() => {
    const btns = [...document.querySelectorAll('.tlhead button')];
    return { hidden: btns.filter(b => b.getBoundingClientRect().width < 4).length,
             tl: document.querySelector('.timeline').getBoundingClientRect().height };
  });
  ok('the timeline buttons did not collapse', narrow.hidden === 0, narrow.hidden + ' collapsed');
  ok('the timeline was not eaten', narrow.tl > 80, narrow.tl.toFixed(0) + 'px');

  await page.close();

  /* ===================== 2. Отдельная страница ===================== */
  console.log('\n=== the standalone HTML page: what a person will see ===');
  page = await browser.newPage();
  await page.setViewport({width: 1280, height: 800});
  const errs2 = [];
  page.on('pageerror', e => errs2.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errs2.push(m.text()); });
  await page.goto('file://' + PAGE, {waitUntil: 'load'});
  await sleep(1500);
  if (SHOTS) await page.screenshot({path: path.join(shotDir, '6-page.png')});
  await firstScreen(page, 'page', errs2);

  const pl = await page.evaluate(() => {
    const vis = id => { const e = document.getElementById(id);
      return !!(e && e.offsetParent && getComputedStyle(e).display !== 'none'); };
    const cur = document.querySelector('.ln');
    return {
      lines: document.querySelectorAll('.ln').length,
      size: cur ? parseFloat(getComputedStyle(cur).fontSize) : 0,
      editorOpen: document.getElementById('editor').classList.contains('open'),
      editorShown: getComputedStyle(document.getElementById('editor')).display !== 'none',
      tapRow: vis('tapRow'),
      unpin: vis('btnUnpin'),
      toast: parseFloat(getComputedStyle(document.getElementById('toast')).opacity),
      playShown: vis('btnPlay'),
      title: document.querySelector('.meta h1').textContent.trim(),
    };
  });
  ok('the lyrics are in place', pl.lines >= 3, pl.lines + ' lines');
  ok('the title is in the header', pl.title.length > 0, pl.title);
  ok('the play button is visible', pl.playShown);
  ok('the stage type is large', pl.size >= 24, pl.size + 'px');
  ok('the editing panel stays closed until it is called', !pl.editorOpen && !pl.editorShown);
  ok('the tapping hint is not showing', !pl.tapRow);
  ok('the “not this one” button is not showing', !pl.unpin);
  ok('no tooltip is hanging on the screen', pl.toast < 0.1, 'opacity ' + pl.toast);
  await stageText(page, 'page', {stage: '.stage', line: '#scroll .ln'});

  console.log('\n--- opened the editing panel ---');
  await page.click('#btnEdit'); await sleep(500);
  if (SHOTS) await page.screenshot({path: path.join(shotDir, '7-editing.png')});
  await firstScreen(page, 'page with editing', errs2);
  const ep = await page.evaluate(() => {
    const rows = [...document.querySelectorAll('.editor .row')].filter(r => r.offsetParent);
    const btns = [...document.querySelectorAll('.editor button')].filter(b => b.offsetParent);
    return { rows: rows.length, btns: btns.length,
      tapRow: !!document.getElementById('tapRow').offsetParent,
      here: (document.getElementById('btnHere')||{}).textContent,
      save: (document.getElementById('btnSavePage')||{}).textContent,
      tgt: document.getElementById('tgtName').textContent.trim() };
  });
  ok('the editing panel opened', ep.rows >= 3, ep.rows + ' rows');
  ok('the tapping hint is still hidden', !ep.tapRow);
  ok('the main action is labelled', /Начало строки/.test(ep.here), ep.here);
  ok('the save button raises no false alarm',
     !/есть несохранённые/.test(ep.save), ep.save);
  ok('it is clear which line is being edited', ep.tgt !== '—' && ep.tgt.length > 2, ep.tgt);
  await stageText(page, 'page with editing', {stage: '.stage', line: '#scroll .ln'});

  console.log('\n--- opened a second time: nothing should pop up ---');
  await page.reload({waitUntil: 'load'});
  await sleep(1600);
  const again = await page.evaluate(() => ({
    toast: parseFloat(getComputedStyle(document.getElementById('toast')).opacity),
    text: document.getElementById('toast').textContent.trim(),
    stored: !!Object.keys(localStorage).find(k => k.startsWith('kar')),
    save: (document.getElementById('btnSavePage')||{}).textContent || '',
  }));
  ok('the page does not report edits that never happened', again.toast < 0.1,
     `“${again.text}”, opacity ${again.toast}`);
  ok('and does not declare itself unsaved', !/есть несохранённые/.test(again.save), again.save);
  await stageText(page, 'second opening', {stage: '.stage', line: '#scroll .ln'});

  console.log('\n--- a phone, 390×844 ---');
  await page.setViewport({width: 390, height: 844, isMobile: true});
  await sleep(700);
  if (SHOTS) await page.screenshot({path: path.join(shotDir, '8-phone.png')});
  await firstScreen(page, 'phone', errs2);
  const mob = await page.evaluate(() => {
    const cur = document.querySelector('.ln');
    return { size: cur ? parseFloat(getComputedStyle(cur).fontSize) : 0,
             play: !!document.getElementById('btnPlay').offsetParent,
             footH: document.querySelector('footer').getBoundingClientRect().height };
  });
  ok('the text stayed readable', mob.size >= 20, mob.size + 'px');
  ok('the play button is reachable', mob.play);
  ok('the bottom did not take the whole screen', mob.footH < 844 * 0.75, mob.footH.toFixed(0) + 'px');
  const cover = await page.evaluate(() => {
    const t = document.getElementById('toast').getBoundingClientRect();
    const p = document.getElementById('btnPlay').getBoundingClientRect();
    return !(t.bottom < p.top || t.top > p.bottom || t.right < p.left || t.left > p.right);
  });
  ok('the caption does not cover the play button', !cover);
  await stageText(page, 'phone', {stage: '.stage', line: '#scroll .ln'});

  await page.close();
} finally {
  await browser.close();
}

console.log(fail ? '\nFAILED: ' + fail : '\nAll checks passed');
process.exit(fail ? 1 : 0);
