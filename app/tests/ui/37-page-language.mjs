// The language of the finished page. The page travels to people whose native
// tongue may be anything, so English is the default and Russian is a choice.
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

console.log('--- a page built in English ---');
{
  const d = open_(process.env.KARAOKE_PAGE_EN, 'ru-RU');   // the browser language must not interfere
  const w = d.window, doc = w.document, $ = id => doc.getElementById(id);
  await sleep(250);
  ok('the markup declares English', doc.documentElement.lang === 'en',
     doc.documentElement.lang);
  ok('the edit button is in English', $('btnEdit').textContent.trim() === 'Edit',
     $('btnEdit').textContent);
  ok('the main action is translated', /Line starts here/.test($('btnHere').textContent),
     $('btnHere').textContent);
  ok('saving is translated', /Save page/.test($('btnSavePage').textContent),
     $('btnSavePage').textContent);
  ok('the editing hint is filled in and in English',
     /Line starts here/.test(doc.querySelector('[data-t="editHint"]').innerHTML),
     doc.querySelector('[data-t="editHint"]').textContent.slice(0,50));
  ok('the tapping hint too', /Tap along/.test($('tapHint').innerHTML),
     $('tapHint').textContent.slice(0,40));
  ok('the tooltips are translated', /Line above/.test($('btnTgtPrev').title),
     $('btnTgtPrev').title);
  // The lyrics themselves of course stay Russian — that is content, not the
  // interface. We look only at the controls: the bottom bar and the edit panel.
  // A line of the song lands both in the target caption and on the stage — content
  // again, not interface. We take only the nodes where lyrics cannot appear.
  const chrome = [
    ...doc.querySelectorAll('footer button'),
    ...doc.querySelectorAll('.knobgrp'),
    ...doc.querySelectorAll('.editor .hint'),
    ...doc.querySelectorAll('.editor .chk'),
  ].map(e => e.textContent).join(' ');
  const rus = (chrome.match(/[а-яА-ЯёЁ][а-яА-ЯёЁ ]{2,30}/g) || []);
  ok('there is no Russian left in the controls', rus.length === 0, rus.slice(0,3).join(' | '));
  const titles = [...doc.querySelectorAll('[title]')].map(e => e.title).join(' ');
  ok('nor in the tooltips', !/[а-яА-ЯёЁ]{3}/.test(titles),
     (titles.match(/[а-яА-ЯёЁ][а-яА-ЯёЁ ]{2,30}/g)||[]).slice(0,2).join(' | '));
  ok('no JS errors', w.__errs.length===0, w.__errs.slice(0,2).join(' | '));
}

console.log('\n--- a page built in Russian ---');
{
  const d = open_(process.env.KARAOKE_PAGE_STEMS, 'en-US');
  const w = d.window, doc = w.document, $ = id => doc.getElementById(id);
  await sleep(250);
  ok('the markup declares Russian', doc.documentElement.lang === 'ru',
     doc.documentElement.lang);
  ok('the labels are Russian', $('btnEdit').textContent.trim() === 'Правка',
     $('btnEdit').textContent);
  ok('the browser language did not override the build choice',
     /Начало строки/.test($('btnHere').textContent), $('btnHere').textContent);
  ok('no JS errors', w.__errs.length===0, w.__errs.slice(0,2).join(' | '));
}

console.log(fail ? '\nFAILED: '+fail : '\nAll checks passed');
process.exit(fail?1:0);
