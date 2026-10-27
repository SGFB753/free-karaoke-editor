// A held final syllable can be placed exactly at the playhead without re-laying a phrase.
import puppeteer from 'puppeteer';
const API=process.env.KARAOKE_API;
const state=await (await fetch(API+'/api/state')).json();
const pid=state.projects[0].id,route='/api/project/'+encodeURIComponent(pid);
const initial=await (await fetch(API+route)).json();
const fixture=initial.lines.slice(0,2).map((ln,i)=>({...ln,text:'Тут дну',start:2+i*6,end:3+i*6,
  lock:false,backing:false,voice:1,words:[{w:'Тут',t:2+i*6,d:.3,s:1},
    {w:'дн',t:2.4+i*6,d:.1,s:1},{w:'у',t:2.5+i*6,d:.5,s:1,g:true}]}));
const write=lines=>fetch(API+route+'/timings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({lines})});
await write(fixture);
const browser=await puppeteer.launch({headless:'new',args:['--no-sandbox','--disable-dev-shm-usage']});
let failures=0;
try {
  const page=await browser.newPage(),errors=[];page.on('pageerror',e=>errors.push(String(e)));
  const ok=(name,value)=>{console.log((value?'  ✓ ':'  ✗ ')+name);if(!value) failures++;};
  const read=()=>page.evaluate(async route=>(await(await fetch(route)).json()).lines,route);
  const saved=()=>page.waitForFunction(()=>document.getElementById('savedNote').classList.contains('ok'));
  const open=async()=>{await page.goto(API+'/',{waitUntil:'networkidle0'});await page.click('.card');await page.waitForFunction(()=>/[1-9]/.test(document.getElementById('tDur').textContent));};
  const cursor=async time=>{
    await page.$eval('#mmap',el=>el.scrollIntoView({block:'center'}));
    const point=await page.$eval('#mmap',(el,args)=>{const r=el.getBoundingClientRect();return{x:r.left+r.width*args.time/args.duration,y:r.top+r.height/2};},{time,duration:initial.duration});
    await page.mouse.click(point.x,point.y);
    // Earlier scenarios may replace the audio without changing project.duration.
    // Assert against the actual playhead clock, as the editor does.
    return page.evaluate(async()=>{
      await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
      return document.getElementById("tCur").textContent.trim().split(":").reduce((n,p)=>n*60+Number(p),0);
    });
  };
  await page.setViewport({width:1440,height:900});await open();
  await page.evaluate(()=>document.querySelector('#scroll .ln').click());
  const firstCursor=await cursor(5.5);
  await page.click('#btnEndHere');await saved();
  let lines=await read();
  const firstEnd=lines[0].end;
  ok('the line and held vowel reach the playhead',Math.abs(firstEnd-firstCursor)<.002 && Math.abs(lines[0].words[2].t+lines[0].words[2].d-firstEnd)<.002);
  ok('other words, letters and lines retain their exact timing',
    JSON.stringify(lines[0].words.slice(0,2))===JSON.stringify(fixture[0].words.slice(0,2)) &&
    JSON.stringify(lines[1])===JSON.stringify(fixture[1]));
  ok('the written word stays joined',lines[0].words[2].g===true && lines[0].text==='Тут дну');
  await page.click('#btnUndo');await saved();
  ok('one undo restores the previous word end',(await read())[0].end===3);
  await page.click('#btnRedo');await saved();
  ok('redo restores the held note',Math.abs((await read())[0].end-firstEnd)<.002);
  await page.$eval('#chkRest',el=>{el.checked=true;});
  const secondCursor=await cursor(6.5);await page.keyboard.down('Shift');await page.keyboard.press('Enter');await page.keyboard.up('Shift');await saved();
  lines=await read();
  ok('Shift+Enter sets only this line’s end even with “all following” checked',Math.abs(lines[0].end-secondCursor)<.002 && JSON.stringify(lines[1])===JSON.stringify(fixture[1]));
  const before=JSON.stringify(lines);
  await cursor(2.1);await page.click('#btnEndHere');
  ok('a cursor before the final letter cannot erase the phrase',JSON.stringify(await read())===before);
  await open();
  ok('the held end survives reopening',Math.abs((await read())[0].end-secondCursor)<.002);
  ok('no JavaScript errors',errors.length===0);
} finally {await browser.close();await write(initial.lines);}
console.log(failures?`FAILED: ${failures}`:'All checks passed');process.exit(failures?1:0);
