const { JSDOM } = await import('jsdom');
import fs from 'fs';
const dom = new JSDOM(fs.readFileSync(process.env.KARAOKE_PAGE_MIX, 'utf8'), {
  runScripts:'dangerously', pretendToBeVisual:true, url:'https://local.test/',
  beforeParse(w){
    w.__inst=[];
    class FA{ constructor(){this.currentTime=0;this.paused=true;this.volume=1;this.duration=26;
      this._h={};w.__inst.push(this);setTimeout(()=>this._fire('loadedmetadata'),0);}
      addEventListener(n,f){(this._h[n]=this._h[n]||[]).push(f);} _fire(n){(this._h[n]||[]).forEach(f=>f());}
      play(){this.paused=false;this._fire('play');return Promise.resolve();} pause(){this.paused=true;this._fire('pause');}}
    w.Audio=FA; w.__errs=[]; w.onerror=m=>w.__errs.push(String(m));
  }});
const w=dom.window,doc=w.document,$=id=>doc.getElementById(id),sleep=ms=>new Promise(r=>setTimeout(r,ms));
w.URL.createObjectURL=()=>'blob:x'; w.URL.revokeObjectURL=()=>{};
let saved=null; w.Blob=class{constructor(p){saved=String(p[0]);}};
w.HTMLAnchorElement.prototype.click=function(){};
await sleep(200);
let fail=0; const ok=(n,c,e='')=>{console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c)fail++;};
const master=w.__inst[0];
const cur=()=>[...doc.querySelectorAll('.ln')].findIndex(e=>e.classList.contains('cur'));
const space=()=>doc.dispatchEvent(new w.KeyboardEvent('keydown',{key:' ',bubbles:true}));

// доводим песню до середины, чтобы проверить перемотку на начало
master.currentTime=12; await sleep(60);
ok('до тапов текст листается сам', cur()===3, 'строка '+(cur()+1));

$('btnTap').click(); await sleep(60);
ok('режим включился, перемотка на начало', master.currentTime===0, 't='+master.currentTime);
ok('проигрывание остановлено', master.paused);
ok('встали на первой строке', cur()===0, 'строка '+(cur()+1));
ok('счётчик показывает прогресс', /строка 1 из 6/.test($('btnTap').textContent), $('btnTap').textContent);
ok('подсказка по тапам появилась', !$('tapRow').classList.contains('hide'));

// ГЛАВНОЕ: время идёт, а текст стоять должен
master.currentTime=9; await sleep(80);
ok('текст НЕ уехал сам, хотя прошло 9 с', cur()===0, 'строка '+(cur()+1));

space(); await sleep(40);
ok('первый Пробел запускает песню, а не отмечает', !master.paused && cur()===0);

master.currentTime=3.0; await sleep(40); space(); await sleep(40);
ok('второй Пробел отметил строку 1 и перешёл на 2', cur()===1, 'строка '+(cur()+1));
master.currentTime=7.0; await sleep(40); space(); await sleep(40);
master.currentTime=11.0; await sleep(40); space(); await sleep(40);
ok('после трёх тапов стоим на строке 4', cur()===3, 'строка '+(cur()+1));
ok('счётчик обновился', /строка 4 из 6/.test($('btnTap').textContent), $('btnTap').textContent);

// между тапами время идёт — строка не должна меняться
master.currentTime=20; await sleep(80);
ok('и между тапами текст стоит', cur()===3, 'строка '+(cur()+1));

doc.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Backspace',bubbles:true})); await sleep(60);
ok('Backspace вернул на строку назад', cur()===2, 'строка '+(cur()+1));
ok('счётчик откатился', /строка 3 из 6/.test($('btnTap').textContent), $('btnTap').textContent);

// выбор строки, с которой продолжать отмечать
[...doc.querySelectorAll('.ln')][4].dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
await sleep(60);
ok('клик по строке в режиме тапов выбирает её', cur()===4, 'строка '+(cur()+1));
ok('счётчик перескочил', /строка 5 из 6/.test($('btnTap').textContent), $('btnTap').textContent);
ok('звук перемотался к этой строке', master.currentTime < 16.2, 't='+master.currentTime.toFixed(2));
master.currentTime=17.0; await sleep(40); space(); await sleep(40);
ok('отметка легла в выбранную строку', cur()===5, 'строка '+(cur()+1));

$('btnTap').click(); await sleep(60);
ok('режим выключен, подсказка скрыта', $('tapRow').classList.contains('hide'));
master.currentTime=12; await sleep(80);
ok('после выхода текст снова идёт по времени', cur()>=0);

$('btnSaveJson').click();
const j=JSON.parse(saved);
ok('отмеченные строки получили мои времена',
   Math.abs(j.lines[0].start-3.0)<0.01 && Math.abs(j.lines[1].start-7.0)<0.01,
   `${j.lines[0].start}, ${j.lines[1].start}`);
ok('ошибок JS нет', w.__errs.length===0, w.__errs.join(';'));
console.log(fail?`\nПРОВАЛЕНО: ${fail}`:'\nВсе проверки пройдены');
process.exit(fail?1:0);
