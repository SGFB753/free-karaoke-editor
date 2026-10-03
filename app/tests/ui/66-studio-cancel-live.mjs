// UI cancellation uses deterministic waiting jobs; backend interruption is
// covered separately by test_jobcontrol, including HTTP and child processes.
import puppeteer from 'puppeteer';
import {useWorkspaceNavigation} from '../helpers/workspace-navigation.mjs';
const API=process.env.KARAOKE_API;
const state=await (await fetch(API+'/api/state')).json();
const id=state.projects[0].id;
const project=await (await fetch(API+'/api/project/'+encodeURIComponent(id))).json();
const before=JSON.stringify(project.lines);
let cancelled=false, failures=0, requests=0;
const ok=(name,test)=>{console.log((test?'  ✓ ':'  ✗ ')+name);if(!test)failures++;};
const browser=await puppeteer.launch({headless:'new',args:['--no-sandbox','--disable-dev-shm-usage']});
try{
  const page=await browser.newPage();useWorkspaceNavigation(page);
  await page.setViewport({width:1366,height:900});
  const errors=[];page.on('pageerror',e=>errors.push(String(e)));
  page.on('dialog',d=>d.accept());
  await page.setRequestInterception(true);
  page.on('request',r=>{
    const path=new URL(r.url()).pathname;
    const reply=body=>r.respond({status:200,contentType:'application/json',body:JSON.stringify(body)});
    if(path==='/api/new'||path.endsWith('/realign')){
      cancelled=false;requests++;return reply({job:'ui-cancel'});
    }
    if(path==='/api/job')return reply({id:'ui-cancel',done:cancelled,ok:false,
      cancellable:!cancelled,cancelled,log:['Waiting for cancellation']});
    if(path==='/api/job/cancel'){cancelled=true;return reply({accepted:true});}
    if(path==='/api/project/'+encodeURIComponent(id)&&r.method()==='GET')
      return reply({...project,quiet:[{start:0,end:5}]});
    return r.continue();
  });
  await page.goto(API+'/',{waitUntil:'networkidle0'});
  await page.click('#btnAdd');
  await page.evaluate(d=>{
    document.getElementById('inAudio').value=d.source_audio||'fixture.wav';
    document.getElementById('inLyrics').value=d.source_lyrics||'fixture.txt';
  },project);
  await page.click('#btnBuild');
  await page.waitForSelector('#scrJob:not(.hide) #btnJobCancel:not(.hide)');
  await page.click('#btnJobCancel');
  await page.waitForSelector('#scrNew:not(.hide)');
  ok('initial timing can be cancelled and returns to its options',requests===1);
  ok('source inputs survive cancellation',await page.$eval('#inLyrics',e=>!!e.value));
  await page.goto(API+'/',{waitUntil:'networkidle0'});
  await page.click('.card');
  await page.waitForSelector('#scrEdit:not(.hide)');
  await page.waitForSelector('.quiet-all');
  ok('mark-all button belongs to the summary, not an absolute header overlay',
    await page.$eval('.quiet-all',e=>getComputedStyle(e).position==='static'&&!!e.closest('.sum')));
  await page.click('#btnRealign');
  await page.waitForSelector('#scrJob:not(.hide) #btnJobCancel:not(.hide)');
  await page.click('#btnJobCancel');
  await page.waitForSelector('#scrEdit:not(.hide)');
  ok('re-timing cancellation returns to the existing editor',requests===2);
  const after=await (await fetch(API+'/api/project/'+encodeURIComponent(id))).json();
  ok('existing project timings remain unchanged',JSON.stringify(after.lines)===before);
  ok('no JavaScript errors',errors.length===0);
}finally{await browser.close();}
console.log(failures ? `FAILED: ${failures}` : 'All checks passed');
process.exit(failures?1:0);
