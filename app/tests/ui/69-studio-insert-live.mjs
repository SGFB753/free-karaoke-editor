// Insert before the first lyric using the actual timeline and browser focus.
import puppeteer from 'puppeteer';
const API=process.env.KARAOKE_API;
const state=await (await fetch(API+'/api/state')).json();
const id=state.projects[0].id;
const original=await (await fetch(API+'/api/project/'+encodeURIComponent(id))).json();
const baseline=original.lines.slice(0,3).map((line,i)=>{
  const start=[5,4,12][i],end=[8,6,14][i];
  return {...line,start,end,lock:i===0,backing:i===1,words:line.words.map((w,j)=>
    ({...w,t:start+(end-start)*j/line.words.length,d:(end-start)/line.words.length}))};
});
baseline[0].words[0].d=.02; // preserve a short syllable rather than a minimum pixel width
let saved={...original,lines:structuredClone(baseline)},failures=0;
const ok=(name,test)=>{console.log((test?'  ✓ ':'  ✗ ')+name);if(!test)failures++;};
const browser=await puppeteer.launch({headless:'new',
  executablePath:process.env.PUPPETEER_EXECUTABLE_PATH||undefined,
  args:['--no-sandbox','--disable-dev-shm-usage']});
try{
  const page=await browser.newPage();const errors=[];
  page.on('pageerror',e=>errors.push(String(e)));
  await page.setViewport({width:1366,height:900});
  await page.setRequestInterception(true);
  page.on('request',r=>{
    const path=new URL(r.url()).pathname;
    const reply=body=>r.respond({status:200,contentType:'application/json',body:JSON.stringify(body)});
    if(path==='/api/project/'+encodeURIComponent(id)+'/timings'){
      saved={...saved,...JSON.parse(r.postData())};return reply({problems:[]});
    }
    if(path==='/api/project/'+encodeURIComponent(id))return reply(saved);
    return r.continue();
  });
  async function open(){
    await page.goto(API+'/',{waitUntil:'networkidle0'});
    await page.click('.card');await page.waitForSelector('#scrEdit:not(.hide)');
    await page.waitForFunction(()=>document.getElementById('tDur').textContent!=='0:00');
  }
  async function insert(time,text){
    await page.$eval('#mmap',e=>e.scrollIntoView({block:'center'}));
    const rect=await page.$eval('#mmap',e=>{
      const r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height};
    });
    await page.mouse.click(rect.x+rect.w*time/saved.duration,rect.y+rect.h/2);
    await page.click('#btnAddLine');
    await page.waitForSelector('.lnedit');
    await page.type('.lnedit',text);await page.keyboard.press('Enter');
    await page.waitForFunction(text=>!document.querySelector('.lnedit')&&
      [...document.querySelectorAll('#scroll .hl')].map(e=>e.textContent).join('').includes(text),{},text);
    await new Promise(r=>setTimeout(r,650));
  }
  await open();
  await insert(1,'Opening');
  ok('timeline cursor inserts an opening before the original first line',
    saved.lines[0].text==='Opening'&&Math.abs(saved.lines[0].start-1)<.04);
  ok('locked lead and overlapping backing retain their order and timing',
    JSON.stringify(saved.lines.slice(1))===JSON.stringify(baseline));
  ok('preview and timeline number the opening first',await page.evaluate(()=>
    document.querySelector('#scroll .ln .hl')?.textContent.trim()==='Opening'&&
    document.querySelector('.blk[data-i="0"]')?.textContent.startsWith('1. Opening')));
  await open();
  ok('the opening remains first after reopening',await page.$eval('#scroll .ln .hl',e=>e.textContent.trim()==='Opening'));
  await insert(9,'Middle');
  ok('cursor inserts between existing phrases despite overlapping backing',
    saved.lines[3].text==='Middle'&&Math.abs(saved.lines[3].start-9)<.04&&saved.lines[4].start===12);
  ok('existing metadata and timing are still untouched',
    JSON.stringify(saved.lines.filter(l=>!['Opening','Middle'].includes(l.text)))===JSON.stringify(baseline));
  const beforePaste=structuredClone(saved.lines),source=beforePaste[1];
  await page.$eval('#scroll .ln:nth-child(2)',e=>e.click());
  await page.click('#btnRhythm');
  await page.$eval('#mmap',e=>e.scrollIntoView({block:'center'}));
  const rect=await page.$eval('#mmap',e=>{
    const r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height};
  });
  await page.mouse.click(rect.x+rect.w*.2/saved.duration,rect.y+rect.h/2);
  await page.click('#btnPasteLine');
  await new Promise(r=>setTimeout(r,700));
  const copy=saved.lines[0];
  ok('copy is pasted at the cursor, not after its selected source',
    copy.text===source.text&&Math.abs(copy.start-.2)<.04);
  ok('copy keeps full duration even though the next lyric is less than a second away',
    Math.abs((copy.end-copy.start)-(source.end-source.start))<.004);
  ok('all copied word durations, short syllables and pauses remain unchanged',
    copy.words.every((word,j)=>Math.abs(word.d-source.words[j].d)<.004&&
      Math.abs((word.t-copy.start)-(source.words[j].t-source.start))<.004));
  ok('pasting adds a copy without moving or replacing existing lines',
    JSON.stringify(saved.lines.slice(1))===JSON.stringify(beforePaste));
  ok('no JavaScript errors',errors.length===0);
}finally{await browser.close();}
console.log(failures?`FAILED: ${failures}`:'All checks passed');
process.exit(failures?1:0);
