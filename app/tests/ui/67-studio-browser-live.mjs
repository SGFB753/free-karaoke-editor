// Automatic reserve uses the same fetch flow without browser-profile controls.
import puppeteer from 'puppeteer';
const API=process.env.KARAOKE_API;
const state=await (await fetch(API+'/api/state')).json();
const project=await (await fetch(API+'/api/project/'+encodeURIComponent(state.projects[0].id))).json();
let downloads=0,permissions=0,polls=0,failures=0;
const ok=(name,test)=>{console.log((test?'  ✓ ':'  ✗ ')+name);if(!test)failures++;};
const browser=await puppeteer.launch({headless:'new',args:['--no-sandbox','--disable-dev-shm-usage']});
try{
  const page=await browser.newPage();const errors=[];
  page.on('pageerror',e=>errors.push(String(e)));
  await page.setRequestInterception(true);
  page.on('request',r=>{
    const path=new URL(r.url()).pathname;
    const reply=body=>r.respond({status:200,contentType:'application/json',body:JSON.stringify(body)});
    if(path==='/api/state')return reply({...state,downloadBrowser:'edge'});
    if(path==='/api/fetch/browser'){permissions++;return reply({browser:'edge'});}
    if(path==='/api/fetch'){downloads++;polls=0;return reply({job:'download'+downloads});}
    if(path==='/api/job'){
      if(downloads===2)return reply({done:true,ok:false,error:'YouTube verification window was closed',cookiesRequired:true});
      if(++polls===1)return reply({done:false,log:['Trying Studio’s private YouTube session']});
      return reply({done:true,ok:true,result:{path:project.source_audio,name:'song.wav',title:'A song',duration:project.duration}});
    }
    if(path==='/api/lyrics/find')return reply({found:[
      {artist:'Bumble Beezy',title:'Стасис',lines:25,duration:171,source:'LRCLIB',timed:true,
       text:'Я погрузил тебя в стазис, подарил тебе саспенс — можешь звать меня Хичкок',
       textTimed:'[00:16.00] Я погрузил тебя в стазис'},
      {artist:'Очень длинное имя исполнителя',title:'Длинное название песни'.repeat(15),lines:28,source:'Genius',text:'Очень длинная строка текста '.repeat(40)}
    ]});
    return r.continue();
  });
  await page.setViewport({width:1017,height:1265});
  await page.goto(API+'/',{waitUntil:'networkidle0'});
  await page.click('#btnAdd');
  ok('manual browser controls are gone even with legacy preferences',await page.$('#fetchBrowserOptions')===null);
  await page.type('#inTitle','My title');
  await page.type('#inLink','https://youtu.be/abcdefghijk');
  await page.click('#btnFetch');
  await page.waitForFunction(()=>!!document.getElementById('inAudio').value);
  await page.waitForSelector('#lyricsFound .one');
  ok('one fetch click receives the reserve result',downloads===1&&permissions===0);
  ok('existing title survives',await page.$eval('#inTitle',e=>e.value==='My title'));
  for(const width of [2560,1920,1017,780,540,390]){
    await page.setViewport({width,height:1265});
    await new Promise(r=>setTimeout(r,150));
    ok('search cards and actions stay inside their panel at '+width,await page.evaluate(()=>{
      const panel=document.querySelector('#lyricsFound').parentElement.getBoundingClientRect();
      return [...document.querySelectorAll('#lyricsFound .one,#lyricsFound button')].every(e=>{
        const b=e.getBoundingClientRect();return b.left>=panel.left-1&&b.right<=panel.right+1;
      });
    }));
  }
  await page.setViewport({width:1017,height:1265});
  await page.click('#btnFetch');
  await page.waitForFunction(()=>!document.getElementById('btnFetch').disabled);
  ok('closed verification shows an error without obsolete controls',
    (await page.$eval('#linkNote',e=>e.textContent)).includes('closed')&&await page.$('#fetchBrowserOptions')===null);
  ok('no JavaScript errors',errors.length===0);
}finally{await browser.close();}
console.log(failures?`FAILED: ${failures}`:'All checks passed');
process.exit(failures?1:0);
