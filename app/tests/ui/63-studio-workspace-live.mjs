// The new shell is tested through actual controls, including inline text and undo.
import puppeteer from 'puppeteer';
import {useWorkspaceNavigation} from '../helpers/workspace-navigation.mjs';
import fs from 'node:fs';
import path from 'node:path';
const API=process.env.KARAOKE_API;
let failed=0;
const ok=(name, condition, extra='')=>{
  console.log((condition?'  ✓ ':'  ✗ ')+name+(extra?' — '+extra:'')); if(!condition)failed++;
};
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const browser=await puppeteer.launch({headless:'new',
  executablePath:process.env.PUPPETEER_EXECUTABLE_PATH || undefined,
  args:['--no-sandbox','--disable-dev-shm-usage']});
try {
const page=await browser.newPage(); useWorkspaceNavigation(page);
const errors=[]; page.on('pageerror',e=>errors.push(String(e)));
await page.setViewport({width:1440,height:960});
await page.goto(API+'/',{waitUntil:'networkidle0'});
await page.click('.card'); await page.waitForSelector('#scrEdit:not(.hide)');
await sleep(1000);
const id=(await (await fetch(API+'/api/state')).json()).projects[0].id;
const project=async()=>await (await fetch(API+'/api/project/'+encodeURIComponent(id))).json();
const before=(await project()).lines;
const index=2;
await page.click('#scroll .ln:nth-child('+(index+1)+')');
await sleep(200);
ok('selecting a line populates the visible editor',
  await page.$eval('#inlineLineText',(el,txt)=>!el.disabled && el.value===txt,before[index].text));
const corrected=before[index].text.replace(/^\S+/, 'Updated');
await page.$eval('#inlineLineText',(el,txt)=>{el.value=txt;el.dispatchEvent(new Event('input',{bubbles:true}));},corrected);
await page.click('#inlineLineText'); await page.keyboard.press('Enter'); await sleep(900);
let lines=(await project()).lines;
ok('Enter saves the text to the project',lines[index].text===corrected);
ok('line edges stay unchanged',lines[index].start===before[index].start && lines[index].end===before[index].end);
ok('word chips reflect the new words',await page.$eval('#words .wtx',el=>el.textContent==='Updated'));
await page.keyboard.down('Control'); await page.keyboard.press('z'); await page.keyboard.up('Control');
await sleep(900);
ok('undo restores the line and the inline field',(await project()).lines[index].text===before[index].text &&
  await page.$eval('#inlineLineText',(el,txt)=>el.value===txt,before[index].text));
await page.keyboard.down('Control'); await page.keyboard.down('Shift');
await page.keyboard.press('z'); await page.keyboard.up('Shift'); await page.keyboard.up('Control');
await sleep(900);
ok('redo works without leaving the text editor',(await project()).lines[index].text===corrected);
await page.click('#btnUndo'); await sleep(900);
await page.$eval('#inlineLineText',el=>{el.value='Do not save this';el.dispatchEvent(new Event('input',{bubbles:true}));});
await page.click('#inlineLineText'); await page.keyboard.press('Escape'); await sleep(200);
ok('Escape cancels the draft without touching the project',await page.$eval('#inlineLineText',
  (el,txt)=>el.value===txt,before[index].text));
await page.$eval('#inlineLineText',el=>{el.value='Leaving saves the correct line';el.dispatchEvent(new Event('input',{bubbles:true}));});
await page.click('#inlineLineText');
await page.click('#scroll .ln:nth-child('+(index+2)+')'); await sleep(900);
lines=(await project()).lines;
ok('switching lines saves to the previous line, never the next',
  lines[index].text==='Leaving saves the correct line' && lines[index+1].text===before[index+1].text);
await page.click('#btnUndo'); await sleep(900);
await page.click('#btnWorkspaceLook'); await sleep(100);
ok('the prominent appearance button opens real settings',await page.$eval('#inspector-look',el=>!el.classList.contains('hide')));
ok('timeline commands remain available while styling',await page.$eval('#btnRhythm',el=>el.getBoundingClientRect().height>=30));
await page.click('#btnWorkspaceProject');
ok('project settings are reachable directly',await page.$eval('#inspector-project',el=>!el.classList.contains('hide')));
await page.click('#btnWorkspaceClose');
ok('return restores the same selected line and text',await page.$eval('#inlineLineText',
  (el,txt)=>el.value===txt,before[index+1].text));
await page.click('#btnLock'); await sleep(200);
ok('locked lyrics cannot be silently edited',await page.$eval('#inlineLineText',el=>el.disabled));
await page.click('#btnLock'); await sleep(200);
ok('unlock enables the editor again',await page.$eval('#inlineLineText',el=>!el.disabled));
await page.setViewport({width:1920,height:1080}); await sleep(2600);
await page.evaluate(()=>{document.querySelector('.timeline-commandbar').scrollLeft=0;document.querySelector('.side').scrollTop=0;});
if(process.env.KARAOKE_DESIGN_PREVIEW_DIR){
  fs.mkdirSync(process.env.KARAOKE_DESIGN_PREVIEW_DIR,{recursive:true});
  await page.screenshot({path:path.join(process.env.KARAOKE_DESIGN_PREVIEW_DIR,'05-editor-working.png')});
}
await page.setViewport({width:2560,height:1440}); await sleep(300);
const large=await page.evaluate(()=>{
  const size=sel=>parseFloat(getComputedStyle(document.querySelector(sel)).fontSize);
  const box=sel=>document.querySelector(sel).getBoundingClientRect();
  return {lyrics:size('.ln'),button:size('#btnRhythm'),editor:size('#inlineLineText'),
    label:size('.editor-label'),sidebar:box('.side').width,
    preview:box('.stagewrap').height,timeline:box('.tlwrap').height,
    footerBottom:box('footer').bottom};
});
ok('QHD text and controls are readable without zooming',large.lyrics>=40 &&
  large.button>=16 && large.editor>=17 && large.label>=15,JSON.stringify(large));
ok('larger text leaves the preview, timeline and transport visible',large.preview>300 &&
  large.timeline>70 && large.sidebar>=390 && large.footerBottom<=1441);
const groupSpace=await page.evaluate(()=>[...document.querySelectorAll('.command-group')].map(group=>{
  const right=Math.max(...[...group.querySelectorAll('button')].map(el=>el.getBoundingClientRect().right));
  return group.getBoundingClientRect().right-right;
}));
ok('QHD command groups hug their buttons instead of stretching into empty columns',
  groupSpace.every(space=>space<=24),JSON.stringify(groupSpace));
const edgeSpace=await page.evaluate(()=>{
  const bar=document.querySelector('.timeline-commandbar').getBoundingClientRect();
  const groups=[...document.querySelectorAll('.command-group')].map(el=>el.getBoundingClientRect());
  return {left:groups[0].left-bar.left,right:bar.right-groups.at(-1).right,
    gaps:groups.slice(1).map((group,i)=>group.left-groups[i].right),
    sameRow:groups.every(group=>Math.abs(group.top-groups[0].top)<1)};
});
ok('QHD command groups use the panel width through its right edge',
  edgeSpace.sameRow && edgeSpace.left<=1 && edgeSpace.right<=1,JSON.stringify(edgeSpace));
ok('QHD leaves only small consistent gaps between command groups',
  edgeSpace.gaps.every(gap=>gap>=0 && gap<=16),JSON.stringify(edgeSpace.gaps));
if(process.env.KARAOKE_DESIGN_PREVIEW_DIR)await page.screenshot({
  path:path.join(process.env.KARAOKE_DESIGN_PREVIEW_DIR,'06-editor-qhd.png')});
await page.setViewport({width:3840,height:2160}); await sleep(300);
const ultra=await page.evaluate(()=>({
  button:parseFloat(getComputedStyle(document.querySelector('#btnRhythm')).fontSize),
  lyrics:parseFloat(getComputedStyle(document.querySelector('.ln')).fontSize),
  side:document.querySelector('.side').getBoundingClientRect().width
}));
ok('4K does not inflate controls further',ultra.button<=18 && ultra.lyrics<=46 &&
  ultra.side<=410,JSON.stringify(ultra));
for(const viewport of [{width:1920,height:1000},{width:1366,height:768},
  {width:1250,height:820},{width:1024,height:700}]){
  await page.setViewport(viewport); await sleep(250);
  const layout=await page.evaluate(()=>{
    const bar=document.querySelector('.timeline-commandbar');
    const bounds=bar.getBoundingClientRect();
    const buttons=[...bar.querySelectorAll('button')].map(el=>el.getBoundingClientRect());
    return {overflow:bar.scrollWidth-bar.clientWidth,
      visible:buttons.every(b=>b.left>=bounds.left-1 && b.right<=bounds.right+1 &&
        b.top>=bounds.top && b.bottom<=bounds.bottom+1),
      preview:document.querySelector('.stagewrap').getBoundingClientRect().height,
      footer:document.querySelector('footer').getBoundingClientRect().bottom,
      lyrics:parseFloat(getComputedStyle(document.querySelector('.ln')).fontSize),
      button:parseFloat(getComputedStyle(document.querySelector('#btnRhythm')).fontSize),
      sidebar:document.querySelector('.side').getBoundingClientRect().width};
  });
  ok(`all commands fit at ${viewport.width}×${viewport.height} without horizontal scrolling`,
    layout.overflow<=1 && layout.visible,JSON.stringify(layout));
  ok('compact displays keep room for lyrics and transport',layout.preview>90 &&
    layout.footer<=viewport.height+1);
  if(viewport.width===1920){
    ok('Full HD keeps larger lyrics and readable commands',layout.lyrics>=38 && layout.button>=15);
    ok('QHD caps growth of controls, inspector and lyrics instead of scaling with resolution',
      large.button/layout.button<=1.13 && large.button/layout.button>=1 &&
      large.sidebar/layout.sidebar<=1.13 && large.lyrics/layout.lyrics<=1.13 &&
      large.button<=18 && large.lyrics<=46,
      JSON.stringify({qhd:large,fullHD:layout}));
    if(process.env.KARAOKE_DESIGN_PREVIEW_DIR)await page.screenshot({
      path:path.join(process.env.KARAOKE_DESIGN_PREVIEW_DIR,'07-editor-fullhd.png')});
  }
}
let undo=0; while(!(await page.$eval('#btnUndo',el=>el.disabled)) && undo++<30){
  await page.click('#btnUndo'); await sleep(100);
}
await sleep(900);
ok('the fixture returns to its original lyrics',JSON.stringify((await project()).lines)===JSON.stringify(before));
for(const viewport of [{width:800,height:600},{width:480,height:700},{width:360,height:640}]){
  await page.setViewport(viewport); await sleep(500);
  const narrow=await page.evaluate(()=>{
    const screen=document.querySelector('#scrEdit'),area=document.querySelector('.editing-area');
    const side=document.querySelector('.side').getBoundingClientRect(),workspace=area.getBoundingClientRect();
    const commands=document.querySelector('.timeline-commandbar');
    return {overflow:screen.scrollWidth-screen.clientWidth,scrollable:screen.scrollHeight>screen.clientHeight,
      stacked:side.top>=workspace.bottom-1,
      preview:document.querySelector('.stagewrap').getBoundingClientRect().height,
      commandsOverflow:commands.scrollWidth-commands.clientWidth};
  });
  ok(`narrow ${viewport.width}×${viewport.height} stacks properties and scrolls without shrinking lyrics`,
    narrow.overflow<=1 && narrow.scrollable && narrow.stacked && narrow.preview>=180 &&
    narrow.commandsOverflow<=1,JSON.stringify(narrow));
}
await page.setViewport({width:1250,height:820}); await sleep(500);
// A real countdown requires an intro of at least ten seconds. The regular
// fixture starts immediately, so give this private test project a 12s intro.
const intro={...before[0],start:before[0].start+12,end:before[0].end+12,
  words:before[0].words.map(word=>({...word,t:word.t+12}))};
await fetch(API+'/api/project/'+encodeURIComponent(id)+'/timings',{method:'POST',
  headers:{'Content-Type':'application/json'},body:JSON.stringify({lines:[intro],keepMarks:true})});
await page.reload({waitUntil:'networkidle0'});
await page.click('.card'); await page.waitForSelector('#wait:not(.hide)'); await sleep(700);
const countdown=await page.evaluate(()=>{
  const wait=document.querySelector('#wait'),stage=document.querySelector('#stage').getBoundingClientRect();
  const line=document.querySelector('.ln').getBoundingClientRect();
  return {visible:!wait.classList.contains('hide'),bottom:wait.getBoundingClientRect().bottom,
    stageTop:stage.top,lineTop:line.top,lineBottom:line.bottom};
});
ok('the countdown has its own space and does not cover the first lyric in a small window',
  countdown.visible && countdown.bottom<=countdown.stageTop+1 &&
  countdown.lineBottom>countdown.stageTop && countdown.lineTop>=countdown.bottom,
  JSON.stringify(countdown));
await fetch(API+'/api/project/'+encodeURIComponent(id)+'/timings',{method:'POST',
  headers:{'Content-Type':'application/json'},body:JSON.stringify({lines:before,keepMarks:true})});
ok('no browser errors',errors.length===0,errors.join(' | '));
} finally {
  await browser.close();
}
console.log(failed?'FAILED: '+failed:'All checks passed');
process.exit(failed?1:0);
