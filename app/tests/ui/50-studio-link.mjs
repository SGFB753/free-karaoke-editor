// A link instead of a file: the sound is taken out of it, and the words are
// offered underneath. Both endings are walked through — the one where the
// download fails and the one where it works — because a person meets both.
const { JSDOM } = await import('jsdom');
const API = process.env.KARAOKE_API;
const html = await (await fetch(API + "/")).text();
const js   = await (await fetch(API + "/ui.js")).text();

const dom = new JSDOM(html, { runScripts:"dangerously", pretendToBeVisual:true,
  url: API + "/",
  beforeParse(w){
    w.__errs=[]; w.onerror=m=>w.__errs.push(String(m));
    w.fetch = (path, opts) => fetch(typeof path === "string" && path.startsWith("/")
        ? API + path : path, opts);
    w.AudioContext = class { constructor(){ this.state="running"; this.destination={}; }
      createGain(){ return {gain:{value:1, setTargetAtTime(v){this.value=v;}}, connect(){}}; }
      createBufferSource(){ return {connect(){},start(){},stop(){}}; }
      decodeAudioData(){ return Promise.resolve({duration:1}); } resume(){} };
    w.HTMLCanvasElement.prototype.getContext = () => ({
      scale(){}, clearRect(){}, fillRect(){}, beginPath(){}, moveTo(){}, lineTo(){},
      stroke(){}, set fillStyle(v){}, set strokeStyle(v){}, set lineWidth(v){} });
    w.Element.prototype.getBoundingClientRect = () =>
      ({left:0,top:0,width:900,height:96,right:900,bottom:96,x:0,y:0});
  }});
const w = dom.window, doc = w.document, $ = id => doc.getElementById(id);
const sleep = ms => new Promise(r=>setTimeout(r,ms));
w.eval(js);
await sleep(900);

let fail=0; const ok=(n,c,e='')=>{console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c)fail++;};
const click = id => $(id).dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
const until = async (fn, ms=20000) => {
  const end = Date.now() + ms;
  while (Date.now() < end){ if (fn()) return true; await sleep(200); }
  return false;
};

click('btnAdd');
await sleep(200);

console.log('--- the link has a place of its own ---');
ok('there is a field for a link', !!$('inLink'));
ok('and a button that takes the sound', !!$('btnFetch'));
ok('nothing is claimed before it is pressed', !$('inAudio').value);

console.log('\n--- something that is not a link ---');
$('inLink').value = 'ftp://example.com/song.mp3';
click('btnFetch');
// “Taking the sound…” shows the moment the button is pressed, so waiting for
// any text at all would read the note before the answer is in.
await until(() => /Не скачалось/.test($('linkNote').textContent));
ok('it is refused, and the reason names http',
   /http/i.test($('linkNote').textContent), $('linkNote').textContent);
ok('and nothing was put in the song field', !$('inAudio').value);

console.log('\n--- a link that leads nowhere ---');
$('inLink').value = 'https://example.com/watch?v=fail';
click('btnFetch');
await until(() => /Не скачалось/.test($('linkNote').textContent));
const bad = $('linkNote').textContent;
ok('the failure is said out loud', /Не скачалось/.test(bad), bad.slice(0, 60));
ok('with the reason the downloader gave', /Video unavailable/.test(bad), bad.slice(-70));
ok('and it offers another link or a file',
   /другую ссылку/.test(bad) && /файл/.test(bad), bad.slice(-60));
ok('the song field is still empty', !$('inAudio').value);
ok('the button works again', !$('btnFetch').disabled);

console.log('\n--- a link that works ---');
$('inLink').value = 'https://example.com/watch?v=zzz123';
click('btnFetch');
const arrived = await until(() => !!$('inAudio').value);
ok('the sound reaches the song field', arrived, $('inAudio').value.slice(-40));
ok('and the window says what came', /Звук на месте/.test($('linkNote').textContent),
   $('linkNote').textContent.slice(0, 60));

console.log('\n--- the background choice appears with the link ---');
// The song from the link brought a cover and a video source. They are one
// choice, never two independent ticks which can contradict each other.
ok('the background selector is visible', !$('grpCover').classList.contains('hide'));
ok('the still cover is the quiet default', $('selBackground').value === 'cover',
   $('selBackground').value);
ok('moving footage is the other single choice',
   [...$('selBackground').options].some(o => o.value === 'video'));

console.log('\n--- the words are offered underneath ---');
const found = await until(() => $('lyricsFound').children.length > 0);
ok('there are texts to choose from', found, $('lyricsNote').textContent.slice(0, 70));
const rows = [...$('lyricsFound').children];
ok('each one says where it came from and how long it is',
   rows.every(r => /LRCLIB|Genius/.test(r.textContent) && /строк/.test(r.textContent)) &&
   rows.some(r => /LRCLIB/.test(r.textContent)) && rows.some(r => /Genius/.test(r.textContent)),
   rows.map(r => r.textContent.slice(0, 60)).join(' | '));
ok('a record with no words at all is not among them',
   !rows.some(r => /Empty Records/.test(r.textContent)), rows.length + ' offered');
ok('the person is asked to read before taking',
   /Прочитайте/.test($('lyricsNote').textContent), $('lyricsNote').textContent.slice(0, 50));

rows[0].querySelector('button').dispatchEvent(new w.MouseEvent('click',{bubbles:true}));
const took = await until(() => !!$('inLyrics').value);
ok('taking one puts it into the text field', took, $('inLyrics').value.slice(-30));
ok('the words are in the box, to be read and corrected',
   $('taLyrics').value.split('\n').length >= 2, $('taLyrics').value.slice(0, 40));
ok('and the box is open', !$('pasteBox').classList.contains('hide'));
const first = $('inLyrics').value;

console.log('\n--- or the text is pasted by hand ---');
$('taLyrics').value = 'строка руками\nвторая строка руками';
$('taLyrics').dispatchEvent(new w.Event('input',{bubbles:true}));
ok('the lines in the box are counted', /2 строки/.test($('pasteCount').textContent),
   $('pasteCount').textContent);
click('btnUseText');
await until(() => $('inLyrics').value !== first);
ok('the pasted text becomes a file of its own',
   $('inLyrics').value !== first && /\.txt$/.test($('inLyrics').value),
   $('inLyrics').value.slice(-40));
ok('and the window says it is in place', /Текст на месте/.test($('lyricsNote').textContent),
   $('lyricsNote').textContent);

$('taLyrics').value = '   ';
$('taLyrics').dispatchEvent(new w.Event('input',{bubbles:true}));
click('btnUseText');
await sleep(300);
ok('an empty box is not saved as a text', /пусто/.test($('lyricsNote').textContent),
   $('lyricsNote').textContent);

console.log('\n--- lyrics pasted into the field made for a path ---');
// A one-line field loses the line breaks, and the whole song arrives as one
// long run — which is what a person actually does when they copy the words
// off a lyrics site.
const many = 'первая строка\nвторая строка\nтретья строка';
const paste = (id, text) => {
  const ev = new w.Event('paste', {bubbles:true, cancelable:true});
  ev.clipboardData = { getData: () => text };
  $(id).dispatchEvent(ev);
};
const was = $('inLyrics').value;
paste('inLyrics', many);
await until(() => $('inLyrics').value !== was);
ok('the words do not stay in the one-line field', $('inLyrics').value !== many);
ok('the lines are whole in the box below',
   $('taLyrics').value.split('\n').length === 3, JSON.stringify($('taLyrics').value));
ok('and they are saved as a file', /\.txt$/.test($('inLyrics').value),
   $('inLyrics').value.slice(-30));
ok('the window says what it did', /текст песни/.test($('lyricsNote').textContent),
   $('lyricsNote').textContent.slice(0, 60));
// The line breaks have to survive all the way to the disk, not just on screen.
const rep = await (await fetch(API + '/api/report', {method:'POST',
  headers:{'Content-Type':'application/json'},
  body: JSON.stringify({audio: $('inAudio').value, lyrics: $('inLyrics').value,
                        align:'energy', separate:false})})).json();
ok('the file on the disk holds three lines, not one',
   rep.text && rep.text.lines === 3, JSON.stringify(rep.text || rep).slice(0, 90));

const keptAudio = $('inAudio').value;
paste('inAudio', 'https://example.com/watch?v=zzz123');
await sleep(200);
ok('a link pasted into the file field goes to the link field',
   $('inLink').value === 'https://example.com/watch?v=zzz123', $('inLink').value);
ok('and the file that was already chosen stays', $('inAudio').value === keptAudio);

console.log('\n--- the report sees both files ---');
const reported = await until(() => !$('report').classList.contains('hide'), 25000);
ok('the report came up on its own', reported);

console.log('\n--- a job that fell over lets you out ---');
// The progress screen had one way to end badly: it kept spinning, with no
// “← To the list”. The job's own error came back through the reader that
// treats an error as a broken request, and the polling stopped on the very
// answer that had to be shown. A text file picked as the song gets there.
$('inAudio').value = $('inLyrics').value;
$('inAudio').dispatchEvent(new w.Event('input',{bubbles:true}));
click('btnBuild');
const wayOut = await until(() => !$('btnJobBack').classList.contains('hide'), 90000);
ok('the way back appears when the job fails', wayOut,
   ($('jobLog').textContent.split('\n').pop() || '').slice(0, 70));
ok('and the failure is named', /Не получилось/.test($('jobTitle').textContent),
   $('jobTitle').textContent);
ok('the reason stays in the log', $('jobLog').textContent.length > 0,
   ($('jobLog').textContent.split('\n').pop() || '').slice(0, 70));
click('btnJobBack');
await sleep(500);
ok('and it really goes back to the list',
   !$('scrList').classList.contains('hide'));

ok('no errors in the window', w.__errs.length === 0, w.__errs[0] || '');
console.log(fail ? `\nFAILED: ${fail}` : '\nAll checks passed');
process.exit(fail ? 1 : 0);
