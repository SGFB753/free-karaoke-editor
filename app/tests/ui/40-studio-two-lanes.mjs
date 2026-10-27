// Overlapping vocals: a second-voice line moves to the second lane of the
// timeline and stays grabbable. A real browser — jsdom does not do layout.
import puppeteer from 'puppeteer';
import {useWorkspaceNavigation, revealTimeline} from '../helpers/workspace-navigation.mjs';

const API = process.env.KARAOKE_API;
let fail = 0;
const ok = (n, c, e='') => { console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c) fail++; };
const PID = (await (await fetch(API+'/api/state')).json()).projects[0].id;
const proj = async () => (await (await fetch(API+'/api/project/'+encodeURIComponent(PID))).json());
const sleep = ms => new Promise(r=>setTimeout(r,ms));

const b = await puppeteer.launch({headless:'new', args:['--no-sandbox','--disable-dev-shm-usage']});
const p = await b.newPage();
useWorkspaceNavigation(p);
await p.setViewport({width:1366, height:768});
const errs = []; p.on('pageerror', e => errs.push(String(e)));
await p.goto(API+'/', {waitUntil:'networkidle0'});
await sleep(600);
await p.click('.card');
await sleep(2500);

const lane = i => p.evaluate(k => {
  const e = document.querySelectorAll('#blocks .blk')[k];
  return e ? e.getBoundingClientRect().top : null;
}, i);
const wrapH = () => p.evaluate(() =>
  document.getElementById('tlwrap').getBoundingClientRect().height);

console.log('--- while there is no second voice ---');
const h0 = await wrapH();
const top0 = await lane(1);
ok('the timeline is a single lane', !(await p.evaluate(() =>
   document.getElementById('tlwrap').classList.contains('twolane'))));

console.log('\n--- giving a line the second voice ---');
await p.evaluate(() => document.querySelectorAll('#scroll .ln')[1].click());
await sleep(200);
await p.click('#btnVoice');
await sleep(400);

const h1 = await wrapH();
const top1 = await lane(1);
const topMain = await lane(0);
ok('the timeline got taller', h1 > h0, `${h0} → ${h1}`);
// The timeline grew and shifted the layout, so we compare the blocks with each
// other, not with their own former coordinates on screen.
ok('the second-voice block sits below the main ones', top1 > topMain + 20,
   `main ${topMain}, second ${top1}`);
ok('before the second voice the blocks ran in one lane', Math.abs(top0 - topMain) < 40,
   `${top0} vs ${topMain}`);

console.log('\n--- the second-voice block can still be grabbed with the mouse ---');
await revealTimeline(p);
const box = await p.evaluate(() => {
  const e = document.querySelectorAll('#blocks .blk')[1];
  const r = e.getBoundingClientRect();
  return {x: r.left + r.width/2, y: r.top + r.height/2};
});
const hit = await p.evaluate(({x,y}) => {
  const e = document.elementFromPoint(x, y);
  return !!(e && e.closest('.blk') === document.querySelectorAll('#blocks .blk')[1]);
}, box);
ok('that very block is under the cursor', hit);
const was = (await proj()).lines[1].start;
await p.mouse.move(box.x, box.y);
await p.mouse.down();
await p.mouse.move(box.x + 60, box.y, {steps: 8});
await p.mouse.up();
await sleep(900);
const now = (await proj()).lines[1].start;
ok('the second-voice line could be moved', now > was + 0.05,
   `${was.toFixed(2)} → ${now.toFixed(2)}`);

console.log('\n--- and the words of that line show under the timeline ---');
const wordsBelow = await p.evaluate(() => {
  const w = document.querySelector('#words .wrd');
  const blk = document.querySelectorAll('#blocks .blk')[1];
  if (!w || !blk) return null;
  return w.getBoundingClientRect().top - blk.getBoundingClientRect().bottom;
});
ok('the word row is below the second lane, not on top of it', wordsBelow !== null && wordsBelow > 0,
   String(wordsBelow));

// put it back so the stand stays clean for the neighbouring suites
await p.click('#btnVoice');
await sleep(200);
await p.evaluate(t => {
  const b = document.querySelectorAll('#blocks .blk')[1];
  b.click();
}, 0);
await sleep(600);

console.log('\n--- a backing sung by voice 1 has an independent lower lane ---');
const original = await proj();
const fixture = original.lines.slice(0,3).map((line,i) => ({...line,
  text:['Main','Backing','Other'][i], backing:i===1, voice:1,lock:false,
  start:[1,4,9][i],end:[8,6,12][i],
  words:[{w:['Main','Backing','Other'][i],t:[1,4,9][i],d:[7,2,3][i],s:1}]}));
const saveLines = async lines => (await fetch(`${API}/api/project/${encodeURIComponent(PID)}/timings`,
  {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({lines})})).json();
const reopen = async () => {
  await p.reload({waitUntil:'networkidle0'});
  await p.click('.card');
  await p.waitForSelector('#scrEdit:not(.hide)');
  await sleep(300);
};
await saveLines(fixture);
await reopen();
await revealTimeline(p);
ok('backing alone opens the second lane', await p.$eval('#tlwrap',el=>el.classList.contains('twolane')));
ok('voice-1 backing is below the main line', (await lane(1)) > (await lane(0))+20);
await p.evaluate(()=>document.querySelectorAll('#scroll .ln')[2].click());
await p.click('#btnVoice');
await sleep(700);
ok('backing shares the second singer’s level',Math.abs((await lane(1))-(await lane(2)))<1);

const blockPoint = i => p.evaluate(k=>{
  const r=document.querySelectorAll('#blocks .blk')[k].getBoundingClientRect();
  return {x:r.left+r.width/2,y:r.top+r.height/2};
},i);
await revealTimeline(p);
const backingPoint=await blockPoint(1);
await p.mouse.click(backingPoint.x,backingPoint.y);
await p.mouse.click(backingPoint.x,backingPoint.y);
ok('repeated clicks on backing do not select the overlapping lead',
   await p.$eval('#blocks .blk.sel',el=>el.dataset.i)==='1');
const scale=await p.$eval('#blocks .blk',el=>el.getBoundingClientRect().width/7);
await p.mouse.move(backingPoint.x,backingPoint.y);
await p.mouse.down();
await p.mouse.move(backingPoint.x-scale*2,backingPoint.y,{steps:12});
await p.mouse.up();
await sleep(900);
const movedBacking=await proj();
ok('backing can start before the main line ends',
   movedBacking.lines[1].start < 3 && movedBacking.lines[1].end < movedBacking.lines[0].end);
ok('dragging backing preserves the lead and the assigned singer',
   movedBacking.lines[0].start===1 && movedBacking.lines[0].end===8 && movedBacking.lines[1].voice===1);

await p.click('#btnFit');
await revealTimeline(p);
const atOverlap=await p.evaluate(()=>{
  const [main,back]=[...document.querySelectorAll('#blocks .blk')].map(el=>el.getBoundingClientRect());
  return {x:(Math.max(main.left,back.left)+Math.min(main.right,back.right))/2,
          y:main.top+main.height/2};
});
const mainHit=await p.evaluate(({x,y})=>{
  const el=document.elementFromPoint(x,y);
  return {hit:el?.closest('.blk')?.dataset.i,tag:el?.tagName,cls:el?.className,x,y,height:innerHeight};
},atOverlap);
await p.mouse.click(atOverlap.x,atOverlap.y);
ok('the overlapping lead is directly clickable in its own lane',
   await p.$eval('#blocks .blk.sel',el=>el.dataset.i)==='0',JSON.stringify(mainHit));

await p.evaluate(()=>document.querySelectorAll('#scroll .ln')[1].click());
await p.click('#btnBacking');
await sleep(700);
ok('removing the backing mark returns voice-1 blocks to the main lane',Math.abs((await lane(1))-(await lane(0)))<1);
await p.click('#btnUndo');
await sleep(700);
ok('undo restores the independent backing lane',Math.abs((await lane(1))-(await lane(2)))<1);

await saveLines(movedBacking.lines);
await reopen();
await revealTimeline(p);
ok('saved backing stays below the lead after reopening',Math.abs((await lane(1))-(await lane(2)))<1 && (await lane(1))>(await lane(0))+20);

console.log('\n--- backing of voice 2 gets a third lane ---');
const four=[...movedBacking.lines, {...movedBacking.lines[2],text:'Backing two',voice:2,backing:true,
  start:10,end:11,words:[{w:'Backing',t:10,d:.5,s:2},{w:'two',t:10.5,d:.5,s:1}]}];
await saveLines(four);await reopen();await revealTimeline(p);
ok('voice-2 backing enables the third lane',await p.$eval('#tlwrap',el=>el.classList.contains('threelane')));
ok('voice-2 backing is below voice 2, while voice-1 backing keeps its existing lane',
   (await lane(3))>(await lane(2))+20 && Math.abs((await lane(1))-(await lane(2)))<1);
const lower=await blockPoint(3);
await p.mouse.click(lower.x,lower.y);await p.mouse.click(lower.x,lower.y);
ok('repeated clicks stay on voice-2 backing',await p.$eval('#blocks .blk.sel',el=>el.dataset.i)==='3');
const wordGap=await p.evaluate(()=>{
  const word=document.querySelector('#words .wrd');
  const block=document.querySelectorAll('#blocks .blk')[3];
  return word.getBoundingClientRect().top-block.getBoundingClientRect().bottom;
});
ok('word chips stay below the third lane',wordGap>0,String(wordGap));
await p.mouse.move(lower.x,lower.y);await p.mouse.down();
await p.mouse.move(lower.x+20,lower.y,{steps:8});await p.mouse.up();await sleep(900);
const movedThird=await proj();
ok('voice-2 backing can be moved independently',movedThird.lines[3].start>10.05 && movedThird.lines[3].voice===2 && movedThird.lines[3].backing);
ok('its main voice keeps every original word timing',JSON.stringify(movedThird.lines[2])===JSON.stringify(four[2]));
const secondMain=await p.evaluate(()=>{
  const blocks=document.querySelectorAll('#blocks .blk');
  const main=blocks[2].getBoundingClientRect(),back=blocks[3].getBoundingClientRect();
  return {x:(Math.max(main.left,back.left)+Math.min(main.right,back.right))/2,y:main.top+main.height/2};
});
await p.mouse.click(secondMain.x,secondMain.y);
ok('voice 2 is directly clickable above its overlapping backing',await p.$eval('#blocks .blk.sel',el=>el.dataset.i)==='2');
await reopen();await revealTimeline(p);
ok('the third lane survives reopening',(await lane(3))>(await lane(2))+20);
await p.evaluate(()=>document.querySelectorAll('#scroll .ln')[3].click());
await p.click('#btnBacking');await sleep(700);
ok('removing the last second-voice backing collapses the extra lane',
   !(await p.$eval('#tlwrap',el=>el.classList.contains('threelane'))) && Math.abs((await lane(3))-(await lane(2)))<1);
await p.click('#btnUndo');await sleep(700);
ok('undo restores the third lane',(await lane(3))>(await lane(2))+20);
await p.click('#btnVoice');await sleep(700);
ok('backing of both voices stays below both main singers',
   await p.evaluate(()=>{
     const back=document.querySelectorAll('#blocks .blk')[3];
     return back.classList.contains('back')&&back.classList.contains('vboth')&&parseFloat(getComputedStyle(back).top)===68;
   }));
await p.click('#btnVoice');await sleep(700);
ok('changing backing back to voice 1 collapses the third lane',
   !(await p.$eval('#tlwrap',el=>el.classList.contains('threelane'))) && Math.abs((await lane(3))-(await lane(2)))<1);
await saveLines(original.lines);

ok('no JS errors', errs.length === 0, errs.slice(0,2).join(' | '));
await b.close();
console.log(fail ? '\nFAILED: '+fail : '\nAll checks passed');
process.exit(fail?1:0);
