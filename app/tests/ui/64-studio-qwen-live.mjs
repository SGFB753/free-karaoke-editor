// Optional timing engine: discoverability, native popup contrast and honest status.
import puppeteer from 'puppeteer';
const API=process.env.KARAOKE_API;
const state=await (await fetch(API+'/api/state')).json();
let failures=0,installed=true,openedEngine='',rememberedEngine=null;
const ok=(name,condition)=>{console.log((condition?'  ✓ ':'  ✗ ')+name);if(!condition)failures++;};
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const browser=await puppeteer.launch({headless:'new',
  executablePath:process.env.PUPPETEER_EXECUTABLE_PATH||undefined,
  args:['--no-sandbox','--disable-dev-shm-usage']});
const page=await browser.newPage();const errors=[];
page.on('pageerror',error=>errors.push(String(error)));
await page.setViewport({width:1366,height:900});
await page.setRequestInterception(true);
page.on('request',request=>{
  const pathname=new URL(request.url()).pathname;
  if(pathname==='/api/state') return request.respond({status:200,contentType:'application/json',body:JSON.stringify({
    ...state,timingEngine:rememberedEngine,caps:{...state.caps,qwen:installed,qwenModel:true}})});
  if(pathname==='/api/preferences/timing'){
    rememberedEngine=JSON.parse(request.postData()||'{}').engine;
    return request.respond({status:200,contentType:'application/json',body:JSON.stringify({engine:rememberedEngine})});
  }
  if(pathname==='/api/models/open-folder'){
    openedEngine=JSON.parse(request.postData()||'{}').engine;
    return request.respond({status:200,contentType:'application/json',body:'{"ok":true}'});
  }
  return request.continue();
});
await page.goto(API+'/',{waitUntil:'networkidle0'});
await page.click('#btnAdd'); await sleep(200);
ok('Qwen is a visible timing choice, outside the advanced section',await page.$eval('#selAlign',el=>
  !el.closest('details') && [...el.options].some(o=>o.value==='qwen' && !o.disabled && /Qwen/.test(o.textContent))));
ok('native option backgrounds and text have readable contrast',await page.$eval('#selModel',el=>{
  const luminance=color=>{
    const rgb=color.match(/[\d.]+/g).slice(0,3).map(x=>Number(x)/255).map(x=>x<=.04045?x/12.92:((x+.055)/1.055)**2.4);
    return rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722;
  };
  return getComputedStyle(el).colorScheme==='dark' && [...el.options].every(o=>{
    const style=getComputedStyle(o),a=luminance(style.color),b=luminance(style.backgroundColor);
    return (Math.max(a,b)+.05)/(Math.min(a,b)+.05)>=4.5;
  });
}));
await page.select('#selAlign','qwen');await sleep(100);
ok('Qwen explains supplied lyrics, vocals and approximate RAM outside advanced controls',await page.evaluate(()=>{
  const explanation=document.getElementById('alignExplain'),memory=document.getElementById('qwenNote');
  return !explanation.closest('details') && explanation.getBoundingClientRect().height>0 &&
    /supplied lyrics|загруженный текст/.test(explanation.textContent) &&
    /6 GB of free RAM|6 ГБ свободной оперативной/.test(memory.textContent) &&
    /not a fixed minimum|не строгий минимум/.test(memory.textContent);
}));
ok('Qwen explains readiness and experimental status without opening advanced controls',await page.$eval('#qwenNote',el=>
  el.getBoundingClientRect().height>0 && !el.closest('details') && /Qwen3-ForcedAligner/.test(el.textContent)));
ok('Whisper models are hidden while Qwen is selected',await page.$eval('#selModel',el=>el.classList.contains('hide')));
await page.click('.build-advanced > summary');
await page.click('#btnModelFolder');await sleep(100);
ok('model folder opens the selected Qwen cache, not the Whisper folder',openedEngine==='qwen');
await page.select('#selAlign','auto');await sleep(100);
ok('switching back preserves the selected Whisper model',await page.$eval('#selModel',el=>
  !el.classList.contains('hide') && el.value==='small'));
installed=false;
await page.select('#selAlign','qwen');await sleep(100);
await page.reload({waitUntil:'networkidle0'});await page.click('#btnAdd');await sleep(200);
ok('unavailable saved Qwen uses an available engine without erasing the preference',
  rememberedEngine==='qwen' && await page.$eval('#selAlign',el=>el.value!=='qwen'));
installed=true;
await page.reload({waitUntil:'networkidle0'});await page.click('#btnAdd');await sleep(200);
ok('Qwen choice is restored after reloading the application',await page.$eval('#selAlign',el=>el.value==='qwen'));
await page.select('#selAlign','auto');await sleep(100);
await page.reload({waitUntil:'networkidle0'});await page.click('#btnAdd');await sleep(200);
ok('Whisper choice is restored after reloading the application',await page.$eval('#selAlign',el=>el.value==='auto'));
installed=false;
await page.reload({waitUntil:'networkidle0'});await page.click('#btnAdd');await sleep(200);
ok('a build without Qwen clearly disables the optional choice',await page.$eval('#selAlign',el=>{
  const q=[...el.options].find(o=>o.value==='qwen');return q.disabled && /not installed|не установлен/.test(q.textContent);
}));
ok('no JavaScript errors',errors.length===0);
await browser.close();
console.log(failures ? `FAILED: ${failures}` : 'All checks passed');
process.exit(failures?1:0);
