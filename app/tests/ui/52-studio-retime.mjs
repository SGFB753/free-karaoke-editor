// Re-timing, against a running studio. Two things it used to get wrong: it
// timed the song with a model nobody chose, and it had nowhere to hear that a
// stretch of the song holds no words.
const API = process.env.KARAOKE_API;
let fail = 0;
const ok = (n, c, e='') => { console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c) fail++; };
const sleep = ms => new Promise(r=>setTimeout(r,ms));

const post = async (path, body) => (await (await fetch(API + path, {method:'POST',
  headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)})).json());
const get = async path => (await (await fetch(API + path)).json());

async function finish(jid, seconds = 180){
  for (let i = 0; i < seconds * 2; i++){
    const j = await get('/api/job?id=' + jid);
    if (j.done || j.error) return j;
    await sleep(500);
  }
  return {done:false, ok:false, log:['timed out']};
}

console.log('--- a song built with a model of its own ---');
const built = await post('/api/new', {
  audio: process.env.KARAOKE_SONG, lyrics: process.env.KARAOKE_TEXT,
  align: 'energy', model: 'medium', separate: false});
const job = await finish(built.job);
ok('the song is built', job.ok, (job.log || []).slice(-1)[0]);
const pid = job.result;
let data = await get('/api/project/' + encodeURIComponent(pid));
ok('the model it was built with is written down', data.model === 'medium', data.model);

console.log('\n--- re-timing keeps it ---');
// It used to fall back to “small” here, quietly making the timing worse than
// the one the person was trying to fix.
const again = await finish((await post(`/api/project/${encodeURIComponent(pid)}/realign`,
  {align: 'energy'})).job);
ok('the re-timing goes through', again.ok, (again.log || []).slice(-1)[0]);
const said = (again.log || []).join('\n');
ok('and it says which model it used', /Модель:\s*medium|Model:\s*medium/.test(said),
   (again.log || []).find(l => /Модель|Model/.test(l)) || said.slice(0, 80));
ok('never the default one', !/Модель:\s*small|Model:\s*small/.test(said));
data = await get('/api/project/' + encodeURIComponent(pid));
ok('the song still remembers it afterwards', data.model === 'medium', data.model);

console.log('\n--- and it hears “there are no words here” ---');
// The test song sings at 2.0-4.6, 5.0-7.6, 8.0-10.6, 11.0-13.6, 16.0-18.6,
// 19.0-21.6. Marking the first two phrases must clear them of words.
const before = Math.min(...data.lines.map(l => l.start));
ok('before the marks, the early phrases are used', before < 7.8, before.toFixed(1));
const marked = await finish((await post(`/api/project/${encodeURIComponent(pid)}/realign`,
  {align: 'energy', noText: '0:00-0:08'})).job);
ok('the re-timing with marks goes through', marked.ok, (marked.log || []).slice(-1)[0]);
data = await get('/api/project/' + encodeURIComponent(pid));
const after = Math.min(...data.lines.map(l => l.start));
ok('nothing is left on the marked stretch', after >= 7.8, after.toFixed(1));
ok('every line is still there', data.lines.length === 6, data.lines.length);
ok('the marks are kept with the song', /0\.0-8\.0/.test(data.noText || ''), data.noText);

console.log('\n--- a locked line survives the re-timing ---');
// What a person put right by hand outweighs anything the model returns for it.
data = await get('/api/project/' + encodeURIComponent(pid));
const moved = JSON.parse(JSON.stringify(data.lines));
moved[0].start = 0.5; moved[0].end = 1.4; moved[0].lock = true;
moved[0].words = moved[0].words.map((w, i) => ({...w, t: 0.5 + i * 0.2, d: 0.2}));
await post(`/api/project/${encodeURIComponent(pid)}/timings`, {lines: moved});
const withLock = await finish((await post(`/api/project/${encodeURIComponent(pid)}/realign`,
  {align: 'energy'})).job);
ok('the re-timing goes through', withLock.ok, (withLock.log || []).slice(-1)[0]);
data = await get('/api/project/' + encodeURIComponent(pid));
ok('the locked line kept the hand-made time', Math.abs(data.lines[0].start - 0.5) < 0.01,
   data.lines[0].start);
ok('and it is still locked afterwards', data.lines[0].lock === true, data.lines[0].lock);
ok('the lines around it were timed anew', data.lines[1].start > 1.4, data.lines[1].start);
ok('the log says what was left alone',
   /заперт|locked/i.test((withLock.log || []).join('\n')),
   (withLock.log || []).find(l => /заперт|locked/i.test(l)) || '');
ok('and it was used as a peg for the rest of the text',
   /опорны|pegs/i.test((withLock.log || []).join('\n')),
   (withLock.log || []).find(l => /опорны|pegs/i.test(l)) || '');

// unlock it again, so the checks below see an ordinary song
const back = JSON.parse(JSON.stringify(data.lines));
back[0].lock = false;
await post(`/api/project/${encodeURIComponent(pid)}/timings`, {lines: back});

console.log('\n--- and a few lines can be timed again on their own ---');
// The timing is wrong in one place and right everywhere else. Redoing all of
// it costs minutes on a long song and throws away every hand-made correction.
data = await get('/api/project/' + encodeURIComponent(pid));
const was = JSON.parse(JSON.stringify(data.lines));
// put lines 3 and 4 plainly out of place, then ask for those two alone
const bent = JSON.parse(JSON.stringify(data.lines));
for (const i of [2, 3]){
  const shift = 0.9;
  bent[i].start += shift; bent[i].end += shift;
  bent[i].words = bent[i].words.map(w => ({...w, t: w.t + shift}));
}
await post(`/api/project/${encodeURIComponent(pid)}/timings`, {lines: bent});
const part = await finish((await post(`/api/project/${encodeURIComponent(pid)}/realign-part`,
  {from: 2, to: 3, align: 'energy'})).job);
ok('timing a stretch goes through', part.ok, (part.log || []).slice(-1)[0]);
ok('and it says which lines and where', /3–4|3-4/.test((part.log || []).join('\n')),
   (part.log || []).find(l => /3–4|3-4/.test(l)) || '');
ok('only the chosen lines are reported', part.result && part.result.lines === 2,
   JSON.stringify(part.result));

data = await get('/api/project/' + encodeURIComponent(pid));
const same = (a, b) => Math.abs(a - b) < 0.001;
ok('the lines around them are untouched to the millisecond',
   [0, 1, 4, 5].every(i => same(data.lines[i].start, was[i].start)
                        && same(data.lines[i].end, was[i].end)),
   [0, 1, 4, 5].map(i => (data.lines[i].start - was[i].start).toFixed(3)).join(', '));
ok('and the bent ones came back to where they were sung',
   [2, 3].every(i => same(data.lines[i].start, was[i].start)),
   [2, 3].map(i => `${was[i].start.toFixed(2)}→${data.lines[i].start.toFixed(2)}`).join(', '));
ok('every line is still in the song', data.lines.length === was.length, data.lines.length);

// a choice that makes no sense is refused, not obeyed
const silly = await post(`/api/project/${encodeURIComponent(pid)}/realign-part`,
  {from: 99, to: 120, align: 'energy'});
const sillyEnd = silly.job ? await finish(silly.job) : {ok: false, error: silly.error};
ok('an impossible choice of lines is refused',
   !sillyEnd.ok && /не выбрано|no lines/i.test(JSON.stringify(sillyEnd)),
   JSON.stringify(sillyEnd).slice(0, 90));

console.log('\n--- a partial re-timing heeds the marks too ---');
// The test song sings at 2.0-4.6, 5.0-7.6, 8.0-10.6, 11.0-13.6, 16.0-18.6,
// 19.0-21.6. Re-time lines 3–4 with the third phrase marked as wordless:
// they must land on the fourth phrase and beyond, not on the marked one.
const part2 = await finish((await post(`/api/project/${encodeURIComponent(pid)}/realign-part`,
  {from: 2, to: 3, align: 'energy', noText: '0:08-0:10.7'})).job);
ok('the re-timing goes through', part2.ok, (part2.log || []).slice(-1)[0]);
data = await get('/api/project/' + encodeURIComponent(pid));
const third = data.lines[2];
ok('no re-timed line landed on the marked stretch',
   third.start >= 10.55 || third.end <= 8.05,
   `${third.start.toFixed(1)}–${third.end.toFixed(1)}`);
const fourth = data.lines[3];
ok('nor the one after it',
   fourth.start >= 10.55 || fourth.end <= 8.05,
   `${fourth.start.toFixed(1)}–${fourth.end.toFixed(1)}`);

console.log('\n--- nonsense in the field is ignored, not obeyed ---');
const junk = await finish((await post(`/api/project/${encodeURIComponent(pid)}/realign`,
  {align: 'energy', noText: 'который час'})).job);
ok('a re-timing with nonsense still goes through', junk.ok, (junk.log || []).slice(-1)[0]);
data = await get('/api/project/' + encodeURIComponent(pid));
ok('and the song is timed over its whole length',
   Math.min(...data.lines.map(l => l.start)) < 7.8,
   Math.min(...data.lines.map(l => l.start)).toFixed(1));

// the stand belongs to everyone: leave it as it was found
await fetch(`${API}/api/project/${encodeURIComponent(pid)}/delete`, {method:'POST'});
console.log(fail ? `\nFAILED: ${fail}` : '\nAll checks passed');
process.exit(fail ? 1 : 0);
