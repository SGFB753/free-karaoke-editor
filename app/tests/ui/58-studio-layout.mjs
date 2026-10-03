// The window at many sizes: nothing overlaps anything, nothing runs off the
// edge, no control is squeezed into a sliver. Two layout bugs got out to a
// person before this existed — a caption printed over the colour swatches, and
// the side panel drawn across the toolbar — and both were invisible to every
// other check we had.
import puppeteer from 'puppeteer';
import { useWorkspaceNavigation } from '../helpers/workspace-navigation.mjs';
import fs from 'node:fs';
import path from 'node:path';

const API = process.env.KARAOKE_API;
let fail = 0;
const ok = (n, c, e='') => { console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c) fail++; };
const sleep = ms => new Promise(r=>setTimeout(r,ms));
async function preview(name){
  const directory = process.env.KARAOKE_DESIGN_PREVIEW_DIR;
  if (!directory) return;
  fs.mkdirSync(directory, {recursive:true});
  await p.screenshot({path:path.join(directory, name + '.png')});
}

const b = await puppeteer.launch({headless:'new',
  executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || undefined,
  args:['--no-sandbox','--disable-dev-shm-usage']});
const p = await b.newPage();
useWorkspaceNavigation(p);
const errs = []; p.on('pageerror', e => errs.push(String(e)));
p.on('dialog', d => d.dismiss());

// What a person actually resizes to: a laptop, a half-screen window, a small
// one. The last is deliberately cramped — that is where things used to break.
const SIZES = [[1600, 900], [1366, 820], [1180, 760], [1024, 700], [900, 640]];

async function overflows(){
  return p.evaluate(() => {
    const d = document.documentElement;
    return {page: d.scrollWidth - d.clientWidth,
            body: document.body.scrollWidth - d.clientWidth};
  });
}

// Two boxes in the same visual row must not lie on top of each other. Rows are
// found by their tops: a wrapped flex row starts a new one.
async function collisions(sel){
  return p.evaluate(container => {
    const box = document.querySelector(container);
    if (!box) return [];
    const kids = [...box.children].filter(e => {
      const s = getComputedStyle(e);
      const r = e.getBoundingClientRect();
      return s.display !== "none" && s.visibility !== "hidden" && r.width > 0 && r.height > 0;
    }).map(e => ({tag: (e.id || e.className || e.tagName).toString().slice(0, 24),
                  r: e.getBoundingClientRect()}));
    const bad = [];
    for (let i = 0; i < kids.length; i++)
      for (let j = i + 1; j < kids.length; j++){
        const a = kids[i].r, c = kids[j].r;
        const sameRow = Math.abs(a.top - c.top) < 4;
        const over = Math.min(a.right, c.right) - Math.max(a.left, c.left);
        if (sameRow && over > 1) bad.push(`${kids[i].tag} × ${kids[j].tag} (${over.toFixed(0)}px)`);
      }
    return bad;
  }, sel);
}

async function tinyControls(sel){
  return p.evaluate(container => {
    const box = document.querySelector(container);
    if (!box) return [];
    return [...box.querySelectorAll("button, input, select")].filter(e => {
      const s = getComputedStyle(e);
      if (s.display === "none" || s.visibility === "hidden") return false;
      // A tick box and a colour swatch are small by their nature — a dozen
      // pixels each is exactly what they are meant to be.
      if (e.type === "checkbox" || e.type === "color" || e.type === "radio") return false;
      const r = e.getBoundingClientRect();
      return r.width > 0 && (r.width < 16 || r.height < 12);
    }).map(e => `${e.id || e.textContent.trim().slice(0, 14)}: ` +
                `${Math.round(e.getBoundingClientRect().width)}×` +
                `${Math.round(e.getBoundingClientRect().height)}`);
  }, sel);
}

async function panelOverToolbar(){
  return p.evaluate(() => {
    const side = document.querySelector(".side");
    const tl = document.querySelector(".timeline");
    if (!side || !tl) return 0;
    const a = side.getBoundingClientRect(), c = tl.getBoundingClientRect();
    const w = Math.min(a.right, c.right) - Math.max(a.left, c.left);
    const h = Math.min(a.bottom, c.bottom) - Math.max(a.top, c.top);
    return (w > 1 && h > 1) ? Math.round(w * h) : 0;
  });
}

async function formCentering(){
  return p.evaluate(() => {
    const list = document.querySelector('.screen:not(.hide) .list');
    if (!list) return null;
    const form = list.querySelector('.form');
    const cards = list.querySelector('.cards');
    const container = form || cards;
    if (!container) return null;
    const viewportCenter = document.documentElement.clientWidth / 2;
    // Measure visible children, not the wrapper
    const children = [...container.children].filter(e => {
      const s = getComputedStyle(e);
      return s.display !== 'none' && s.visibility !== 'hidden' &&
             e.getBoundingClientRect().width > 0;
    });
    if (children.length === 0) return null;
    let minX = Infinity, maxX = -Infinity;
    for (const el of children) {
      const r = el.getBoundingClientRect();
      minX = Math.min(minX, r.left);
      maxX = Math.max(maxX, r.right);
    }
    const contentCenter = (minX + maxX) / 2;
    return Math.abs(contentCenter - viewportCenter);
  });
}

// Inside .field: do the children start at the same left edge as .field itself?
async function fieldInternals(){
  return p.evaluate(() => {
    const fields = document.querySelectorAll('.screen:not(.hide) .form .field');
    const issues = [];
    for (const field of fields) {
      const fr = field.getBoundingClientRect();
      const fieldCs = getComputedStyle(field);
      const label = (field.querySelector('label') || {}).textContent || '';
      const fieldLeft = fr.left + parseFloat(fieldCs.paddingLeft) + parseFloat(fieldCs.borderLeftWidth);
      for (const child of field.children) {
        const r = child.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) continue;
        const drift = Math.abs(r.left - fieldLeft);
        if (drift > 1) {
          issues.push(label.trim().slice(0,20) + ' child ' + (child.className || child.tagName).toString().slice(0,15) +
                     ': field.left=' + fieldLeft.toFixed(1) +
                     ' child.left=' + r.left.toFixed(1) +
                     ' drift=' + drift.toFixed(1));
        }
      }
    }
    return {issues, fieldCount: fields.length};
  });
}

await p.goto(API + '/', {waitUntil:'networkidle0'});
// Centring a partially clipped highlight centres its text in the narrow clip,
// not over the base word. Measure glyph positions, not just span rectangles.
const highlightOffsets = await p.evaluate(() => {
  const offsets = [];
  for (const kind of ['', 'back', 'v2', 'vboth']) {
    const line = document.createElement('div');
    line.className = 'ln cur ' + kind;
    line.style.width = '260px';
    document.body.appendChild(line);
    for (const text of ['Длинное слово ', 'следующее ']) {
      const word = document.createElement('span'); word.className = 'w';
      const hl = document.createElement('span'); hl.className = 'hl';
      hl.textContent = text;
      const base = document.createTextNode(text);
      word.append(hl, base); line.appendChild(word);
      for (const width of ['10%', '50%', '100%']) {
        hl.style.width = width;
        const a = document.createRange(), b = document.createRange();
        a.selectNodeContents(hl.firstChild); b.selectNodeContents(base);
        offsets.push(Math.abs(a.getBoundingClientRect().left - b.getBoundingClientRect().left));
      }
    }
    line.remove();
  }
  return offsets;
});
ok('partial highlighting stays aligned with the base words in every voice',
   highlightOffsets.every(x => x < .5), highlightOffsets.map(x => x.toFixed(1)).join(', '));
await sleep(600);

console.log('--- the list of songs ---');
const libraryProjects = (await (await fetch(API+'/api/state')).json()).projects;
const visibleProjectIds = await p.$$eval('#cards .card', els=>els.map(el=>el.dataset.id));
ok('the library keeps the server order, newest activity first',
   libraryProjects.every((project,i)=>i===0 || project.edited<=libraryProjects[i-1].edited) &&
   JSON.stringify(visibleProjectIds)===JSON.stringify(libraryProjects.map(project=>project.id)));
await p.setViewport({width:1366, height:820});
await preview('01-library');
ok('the running application version is visible',
   /^v\d+\.\d+\.\d+/.test(await p.$eval('#scrList .app-version', e=>e.textContent)));
for (const [w, h] of SIZES){
  await p.setViewport({width: w, height: h});
  await sleep(300);
  const o = await overflows();
  ok(`${w}×${h}: nothing runs off sideways`, o.page <= 1 && o.body <= 1, JSON.stringify(o));
  const center = await formCentering();
  ok(`${w}×${h}: the cards are centered in the viewport`, center !== null && center <= 1,
     center !== null ? `offset ${center.toFixed(1)}px` : 'elements not found');
  ok(`${w}×${h}: songs stay in one vertical list`,
     await p.$eval('#cards', el=>getComputedStyle(el).gridTemplateColumns.trim().split(/\s+/).length===1));
}

console.log('\n--- the screen for a new song ---');
await p.setViewport({width: 1366, height: 820});
await sleep(200);
await p.click('#btnAdd');
await sleep(300);
await preview('02-new-song');
ok('the player belongs to audio and metadata precedes lyrics', await p.evaluate(() => {
  const source = document.getElementById('inAudio').closest('.field');
  const metadata = document.getElementById('inTitle').closest('.field');
  const lyrics = document.getElementById('inLyrics').closest('.field');
  return source.contains(document.getElementById('newAudioPreview')) &&
    !!(metadata.compareDocumentPosition(lyrics) & Node.DOCUMENT_POSITION_FOLLOWING);
}));
ok('advanced controls preserve the existing build defaults', await p.evaluate(() =>
  document.getElementById('selModel').value === 'small' && document.getElementById('chkSep').checked &&
  document.getElementById('selModel').closest('details')?.classList.contains('build-advanced')));
await p.click('.build-advanced > summary');
for (const [w, h] of SIZES){
  await p.setViewport({width: w, height: h});
  await sleep(300);
  const o = await overflows();
  ok(`${w}×${h}: nothing runs off sideways`, o.page <= 1 && o.body <= 1, JSON.stringify(o));
  const clash = await collisions('.form .opts');
  ok(`${w}×${h}: the options do not lie on each other`, clash.length === 0, clash.join('; '));
  const tiny = await tinyControls('#scrNew');
  ok(`${w}×${h}: nothing is squeezed to a sliver`, tiny.length === 0, tiny.join('; '));
  const center = await formCentering();
  ok(`${w}×${h}: the form is centered in the viewport`, center !== null && center <= 1,
     center !== null ? `offset ${center.toFixed(1)}px` : 'elements not found');
  const fi = await fieldInternals();
  ok(`${w}×${h}: field children align to field left edge`,
     fi.issues.length === 0,
     fi.issues.length > 0 ? fi.issues.join('; ') : `${fi.fieldCount} fields OK`);
}

console.log('\n--- the editor, where both bugs happened ---');
await p.setViewport({width: 1366, height: 820});
await sleep(200);
await p.click('#btnBackNew');
await sleep(400);
await p.waitForSelector('.card', {timeout:20000});
await p.click('.card');
await p.waitForSelector('#scrEdit:not(.hide)', {timeout:20000});
await sleep(800);
await preview('03-editor-review');
const darkChrome = await p.evaluate(() => {
  const luminance = css => {
    const rgb = css.match(/[\d.]+/g).slice(0,3).map(Number).map(v => {
      const s=v/255; return s<=.04045 ? s/12.92 : ((s+.055)/1.055)**2.4;
    });
    return rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722;
  };
  return {
    surfaces:['#scrEdit','#scrEdit > header','.workspace-bar','.side','.timeline','#btnText','footer']
      .map(sel=>luminance(getComputedStyle(document.querySelector(sel)).backgroundColor)),
    captionContrast:(luminance(getComputedStyle(document.querySelector('.workspace-heading p')).color)+.05)/
      (luminance(getComputedStyle(document.querySelector('.workspace-bar')).backgroundColor)+.05)
  };
});
ok('editor surfaces keep the original low-brightness dark palette',
   darkChrome.surfaces.every(value=>value<.012), darkChrome.surfaces.map(value=>value.toFixed(3)).join(', '));
ok('secondary labels remain readable on the darker panels',darkChrome.captionContrast>=4.5,
   darkChrome.captionContrast.toFixed(1)+':1');
ok('the summary folds its actual contents, without placeholder text',
   await p.$eval('.review-summary', e => !!e.querySelector('#sum') && !/^null$/m.test(e.innerText)));
ok('command groups contain real controls without null placeholders',
   await p.$$eval('.command-buttons', els => els.length === 4 && els.every(el =>
     el.children.length > 0 && ![...el.childNodes].some(node => node.nodeType === 3 && node.textContent.trim()))));
ok('everyday edits are available without opening an inspector',
   await p.evaluate(() => ['btnAddLine','btnDelLine','btnSplit','btnJoin','btnRhythm','btnPasteLine','btnPaste'].every(id =>
     document.getElementById(id).closest('.tlhead') && document.getElementById(id).getBoundingClientRect().height > 0)));
for (const pane of ['line','look','project']){
  if (pane !== 'line') await p.click(pane === 'look' ? '#btnWorkspaceLook' : '#btnWorkspaceProject');
  ok(pane + ' section is available without hiding the timeline',
     await p.$eval('#inspector-' + pane, e=>!e.classList.contains('hide')) &&
     await p.$eval('#tlwrap', e=>e.getBoundingClientRect().height > 50));
  const clashes = await collisions('#inspector-' + pane + ' .inspector-controls');
  ok(pane + ' inspector controls do not overlap', clashes.length === 0, clashes.join('; '));
  await preview('04-editor-' + pane);
}
await p.click('#btnWorkspaceClose');

// Exercise the full transport layout as it appears with a separated vocal.
// The fixture can contain only a mix; this is a presentation check, not fake audio.
const voiceWasHidden = await p.$eval('#grpVoice', el=>el.classList.contains('hide'));
await p.$eval('#grpVoice', el=>el.classList.remove('hide'));
await p.$eval('#rVoice', el=>{el.value='42';el.dispatchEvent(new Event('input',{bubbles:true}));});
await p.hover('#rVoice');
async function wheelVoice(deltaY, shift=false){
  if (shift) await p.keyboard.down('Shift');
  try { await p.mouse.wheel({deltaY}); await sleep(100); }
  finally { if (shift) await p.keyboard.up('Shift'); }
  return p.$eval('#rVoice', el=>Number(el.value));
}
ok('wheel up raises vocal monitoring by 5%', await wheelVoice(-100) === 47);
ok('wheel down lowers vocal monitoring by 5%', await wheelVoice(100) === 42);
ok('Shift + wheel raises vocal monitoring by 1%', await wheelVoice(-100,true) === 43);
ok('Shift + wheel lowers vocal monitoring by 1%', await wheelVoice(100,true) === 42);
await p.$eval('#rVoice', el=>{el.value='99';el.dispatchEvent(new Event('input',{bubbles:true}));});
ok('wheel cannot raise vocal monitoring above 100%', await wheelVoice(-100) === 100);
await p.$eval('#rVoice', el=>{el.value='1';el.dispatchEvent(new Event('input',{bubbles:true}));});
ok('wheel cannot lower vocal monitoring below 0%', await wheelVoice(100) === 0);
ok('browser zoom and horizontal scrolling are not intercepted', await p.$eval('#rVoice', el=>{
  return [{deltaY:-100,ctrlKey:true},{deltaY:-100,metaKey:true},{deltaX:100,deltaY:1}].every(options=>{
    const event=new WheelEvent('wheel',{bubbles:true,cancelable:true,...options});
    el.dispatchEvent(event);
    return !event.defaultPrevented && el.value==='0';
  });
}));
await p.$eval('#rVoice', el=>{el.value='42';el.dispatchEvent(new Event('input',{bubbles:true}));});
await preview('06-editor-audio-controls');

for (const [w, h] of SIZES){
  await p.setViewport({width: w, height: h});
  await sleep(400);
  const o = await overflows();
  ok(`${w}×${h}: nothing runs off sideways`, o.page <= 1 && o.body <= 1, JSON.stringify(o));

  const head = await collisions('#scrEdit > header');
  ok(`${w}×${h}: the top bar does not lie on itself`, head.length === 0, head.join('; '));

  ok(`${w}×${h}: line properties and review coexist without tabs`,
     await p.evaluate(() => !document.querySelector('.inspector-tabs') &&
       ['inspector-line','inspector-check'].every(id=>!document.getElementById(id).closest('details') &&
         document.getElementById(id).getBoundingClientRect().height > 0)));
  const entry = await p.$$eval('.destination', els => els.map(el => {
    const r=el.getBoundingClientRect();
    return {width:r.width,height:r.height,font:parseFloat(getComputedStyle(el.querySelector('b')).fontSize),
      inside:r.left>=0 && r.right<=innerWidth && r.top>=0 && r.bottom<=innerHeight};
  }));
  ok(`${w}×${h}: appearance and project have prominent, readable entry points`,
    entry.length===2 && entry.every(e=>e.width>=140 && e.height>=50 && e.font>=14 && e.inside),
    JSON.stringify(entry));
  const labels = await p.$$eval('.command-buttons button', els=>els.map(el=>parseFloat(getComputedStyle(el).fontSize)));
  ok(`${w}×${h}: editing commands use readable labels`, labels.every(n=>n>=13));

  const tools = await collisions('.tlhead');
  ok(`${w}×${h}: the toolbar does not lie on itself`, tools.length === 0, tools.join('; '));

  const over = await panelOverToolbar();
  ok(`${w}×${h}: the side panel keeps off the timeline`, over === 0, over + 'px²');

  // the caption inside a swatch pair must not run into the swatches
  await p.click('#btnWorkspaceLook');
  const pick = await p.$$eval('.pick', els => els.map(el => {
    const b = el.querySelector('b'), i = el.querySelector('.sw');
    if (!b || !i) return 0;
    return b.getBoundingClientRect().right - i.getBoundingClientRect().left;
  }));
  ok(`${w}×${h}: the colour captions keep off the swatches`,
     pick.every(v => v <= 0.5), JSON.stringify(pick.map(v => Math.round(v))));
  await p.click('#btnWorkspaceClose');
  await p.evaluate(() => document.querySelector('.probs').scrollIntoView({block:'nearest'}));

  // The Check list must keep visible room whatever the summary holds: it used
  // to be squeezed to nothing and read as “the scrolling is broken”.
  const panel = await p.evaluate(() => {
    const probs = document.querySelector('.probs');
    const side = document.querySelector('.side');
    if (!probs || !side) return null;
    const a = probs.getBoundingClientRect(), b = side.getBoundingClientRect();
    return {h: a.height, inside: a.bottom <= b.bottom + 1 && a.top >= b.top - 1,
            scrollable: getComputedStyle(probs).overflowY};
  });
  ok(`${w}×${h}: the Check list keeps visible room`,
     panel && panel.h >= 40 && panel.inside, JSON.stringify(panel));
  ok(`${w}×${h}: and it is allowed to scroll`,
     panel && (panel.scrollable === 'auto' || panel.scrollable === 'scroll'),
     panel && panel.scrollable);

  const tiny = await tinyControls('#scrEdit');
  ok(`${w}×${h}: nothing is squeezed to a sliver`, tiny.length === 0, tiny.join('; '));
  const transport = await p.evaluate(()=>{
    const pitch=document.getElementById('grpPitch').getBoundingClientRect();
    const voice=document.getElementById('grpVoice').getBoundingClientRect();
    const slider=document.getElementById('rVoice').getBoundingClientRect();
    return {pitchTop:pitch.top,voiceTop:voice.top,pitchHeight:pitch.height,voiceHeight:voice.height,
      sliderWidth:slider.width,sliderHeight:slider.height};
  });
  ok(`${w}×${h}: vocal monitoring matches the key control and has a usable slider`,
    Math.abs(transport.pitchTop-transport.voiceTop)<1 &&
    Math.abs(transport.pitchHeight-transport.voiceHeight)<1 && transport.voiceHeight>=56 &&
    transport.sliderWidth>=128 && transport.sliderHeight>=32,JSON.stringify(transport));
}
await p.$eval('#grpVoice',(el,hidden)=>el.classList.toggle('hide',hidden),voiceWasHidden);

console.log('\n--- background survives entering and leaving a project ---');
await p.setViewport({width: 1366, height: 820});
await sleep(200);
// Go back to list
await p.evaluate(() => {
  const back = document.querySelector('#btnBack');
  if (back) back.click();
});
await sleep(500);
await p.waitForSelector('.card', {timeout:20000});
const bgBase = await p.evaluate(() => {
  const cs = getComputedStyle(document.body);
  return {
    background: cs.background,
    backgroundColor: cs.backgroundColor,
    backgroundImage: cs.backgroundImage,
  };
});
// The list screen must have a gradient, not a flat colour
ok('the list background is a gradient (not flat)',
   bgBase.backgroundImage.includes('linear-gradient'),
   `backgroundImage: ${bgBase.backgroundImage}`);
ok('the list background uses the default CSS values',
   bgBase.background.includes('10, 11, 20') && bgBase.background.includes('20, 24, 48'),
   `background: ${bgBase.background}`);
const bgBefore = bgBase;
await p.click('.card');
await p.waitForSelector('#scrEdit:not(.hide)', {timeout:20000});
await sleep(800);
await p.evaluate(() => {
  const back = document.querySelector('#btnBack');
  if (back) back.click();
});
await sleep(500);
await p.waitForSelector('#scrList:not(.hide)', {timeout:20000});
const bgAfter = await p.evaluate(() => {
  const cs = getComputedStyle(document.body);
  return {
    background: cs.background,
    backgroundColor: cs.backgroundColor,
    backgroundImage: cs.backgroundImage,
  };
});
ok('the background is the same after leaving the project',
   bgBefore.background === bgAfter.background,
   `before: ${bgBefore.backgroundColor} ${bgBefore.backgroundImage}, after: ${bgAfter.backgroundColor} ${bgAfter.backgroundImage}`);

ok('no errors in the browser console', errs.length === 0, errs[0] || '');
await b.close();
console.log(fail ? `\nFAILED: ${fail}` : '\nAll checks passed');
process.exit(fail ? 1 : 0);
