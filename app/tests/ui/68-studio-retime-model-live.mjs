// Real-browser model selection does not require rebuilding the project's audio.
import puppeteer from 'puppeteer';
import {useWorkspaceNavigation} from '../helpers/workspace-navigation.mjs';
const API=process.env.KARAOKE_API;
const state=await (await fetch(API+'/api/state')).json();
const id=state.projects[0].id;
const project=await (await fetch(API+'/api/project/'+encodeURIComponent(id))).json();
let saved={...project,engine:'qwen',model:'qwen3-forcedaligner-0.6b'},available=true;
let calls=[],cancelled=false,failures=0;
const ok=(name,test)=>{console.log((test?'  ✓ ':'  ✗ ')+name);if(!test)failures++;};
const browser=await puppeteer.launch({headless:'new',
  executablePath:process.env.PUPPETEER_EXECUTABLE_PATH||undefined,
  args:['--no-sandbox','--disable-dev-shm-usage']});
try{
  const page=await browser.newPage();useWorkspaceNavigation(page);
  const errors=[];page.on('pageerror',e=>errors.push(String(e)));
  await page.setViewport({width:1366,height:900});
  await page.setRequestInterception(true);
  page.on('request',r=>{
    const path=new URL(r.url()).pathname;
    const reply=body=>r.respond({status:200,contentType:'application/json',body:JSON.stringify(body)});
    if(path==='/api/state')return reply({...state,caps:{...state.caps,whisper:true,qwen:available,qwenModel:true}});
    if(path==='/api/project/'+encodeURIComponent(id)&&r.method()==='GET')return reply(saved);
    if(path.endsWith('/realign')){calls.push(JSON.parse(r.postData()));cancelled=false;return reply({job:'retime-model'});}
    if(path==='/api/job')return reply({id:'retime-model',done:cancelled,ok:false,
      cancellable:!cancelled,cancelled,log:['Waiting']});
    if(path==='/api/job/cancel'){cancelled=true;return reply({accepted:true});}
    return r.continue();
  });
  async function open(){
    await page.goto(API+'/',{waitUntil:'networkidle0'});
    await page.click('.card');
    await page.waitForSelector('#scrEdit:not(.hide)');
    await page.click('#btnRealign');
    await page.waitForSelector('#retimeDlg:not(.hide)');
  }
  await open();
  ok('project Qwen engine is selected by default',await page.$eval('#retimeEngine',e=>e.value==='qwen'));
  ok('Whisper model is hidden for Qwen',await page.$eval('#retimeModelRow',e=>e.classList.contains('hide')));
  await page.select('#retimeEngine','whisper');
  ok('Qwen-to-Whisper starts with a valid model, not the Qwen model name',await page.$eval('#retimeModel',e=>e.value==='small'));
  await page.select('#retimeModel','medium');
  await page.select('#retimeEngine','qwen');await page.select('#retimeEngine','whisper');
  ok('switching engines keeps the chosen Whisper size',await page.$eval('#retimeModel',e=>e.value==='medium'));
  await page.click('#retimeCancel');
  ok('cancel closes settings without starting a job',calls.length===0&&await page.$eval('#retimeDlg',e=>e.classList.contains('hide')));
  await page.click('#btnRealign');await page.keyboard.press('Escape');
  ok('Escape closes the settings and returns focus',await page.evaluate(()=>
    document.getElementById('retimeDlg').classList.contains('hide')&&document.activeElement.id==='btnRealign'));
  await page.click('#btnRealign');await page.select('#retimeEngine','whisper');await page.select('#retimeModel','large-v3');
  await page.click('#retimeGo');
  await page.waitForSelector('#scrJob:not(.hide) #btnJobCancel:not(.hide)');
  ok('explicit engine and model reach re-timing API',calls.length===1&&calls[0].align==='whisper'&&calls[0].model==='large-v3');
  await page.click('#btnJobCancel');await page.waitForSelector('#scrEdit:not(.hide)');
  saved={...project,engine:'whisper',model:'medium'};
  await open();
  ok('saved Whisper size is restored in the dialog',await page.$eval('#retimeModel',e=>e.value==='medium'));
  await page.select('#retimeEngine','qwen');await page.click('#retimeGo');
  await page.waitForSelector('#scrJob:not(.hide) #btnJobCancel:not(.hide)');
  ok('Whisper-to-Qwen explicitly sends the Qwen engine',calls.length===2&&calls[1].align==='qwen');
  await page.click('#btnJobCancel');await page.waitForSelector('#scrEdit:not(.hide)');
  saved={...project,engine:'qwen',model:'qwen3-forcedaligner-0.6b'};available=false;
  await open();
  ok('missing Qwen never silently runs another engine',await page.$eval('#retimeGo',e=>e.disabled));
  ok('missing dependencies do not hide available Whisper choice',await page.$eval('#retimeEngine',e=>!e.querySelector('[value="whisper"]').disabled));
  await page.setViewport({width:700,height:500});
  ok('dialog fits a small window',await page.$eval('.retimebox',e=>{
    const r=e.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight;
  }));
  ok('no JavaScript errors',errors.length===0);
}finally{await browser.close();}
console.log(failures?`FAILED: ${failures}`:'All checks passed');
process.exit(failures?1:0);
