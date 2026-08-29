// The clip's cover behind the lyrics: not a field in a payload but paint on
// the screen. A page is built twice — bare and with a bright red cover — and
// the pixels themselves say whether the backdrop is truly visible.
import puppeteer from 'puppeteer';
import fs from 'fs';
import path from 'path';
import os from 'os';
import { execFileSync } from 'child_process';

let fail = 0;
const ok = (n, c, e='') => { console.log((c?'  ✓ ':'  ✗ ')+n+(e?' — '+e:'')); if(!c) fail++; };
const sleep = ms => new Promise(r=>setTimeout(r,ms));
const PY = process.env.KARAOKE_PYTHON || 'python3';

// A cover no one could miss: a plain red jpeg.
const RED = 'data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAMCAgMCAgMDAwMEAwMEBQgFBQQEBQoHBwYIDAoMDAsKCwsNDhIQDQ4RDgsLEBYQERMUFRUVDA8XGBYUGBIUFRT/2wBDAQMEBAUEBQkFBQkUDQsNFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBT/wAARCAASACADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD5/ooor8kP9CwooooAKKKKACiiigD/2Q==';

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'cover_'));
const txt = path.join(tmp, 'lyrics.txt');
fs.writeFileSync(txt, 'title: Обложка\n\nПервая строка песни\nВторая строка песни\n', 'utf8');
const bare = path.join(tmp, 'bare.html');
execFileSync(PY, ['karaoke.py', process.env.KARAOKE_SONG, txt, '-o', bare,
  '--align','energy','--no-separate','--ui-lang','ru']);

// The same page, with the cover slipped into the payload — exactly the field
// the studio export fills.
const raw = fs.readFileSync(bare, 'utf8');
const mark = '<script id="payload" type="application/json">';
const a = raw.indexOf(mark) + mark.length, b = raw.indexOf('</scr'+'ipt>', a);
const pay = JSON.parse(raw.slice(a,b).replace(/\\u003c/g,'<').replace(/\\u003e/g,'>')
                                     .replace(/\\u0026/g,'&'));
ok('the payload knows the cover field', 'cover' in pay, Object.keys(pay).join(','));
pay.cover = RED;
const covered = path.join(tmp, 'covered.html');
fs.writeFileSync(covered, raw.slice(0,a) + JSON.stringify(pay)
  .replace(/</g,'\\u003c').replace(/>/g,'\\u003e').replace(/&/g,'\\u0026') + raw.slice(b), 'utf8');

const br = await puppeteer.launch({headless:'new', args:['--no-sandbox','--disable-dev-shm-usage']});
const p = await br.newPage();
const errs = []; p.on('pageerror', e => errs.push(String(e)));
await p.setViewport({width:800, height:600});

// Three glances at the ground, away from buttons and titles.
const looks = async file => {
  await p.goto('file://' + file, {waitUntil:'networkidle0'});
  await sleep(600);
  const png = await p.screenshot({type:'png'});
  const shot = path.join(tmp, 'shot.png');
  fs.writeFileSync(shot, png);
  const out = execFileSync(PY, ['-c', `
from PIL import Image
im = Image.open(${JSON.stringify(path.join(tmp, 'shot.png'))}).convert('RGB')
W, H = im.size
px = [im.getpixel(p) for p in [(W//2, 80), (W-60, H-60), (60, H-80)]]
print(sum(1 for r, g, b in px if r > b + 8), px)`]).toString();
  return { red: parseInt(out), px: out.trim() };
};

const plain = await looks(bare);
ok('without a cover the ground keeps its cool colours', plain.red === 0, plain.px);
const dressed = await looks(covered);
ok('with a cover the red shows through the blur', dressed.red >= 2, dressed.px);
ok('the page itself raised no errors', errs.length === 0, errs.join(' | '));

await br.close();
fs.rmSync(tmp, {recursive:true, force:true});
console.log(fail ? '\nFAILED: '+fail : '\nAll checks passed');
process.exit(fail ? 1 : 0);
