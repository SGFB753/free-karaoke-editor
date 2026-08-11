// Язык надписей готовой страницы. Страница уезжает к людям, у которых родной
// язык может быть любым, поэтому английский — по умолчанию, русский — выбором.
const { JSDOM } = await import('jsdom');
import fs from 'fs';

let fail=0; const ok=(n,c,e='')=>{console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c)fail++;};
const sleep = ms => new Promise(r=>setTimeout(r,ms));

function open_(file, navLang){
  return new JSDOM(fs.readFileSync(file,'utf8'), {
    runScripts:'dangerously', pretendToBeVisual:true, url:'https://local.test/',
    beforeParse(w){
      w.__errs=[]; w.onerror=m=>w.__errs.push(String(m));
      Object.defineProperty(w.navigator, 'language', {get: () => navLang || 'en-US'});
      class FA{ constructor(){this.paused=true;this.volume=1;this.duration=26;
        this.playbackRate=1;this._t=0;this._h={};setTimeout(()=>this._fire('loadedmetadata'),0);}
        get currentTime(){return this._t;} set currentTime(v){this._t=v;this._fire('seeked');}
        addEventListener(n,f){(this._h[n]=this._h[n]||[]).push(f);} removeEventListener(){}
        _fire(n){(this._h[n]||[]).slice().forEach(f=>f());}
        play(){this.paused=false;return Promise.resolve();} pause(){this.paused=true;}}
      w.Audio=FA;
    }});
}

console.log('--- страница, собранная по-английски ---');
{
  const d = open_(process.env.KARAOKE_PAGE_EN, 'ru-RU');   // язык браузера не должен мешать
  const w = d.window, doc = w.document, $ = id => doc.getElementById(id);
  await sleep(250);
  ok('в разметке заявлен английский', doc.documentElement.lang === 'en',
     doc.documentElement.lang);
  ok('кнопка правки по-английски', $('btnEdit').textContent.trim() === 'Edit',
     $('btnEdit').textContent);
  ok('главное действие переведено', /Line starts here/.test($('btnHere').textContent),
     $('btnHere').textContent);
  ok('сохранение переведено', /Save page/.test($('btnSavePage').textContent),
     $('btnSavePage').textContent);
  ok('подсказка про правку заполнена и на английском',
     /Line starts here/.test(doc.querySelector('[data-t="editHint"]').innerHTML),
     doc.querySelector('[data-t="editHint"]').textContent.slice(0,50));
  ok('подсказка по тапам тоже', /Tap along/.test($('tapHint').innerHTML),
     $('tapHint').textContent.slice(0,40));
  ok('всплывающие подписи переведены', /Line above/.test($('btnTgtPrev').title),
     $('btnTgtPrev').title);
  // Сам текст песни, разумеется, остаётся русским — это содержимое, а не
  // интерфейс. Смотрим только на органы управления: низ страницы и панель правки.
  // Строка песни попадает и в подпись цели, и в саму сцену — это содержимое,
  // а не интерфейс. Берём только те узлы, где текста песни быть не может.
  const chrome = [
    ...doc.querySelectorAll('footer button'),
    ...doc.querySelectorAll('.knobgrp'),
    ...doc.querySelectorAll('.editor .hint'),
    ...doc.querySelectorAll('.editor .chk'),
  ].map(e => e.textContent).join(' ');
  const rus = (chrome.match(/[а-яА-ЯёЁ][а-яА-ЯёЁ ]{2,30}/g) || []);
  ok('в органах управления русского нет', rus.length === 0, rus.slice(0,3).join(' | '));
  const titles = [...doc.querySelectorAll('[title]')].map(e => e.title).join(' ');
  ok('и во всплывающих подсказках тоже', !/[а-яА-ЯёЁ]{3}/.test(titles),
     (titles.match(/[а-яА-ЯёЁ][а-яА-ЯёЁ ]{2,30}/g)||[]).slice(0,2).join(' | '));
  ok('ошибок JS нет', w.__errs.length===0, w.__errs.slice(0,2).join(' | '));
}

console.log('\n--- страница, собранная по-русски ---');
{
  const d = open_(process.env.KARAOKE_PAGE_STEMS, 'en-US');
  const w = d.window, doc = w.document, $ = id => doc.getElementById(id);
  await sleep(250);
  ok('в разметке заявлен русский', doc.documentElement.lang === 'ru',
     doc.documentElement.lang);
  ok('надписи русские', $('btnEdit').textContent.trim() === 'Правка',
     $('btnEdit').textContent);
  ok('язык браузера не переспорил выбор при сборке',
     /Начало строки/.test($('btnHere').textContent), $('btnHere').textContent);
  ok('ошибок JS нет', w.__errs.length===0, w.__errs.slice(0,2).join(' | '));
}

console.log(fail ? '\nПРОВАЛЕНО: '+fail : '\nВсе проверки пройдены');
process.exit(fail?1:0);
