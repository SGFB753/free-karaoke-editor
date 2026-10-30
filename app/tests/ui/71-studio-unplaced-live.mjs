// A truncated recording opens without silently losing its unmatched lyrics.
import puppeteer from 'puppeteer';
const API=process.env.KARAOKE_API;
const state=await(await fetch(API+'/api/state')).json();
const pid=state.projects[0].id, route='/api/project/'+encodeURIComponent(pid);
const original=await(await fetch(API+route)).json();
const text='A missing chorus\n<script>window.unplacedExecuted=true</script>';
let unplaced=text.split('\n').map((text,i)=>({text,line:96+i,reason:'unmatched-ending'}));
let timed=original.lines;
let failures=0;
const ok=(name,value)=>{console.log((value?'  ✓ ':'  ✗ ')+name);if(!value)failures++;};
const browser=await puppeteer.launch({headless:'new',args:['--no-sandbox','--disable-dev-shm-usage']});
try{
  const page=await browser.newPage(), errors=[];
  page.on('pageerror',e=>errors.push(String(e)));
  await page.setViewport({width:1366,height:900});
  await page.setRequestInterception(true);
  page.on('request',r=>{
    if(new URL(r.url()).pathname===route && r.method()==='GET')
      return r.respond({status:200,contentType:'application/json',body:JSON.stringify({...original,lines:timed,problems:[],unplacedLyrics:unplaced})});
    if(new URL(r.url()).pathname===route+'/timings')
      return r.respond({status:200,contentType:'application/json',body:'{"problems":[]}'});
    return r.continue();
  });
  const open=async()=>{
    await page.goto(API+'/',{waitUntil:'networkidle0'});
    await page.click('.card');await page.waitForSelector('#scrEdit:not(.hide)');
    await page.waitForFunction(()=>document.getElementById('tDur').textContent!=='0:00');
  };
  await open();
  ok('the project opens and displays an unmatched-text notice',await page.$eval('#unplacedLyrics',e=>!e.classList.contains('hide')&&e.querySelector('summary').textContent.includes('2')));
  ok('the notice does not claim that everything is correct',await page.$('.allgood')===null);
  await page.click('#unplacedLyrics summary');
  ok('all unmatched text remains selectable for copying',await page.$eval('#unplacedLyrics textarea',(e,text)=>e.value===text && e.readOnly && e.getBoundingClientRect().height>0,text));
  for(const target of ['#mmap','#tlwrap','.preview-caption > span']){
    await page.click('#unplacedLyrics textarea');
    await page.keyboard.down('Control');await page.keyboard.press('KeyA');await page.keyboard.up('Control');
    ok('text can still be selected for copying inside the field',await page.$eval('#unplacedLyrics textarea',e=>document.activeElement===e&&e.selectionEnd-e.selectionStart===e.value.length));
    await page.click(target);
    ok(`any outside press releases the text field: ${target}`,await page.$eval('#unplacedLyrics textarea',e=>document.activeElement!==e));
    await page.keyboard.press('Space');
    await page.waitForFunction(()=>document.getElementById('btnPlay').textContent==='⏸');
    ok('Space starts playback after leaving the text field',await page.$eval('#unplacedLyrics textarea',(e,text)=>e.value===text,text));
    await page.keyboard.press('Space');
    await page.waitForFunction(()=>document.getElementById('btnPlay').textContent==='▶');
  }
  ok('lyric markup is displayed as text',await page.evaluate(()=>!window.unplacedExecuted));
  ok('unmatched lines are absent from preview and timeline',await page.evaluate(()=>!document.querySelector('#scroll').textContent.includes('A missing chorus')&&!document.querySelector('#blocks').textContent.includes('A missing chorus')));
  await open();
  ok('the notice remains after reopening',await page.$eval('#unplacedLyrics',e=>!e.classList.contains('hide')));
  timed=[];unplaced=unplaced.map(ln=>({...ln,reason:'whisper-unavailable'}));await open();
  ok('a project without recovered timing opens with an honest Whisper warning',await page.$eval('#unplacedLyrics p',e=>e.textContent.includes('Whisper')) && await page.$('.allgood')===null);
  await page.click('#btnAddLine');await page.waitForSelector('.lnedit');
  await page.type('.lnedit','Manually timed lyric');await page.keyboard.press('Enter');
  ok('the draft supports adding and timing lyrics manually',await page.waitForFunction(()=>
    [...document.querySelectorAll('#scroll .hl')].map(e=>e.textContent).join('')==='Manually timed lyric'));
  unplaced=[];timed=original.lines;await open();
  ok('projects without unmatched text retain the ordinary review state',await page.$eval('#unplacedLyrics',e=>e.classList.contains('hide')) && await page.$('.allgood')!==null);
  ok('no JavaScript errors',!errors.length);
}finally{await browser.close();}
console.log(failures?`FAILED: ${failures}`:'All checks passed');process.exit(failures?1:0);
