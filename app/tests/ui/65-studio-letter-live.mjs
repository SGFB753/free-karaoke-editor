// Real editor: a held vowel stays one written word, including save and export.
import puppeteer from 'puppeteer';
const API=process.env.KARAOKE_API;
const state=await (await fetch(API+'/api/state')).json();
const pid=state.projects[0].id, route='/api/project/'+encodeURIComponent(pid);
const initial=await (await fetch(API+route)).json();
const fixture=initial.lines.slice(0,2).map((ln,i)=>({...ln,text:'Тут дну',start:2+i*6,end:3+i*6,
  lock:false,backing:false,voice:1,words:[{w:'Тут',t:2+i*6,d:.3,s:1},{w:'дну',t:2.4+i*6,d:.6,s:1}]}));
await fetch(API+route+'/timings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({lines:fixture,keepMarks:true})});
const browser=await puppeteer.launch({headless:'new',args:['--no-sandbox','--disable-dev-shm-usage']});
let failures=0;
try {
const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(String(e)));
await page.setViewport({width:1440,height:900});
const ok=(name,yes)=>{console.log((yes?'  ✓ ':'  ✗ ')+name);if(!yes)failures++;};
const read=()=>page.evaluate(async route=>(await (await fetch(route)).json()).lines,route);
const saved=async()=>{await page.waitForFunction(()=>document.getElementById('savedNote').classList.contains('ok'),{timeout:15000});};
await page.goto(API+'/',{waitUntil:'networkidle0'});await page.click('.card');
await page.waitForSelector('#scroll .ln');
await page.waitForFunction(()=>/[1-9]/.test(document.getElementById('tDur').textContent));
await page.evaluate(()=>document.querySelector('#scroll .ln').click());
await page.$eval('#mmap',el=>el.scrollIntoView({block:'center'}));
const spot=await page.$eval('#mmap',(el,duration)=>{const r=el.getBoundingClientRect();return{x:r.left+r.width*5.5/duration,y:r.top+r.height/2};},initial.duration);
await page.mouse.click(spot.x,spot.y);
await page.waitForSelector('#words .wrd');
await page.click('#words .wrd[data-j="1"]',{clickCount:2});
await page.waitForFunction(()=>!document.getElementById('letterDlg').classList.contains('hide'));
ok('double-click offers individual letters and selects the vowel',await page.$eval('#letterChoices',el=>
  [...el.children].map(b=>b.textContent).join('')==='дну' && el.querySelector('[aria-pressed="true"]').textContent==='у'));
ok('the playhead can be used as the vowel end',await page.$eval('#letterToCursor',el=>el.checked&&!el.disabled));
console.log('  playhead:',await page.$eval('#letterCursorLabel',el=>el.textContent));
await page.click('#letterApply');await saved();
let lines=await read();
ok('the written line stays unchanged',lines[0].text==='Тут дну');
ok('only the vowel carries the long timing',lines[0].words.length===3 && lines[0].words[1].w==='дн'
  && lines[0].words[2].w==='у' && lines[0].words[2].g===true && lines[0].words[1].d<.2
  && Math.abs(lines[0].words[2].t+lines[0].words[2].d-5.5)<.03);
ok('other words and lines were not moved',JSON.stringify(lines[0].words[0])===JSON.stringify(fixture[0].words[0])
  && JSON.stringify(lines[1].words)===JSON.stringify(fixture[1].words));
ok('preview keeps the letter parts together without an inserted space',await page.$eval('#scroll .ln .wgroup',el=>
  [...el.querySelectorAll('.w')].map(w=>w.lastChild.textContent).join('')==='дну'
  && getComputedStyle(el).whiteSpace==='nowrap'));
const savedTiming=JSON.stringify(lines);
for(let i=0;i<6;i++)await page.click('#btnZoomOut');
await new Promise(resolve=>setTimeout(resolve,150));
const zoomed=await page.evaluate(words=>{
  const k=document.querySelector('#tlwrap').clientWidth/parseFloat(document.querySelector('#zoomNote').textContent);
  const chips=[...document.querySelectorAll('#words .wrd')];
  const line=document.querySelector('.blk[data-i="0"]').getBoundingClientRect();
  return {errors:chips.map((chip,i)=>Math.abs(parseFloat(chip.style.left)-words[i].t*k)),
    end:chips.at(-1).getBoundingClientRect().right,lineEnd:line.right};
},lines[0].words);
ok('zoomed-out letter chips keep true timestamps and stay inside their line',
  zoomed.errors.every(error=>error<.05) && zoomed.end<=zoomed.lineEnd+2);
await page.click('#btnFit');
ok('zoom changes never rewrite letter timing',JSON.stringify(await read())===savedTiming);
const frames=await page.evaluate(async route=>{
  const hash=async t=>{
    const r=await fetch(route+'/still?at='+t),bytes=new Uint8Array(await r.arrayBuffer());
    return {ok:r.ok,size:bytes.length,hash:bytes.reduce((v,b)=>(Math.imul(v,31)+b)>>>0,0)};
  }; return [await hash(4),await hash(5)];
},route);
ok('the video renderer continues filling the vowel after the old word end',frames.every(f=>f.ok&&f.size>5000)&&frames[0].hash!==frames[1].hash);
await page.click('#btnUndo');await saved();lines=await read();
ok('one Undo restores the unsplit word and its duration',lines[0].words.length===2 && lines[0].words[1].d===.6);
await page.click('#btnRedo');await saved();
await page.reload({waitUntil:'networkidle0'});await page.click('.card');await page.waitForSelector('#scroll .ln');
await page.waitForFunction(()=>/[1-9]/.test(document.getElementById('tDur').textContent));
await page.evaluate(()=>document.querySelector('#scroll .ln').click());
await page.waitForSelector('#words .wrd');
ok('letter timing survives reopening the project',(await read())[0].words[2].g===true);
await page.evaluate(()=>{document.querySelector('#words .wrd[data-j="1"]').focus();});await page.keyboard.press('Enter');
await page.waitForFunction(()=>!document.getElementById('letterDlg').classList.contains('hide'));
ok('keyboard users can open the same control',await page.$eval('#letterChoices',el=>el.children.length===3));
await page.keyboard.press('Escape');
ok('Escape cancels without changing timing',Math.abs((await read())[0].words[2].d-2.98)<.03);
await page.$eval('#inlineLineText',el=>{el.value='Вот дну';el.dispatchEvent(new Event('input',{bubbles:true}));});
await page.click('#btnApplyLineText');await saved();lines=await read();
ok('editing another word preserves the held-letter layout',lines[0].text==='Вот дну' && lines[0].words.length===3
  && lines[0].words[2].w==='у' && lines[0].words[2].g===true && lines[0].words[2].d>2.9);
// Copy letter timing into an unsplit repeat, without requiring chip-count equality.
await page.$eval('#inlineLineText',el=>{el.value='Тут дну';el.dispatchEvent(new Event('input',{bubbles:true}));});
await page.click('#btnApplyLineText');await saved();await page.click('#btnRhythm');
await page.evaluate(()=>document.querySelectorAll('#scroll .ln')[1].click());
await page.click('#btnPaste');await saved();lines=await read();
ok('rhythm paste preserves letter timing on an unsplit repeat',lines[1].words.length===3 && lines[1].words[2].g===true
  && Math.abs(lines[1].words[2].d-lines[0].words[2].d)<.002);
ok('no JavaScript errors',errors.length===0);
} finally { await browser.close(); }
console.log(failures?`FAILED: ${failures}`:'All checks passed');process.exit(failures?1:0);
