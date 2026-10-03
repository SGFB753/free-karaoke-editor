// Release notes use the interface language; opening/cancelling never installs.
const { JSDOM } = await import('jsdom');
const API = process.env.KARAOKE_API;
const html = await (await fetch(API + '/')).text();
const js = await (await fetch(API + '/ui.js')).text();
let downloads = 0, missing = false;
const languages = [];
const dom = new JSDOM(html, {runScripts:'dangerously', pretendToBeVisual:true,
  url:API+'/', beforeParse(w){
    w.__errs=[]; w.onerror=m=>w.__errs.push(String(m));
    w.HTMLCanvasElement.prototype.getContext = () => ({});
    w.fetch = async (path, options={}) => {
      const json = value => new Response(JSON.stringify(value), {headers:{'Content-Type':'application/json'}});
      if (path === '/api/update') return json({available:true, version:'4.50.0', tag:'v4.50.0'});
      if (String(path).startsWith('/api/update/notes?')) {
        const language = options.headers['X-Karaoke-Lang'];
        languages.push(language);
        return json({notes:missing ? '' : (language === 'ru' ? 'Русские изменения' : 'English changes') + '\n<img id="injected">'});
      }
      if (path === '/api/update/download') { downloads++; return json({error:'Test: installation stopped'}); }
      const response = await fetch(String(path).startsWith('/') ? API+path : path, options);
      if (path === '/api/state') {
        const state = await response.json(); state.caps.updates=true;
        return json(state);
      }
      return response;
    };
    w.confirm = () => {throw new Error('Unexpected native confirmation');};
  }});
const w=dom.window, $=id=>w.document.getElementById(id);
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
let failed=0;
const ok=(name, condition)=>{console.log((condition?'  ✓ ':'  ✗ ')+name); if(!condition)failed++;};
w.KARAOKE_UI_LANG='ru'; w.eval(js); await sleep(1100);
$('btnUpdate').click(); await sleep(150);
ok('an available update opens the release notes', !$('updateDlg').classList.contains('hide'));
ok('Russian UI asks for Russian notes', languages.at(-1)==='ru' && $('updateNotes').textContent.includes('Русские'));
ok('remote markup stays plain text', !w.document.getElementById('injected'));
$('btnUpdateCancel').click();
ok('cancel closes without downloading', $('updateDlg').classList.contains('hide') && downloads===0);
$('btnLang').click(); await sleep(200);
$('btnUpdate').click(); await sleep(150);
ok('English UI asks for English notes', languages.at(-1)==='en' && $('updateNotes').textContent.includes('English'));
w.document.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
ok('Escape closes and returns focus', $('updateDlg').classList.contains('hide') && w.document.activeElement===$('btnUpdate'));
missing=true; $('btnUpdate').click(); await sleep(150);
ok('missing notes have an explanation and do not disable install', !!$('updateNotes').textContent && !$('btnUpdateInstall').disabled);
$('btnUpdateInstall').click(); await sleep(150);
ok('only an explicit install starts downloading', downloads===1);
ok('no JavaScript errors', w.__errs.length===0);
dom.window.close();
console.log(failed ? 'FAILED: '+failed : 'All checks passed');
process.exit(failed ? 1 : 0);
