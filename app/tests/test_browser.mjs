// Настоящий браузер, а не jsdom: тот ничего не рисует, поэтому беды «при
// открытии» — съехавшая вёрстка, невидимая кнопка, лишняя полоса прокрутки,
// не тот размер шрифта — сквозь него проходят незамеченными.
//
// Что нужно один раз:
//   npm install puppeteer && npx puppeteer browsers install chrome
//
// Как гонять (студия должна быть запущена на 8770, рядом — собранная страница
// karaoke.html; путь к ней можно передать вторым способом ниже):
//   node tests/test_browser.mjs
//   node tests/test_browser.mjs --shots      ещё и снимки экрана в shots/
//   PAGE=/путь/к/песне_караоке.html node tests/test_browser.mjs
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

// Общие беды первого экрана, одинаковые для любой страницы.
async function firstScreen(page, name, errs){
  const r = await page.evaluate(() => {
    const el = document.documentElement;
    const over = [];
    // Элементы, вылезшие за правый край окна — самый заметный вид «хрени».
    // Обрезанные предком с overflow:hidden не считаются: дорожка времени
    // намеренно шире экрана, её блоки просто уезжают за край и клипятся.
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
    // текст, не поместившийся в свою коробку по вертикали
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
      // фон может быть и градиентом — тогда цвет прозрачный, а картинка есть
      bodyBg: getComputedStyle(document.body).backgroundColor,
      bodyImg: getComputedStyle(document.body).backgroundImage,
      title: document.title,
    };
  });
  ok(`${name}: нет боковой прокрутки`, !r.scrollX);
  ok(`${name}: ничего не вылезло за край окна`, r.over.length === 0, r.over.join(', '));
  ok(`${name}: подписи помещаются в кнопки`, r.clipped.length === 0, r.clipped.join(' | '));
  const painted = (r.bodyImg && r.bodyImg !== 'none') ||
                  (r.bodyBg !== 'rgba(0, 0, 0, 0)' && r.bodyBg !== 'rgb(255, 255, 255)');
  ok(`${name}: фон отрисован, а не белый по умолчанию`, painted,
     r.bodyBg + ' / ' + (r.bodyImg || '').slice(0, 40));
  ok(`${name}: ошибок в консоли нет`, errs.length === 0, errs.slice(0, 3).join(' | '));
  return r;
}


// Видно ли текст песни на сцене: не уехал ли он за края и близко ли к центру.
// Ровно это и ломалось — отступы в долях окна на сцене, которая ниже окна.
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
  ok(`${name}: текст песни видно на сцене`, r.seen >= 2,
     `видно ${r.seen} из ${r.total}, сцена ${r.h.toFixed(0)}px`);
  ok(`${name}: строка стоит близко к центру сцены`, r.nearest < r.h * 0.3,
     `до центра ${r.nearest.toFixed(0)}px при высоте ${r.h.toFixed(0)}px`);
  return r;
}

const browser = await puppeteer.launch({
  headless: 'new',
  args: ['--no-sandbox', '--disable-dev-shm-usage', '--autoplay-policy=no-user-gesture-required'],
});

try {
  /* ===================== 1. Студия ===================== */
  console.log('=== студия: как она открывается ===');
  let page = await browser.newPage();
  await page.setViewport({width: 1280, height: 800});
  const errs = [];
  page.on('pageerror', e => errs.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
  page.on('requestfailed', r => errs.push('не загрузилось: ' + r.url()));

  await page.goto(API + '/', {waitUntil: 'networkidle0'});
  await sleep(700);
  if (SHOTS) await page.screenshot({path: path.join(shotDir, '1-список.png')});
  await firstScreen(page, 'список песен', errs);

  const list = await page.evaluate(() => ({
    screen: [...document.querySelectorAll('.screen')].filter(s => !s.classList.contains('hide'))
                .map(s => s.id),
    cards: document.querySelectorAll('.card').length,
    addVisible: !!document.getElementById('btnAdd')?.offsetParent,
  }));
  ok('открыт ровно один экран', list.screen.length === 1, list.screen.join(', '));
  ok('это список песен', list.screen[0] === 'scrList', list.screen[0]);
  ok('кнопка «Добавить песню» на виду', list.addVisible);
  ok('песня в списке есть', list.cards >= 1, 'карточек ' + list.cards);

  /* ---- экран добавления ---- */
  console.log('\n=== экран добавления песни ===');
  await page.click('#btnAdd'); await sleep(400);
  if (SHOTS) await page.screenshot({path: path.join(shotDir, '2-добавление.png')});
  await firstScreen(page, 'добавление', errs);
  const add = await page.evaluate(() => ({
    model: document.getElementById('selModel').selectedOptions[0].textContent,
    note: document.getElementById('modelNote').textContent.trim(),
    noteVisible: !!document.getElementById('modelNote').offsetParent,
  }));
  ok('у модели видна пометка про загрузку', /уже скачана|скачается/.test(add.model), add.model);
  ok('подсказка под выбором показана', add.noteVisible && add.note.length > 10, add.note.slice(0, 50));

  /* ---- редактор ---- */
  console.log('\n=== редактор: главный экран работы ===');
  await page.click('#btnBackNew'); await sleep(400);
  await page.click('.card'); await sleep(2500);
  if (SHOTS) await page.screenshot({path: path.join(shotDir, '3-редактор.png')});
  await firstScreen(page, 'редактор', errs);

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
  ok('текст песни на сцене', ed.stage >= 3, ed.stage + ' строк');
  ok('название песни в шапке', ed.title.length > 0, ed.title);
  ok('блоки на дорожке', ed.blocks === ed.stage, `${ed.blocks} против ${ed.stage}`);
  ok('дорожка видна', ed.timeline && ed.waveShown);
  ok('волна голоса действительно нарисована', ed.waveDrawn);
  ok('панель «Проверить» видна', ed.side);
  ok('подсказка про порядок работы видна', ed.howto);
  ok('строка читается: кегль не меньше 18px', ed.lineSize >= 18, ed.lineSize + 'px');
  ok('состояние сохранения видно сразу', ed.savedShown > 0.5 && ed.saved.length > 0,
     `«${ed.saved}», прозрачность ${ed.savedShown}`);
  ok('до выбора строки ряда слов нет', ed.words === 0, ed.words + ' кусочков');
  await stageText(page, 'редактор', {stage: '.stage', line: '#scroll .ln'});

  /* ---- выбор строки: появляется ряд слов ---- */
  console.log('\n=== выбор строки и ряд слов ===');
  await page.evaluate(() => document.querySelectorAll('#scroll .ln')[2].click());
  await sleep(600);
  if (SHOTS) await page.screenshot({path: path.join(shotDir, '4-слова.png')});
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
  ok('слова выбранной строки показаны', wr.n >= 2, wr.n + ' слов');
  ok('ряд слов внутри дорожки, а не за её краями', wr.inside);
  ok('ряд не налезает на блоки строк', !wr.overlapBlocks);
  ok('слова идут слева направо', wr.ordered);
  ok('кусочки видимого размера', wr.readable);
  ok('подпись показывает выбранную строку', /строка \d/.test(wr.note), wr.note);

  /* ---- звук действительно заводится ---- */
  console.log('\n=== звук ===');
  await page.click('#btnPlay'); await sleep(1200);
  const snd = await page.evaluate(() => {
    const t = document.getElementById('tCur')?.textContent || '';
    return {t, head: document.getElementById('phead')?.getBoundingClientRect().left};
  });
  await sleep(1200);
  const snd2 = await page.evaluate(() => (document.getElementById('tCur')||{}).textContent || '');
  ok('время идёт, песня играет', snd.t !== snd2, `${snd.t} → ${snd2}`);
  await page.click('#btnPlay'); await sleep(300);

  /* ---- узкое окно: ноутбук, а не монитор ---- */
  console.log('\n=== узкое окно 1024×640 ===');
  await page.setViewport({width: 1024, height: 640});
  await sleep(700);
  if (SHOTS) await page.screenshot({path: path.join(shotDir, '5-узкое.png')});
  await firstScreen(page, 'узкое окно', errs);
  const narrow = await page.evaluate(() => {
    const btns = [...document.querySelectorAll('.tlhead button')];
    return { hidden: btns.filter(b => b.getBoundingClientRect().width < 4).length,
             tl: document.querySelector('.timeline').getBoundingClientRect().height };
  });
  ok('кнопки дорожки не схлопнулись', narrow.hidden === 0, narrow.hidden + ' схлопнутых');
  ok('дорожка не съелась', narrow.tl > 80, narrow.tl.toFixed(0) + 'px');

  await page.close();

  /* ===================== 2. Отдельная страница ===================== */
  console.log('\n=== отдельная HTML-страница: как её увидит человек ===');
  page = await browser.newPage();
  await page.setViewport({width: 1280, height: 800});
  const errs2 = [];
  page.on('pageerror', e => errs2.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errs2.push(m.text()); });
  await page.goto('file://' + PAGE, {waitUntil: 'load'});
  await sleep(1500);
  if (SHOTS) await page.screenshot({path: path.join(shotDir, '6-страница.png')});
  await firstScreen(page, 'страница', errs2);

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
  ok('текст песни на месте', pl.lines >= 3, pl.lines + ' строк');
  ok('название в шапке', pl.title.length > 0, pl.title);
  ok('кнопка воспроизведения видна', pl.playShown);
  ok('крупный кегль сцены', pl.size >= 24, pl.size + 'px');
  ok('панель правки закрыта, пока её не позвали', !pl.editorOpen && !pl.editorShown);
  ok('подсказки по тапам не видно', !pl.tapRow);
  ok('кнопки «не эту» не видно', !pl.unpin);
  ok('всплывающая подпись не висит на экране', pl.toast < 0.1, 'прозрачность ' + pl.toast);
  await stageText(page, 'страница', {stage: '.stage', line: '#scroll .ln'});

  console.log('\n--- открыли правку ---');
  await page.click('#btnEdit'); await sleep(500);
  if (SHOTS) await page.screenshot({path: path.join(shotDir, '7-правка.png')});
  await firstScreen(page, 'страница с правкой', errs2);
  const ep = await page.evaluate(() => {
    const rows = [...document.querySelectorAll('.editor .row')].filter(r => r.offsetParent);
    const btns = [...document.querySelectorAll('.editor button')].filter(b => b.offsetParent);
    return { rows: rows.length, btns: btns.length,
      tapRow: !!document.getElementById('tapRow').offsetParent,
      here: (document.getElementById('btnHere')||{}).textContent,
      save: (document.getElementById('btnSavePage')||{}).textContent,
      tgt: document.getElementById('tgtName').textContent.trim() };
  });
  ok('панель правки открылась', ep.rows >= 3, ep.rows + ' рядов');
  ok('подсказка по тапам по-прежнему спрятана', !ep.tapRow);
  ok('главное действие подписано', /Начало строки/.test(ep.here), ep.here);
  ok('кнопка сохранения без ложной тревоги',
     !/есть несохранённые/.test(ep.save), ep.save);
  ok('видно, какую строку правим', ep.tgt !== '—' && ep.tgt.length > 2, ep.tgt);
  await stageText(page, 'страница с правкой', {stage: '.stage', line: '#scroll .ln'});

  console.log('\n--- открыли второй раз: ничего не должно всплывать ---');
  await page.reload({waitUntil: 'load'});
  await sleep(1600);
  const again = await page.evaluate(() => ({
    toast: parseFloat(getComputedStyle(document.getElementById('toast')).opacity),
    text: document.getElementById('toast').textContent.trim(),
    stored: !!Object.keys(localStorage).find(k => k.startsWith('kar')),
    save: (document.getElementById('btnSavePage')||{}).textContent || '',
  }));
  ok('страница не сообщает о правках, которых не было', again.toast < 0.1,
     `«${again.text}», прозрачность ${again.toast}`);
  ok('и не объявляет себя несохранённой', !/есть несохранённые/.test(again.save), again.save);
  await stageText(page, 'второе открытие', {stage: '.stage', line: '#scroll .ln'});

  console.log('\n--- телефон 390×844 ---');
  await page.setViewport({width: 390, height: 844, isMobile: true});
  await sleep(700);
  if (SHOTS) await page.screenshot({path: path.join(shotDir, '8-телефон.png')});
  await firstScreen(page, 'телефон', errs2);
  const mob = await page.evaluate(() => {
    const cur = document.querySelector('.ln');
    return { size: cur ? parseFloat(getComputedStyle(cur).fontSize) : 0,
             play: !!document.getElementById('btnPlay').offsetParent,
             footH: document.querySelector('footer').getBoundingClientRect().height };
  });
  ok('текст остался читаемым', mob.size >= 20, mob.size + 'px');
  ok('кнопка воспроизведения доступна', mob.play);
  ok('низ не занял весь экран', mob.footH < 844 * 0.75, mob.footH.toFixed(0) + 'px');
  const cover = await page.evaluate(() => {
    const t = document.getElementById('toast').getBoundingClientRect();
    const p = document.getElementById('btnPlay').getBoundingClientRect();
    return !(t.bottom < p.top || t.top > p.bottom || t.right < p.left || t.left > p.right);
  });
  ok('подпись не накрывает кнопку пуска', !cover);
  await stageText(page, 'телефон', {stage: '.stage', line: '#scroll .ln'});

  await page.close();
} finally {
  await browser.close();
}

console.log(fail ? '\nFAILED: ' + fail : '\nAll checks passed');
process.exit(fail ? 1 : 0);
