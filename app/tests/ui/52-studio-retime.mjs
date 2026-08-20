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
