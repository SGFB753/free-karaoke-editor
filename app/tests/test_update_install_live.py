"""Opt-in: real published updater -> new frozen core -> another update.

Run after build-windows.ps1, supplying the previous published Windows ZIP.
Uses a private installation, HTTP asset server, Temp, projects and model cache.
The --elevated worker flag suppresses GUI restart/UAC in this writable sandbox;
the installed real EXE is then started headlessly and checked over its HTTP API.
"""
import argparse
import hashlib
import http.server
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import types
import urllib.request
import zipfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'app'))
from kstudio import components as C, update as UP, models as M
import updater as U


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inventory(root):
    return {p.relative_to(root).as_posix(): p.stat().st_size
            for p in root.rglob('*') if p.is_file()}


def driver(args):
    # Execute the actual update client compiled into the installed release.
    from PyInstaller.archive.readers import CArchiveReader
    archive = CArchiveReader(str(Path(args.install)/'KaraokeStudio.exe'))
    pyz = archive.open_embedded_archive(next(n for n in archive.toc if n.startswith('PYZ')))
    module = types.ModuleType('kstudio.update')
    module.__package__ = 'kstudio'
    exec(pyz.extract('kstudio.update'), module.__dict__)
    module.supported = lambda: True
    module._bundle_root = lambda: args.install
    module.latest = lambda: dict(available=True, version='test-next',
        _zip=args.url+'/'+UP.ASSET, _sha=args.url+'/'+UP.CHECKSUM)
    real_popen = subprocess.Popen
    def hidden_worker(command, **kwargs):
        assert Path(command[0]).name == 'KaraokeUpdater.exe'
        kwargs['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        kwargs['stdout'] = open(args.worker_log, 'ab')
        kwargs['stderr'] = subprocess.STDOUT
        process = real_popen(command+['--elevated'], **kwargs)
        Path(args.worker_state).write_text(json.dumps(dict(pid=process.pid,
            helper=str(Path(command[0]).parents[1]))), encoding='utf-8')
        return process
    with patch.object(subprocess, 'Popen', side_effect=hidden_worker):
        item = module.download(lambda line: print(line, flush=True))
        module.launch(item['path'])


def run(args):
    output = ROOT/'build/update-e2e'
    output.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='isolated-', dir=output)).resolve()
    report = {'cycles': [], 'checks': []}
    env = dict(os.environ, TEMP=str(work/'temp'), TMP=str(work/'temp'),
        XDG_CACHE_HOME=str(work/'cache'), USERPROFILE=str(work/'home'),
        KARAOKE_PROJECTS=str(work/'library/projects'), PYTHONIOENCODING='utf-8',
        PYINSTALLER_RESET_ENVIRONMENT='1')
    env.pop('KARAOKE_COMPONENTS_DIR', None)
    env.pop('KARAOKE_CHECK_CACHED_QWEN', None)
    for name in ('temp', 'home', 'library/projects'):
        (work/name).mkdir(parents=True)
    server = None
    workers = []
    def check(name, value):
        if not value:
            raise AssertionError(name)
        report['checks'].append(name)
        print('PASS', name, flush=True)
    try:
        with zipfile.ZipFile(args.old_archive) as z:
            z.extractall(work/'installed')
        install = work/'installed/KaraokeStudio'
        old_files = inventory(install)
        report['old_install_bytes'] = sum(old_files.values())
        for name, data in {'projects/keep.json': b'project sentinel',
                           'output/keep.mp4': b'export sentinel',
                           'settings.ini': b'[studio]\nlanguage=ru\n'}.items():
            path = install/name; path.parent.mkdir(exist_ok=True); path.write_bytes(data)
        sentinels = {p: digest(install/p) for p in ('projects/keep.json', 'output/keep.mp4', 'settings.ini')}
        class QuietHandler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *values):
                pass
        handler = lambda *a, **kw: QuietHandler(*a, directory=str(Path(args.new_archive).parent), **kw)
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = 'http://127.0.0.1:'+str(server.server_port)
        # Download/install real component ZIPs via their normal hash/extraction
        # code, with only the asset host redirected to this local HTTP server.
        calls = []
        original_download = C._download
        def local_asset(remote, *values):
            calls.append(remote)
            return original_download(url+'/'+remote.rsplit('/', 1)[-1], *values)
        with patch.dict(os.environ, env, clear=True), patch.object(C, '_download', side_effect=local_asset):
            weights = Path(M.qwen_dir())/'existing-weights-sentinel'
            weights.parent.mkdir(parents=True, exist_ok=True); weights.write_bytes(b'preserve existing weights')
            weight_hash = digest(weights)
            runtime_dirs = [C.component_dir(n) for n in ('qwen', 'node')]
        runtime_after_first = None
        for cycle in range(2):
            state, log = output/f'worker-{cycle}.json', output/f'worker-{cycle}.log'
            log.write_bytes(b'')
            started = time.monotonic()
            command = [sys.executable, str(Path(__file__).resolve()), '--driver',
                '--install', str(install), '--url', url, '--worker-log', str(log), '--worker-state', str(state)]
            result = subprocess.run(command, env=env, capture_output=True, timeout=90)
            if result.returncode:
                print(result.stdout.decode('utf-8', errors='replace'), result.stderr.decode('utf-8', errors='replace'))
            check(f'cycle {cycle+1}: in-app download/checksum/handoff', result.returncode == 0)
            worker = json.loads(state.read_text())
            workers.append(worker['pid'])
            check(f'cycle {cycle+1}: running helper is protected', not UP._retire_helper_executable(str(Path(worker['helper'])/'updater/KaraokeUpdater.exe')))
            U.wait_for(worker['pid'], seconds=240)
            check(f'cycle {cycle+1}: actual frozen updater completed', 'Done /' in log.read_text(encoding='utf-8', errors='replace'))
            elapsed = round(time.monotonic()-started, 2)
            if cycle == 0:
                with patch.dict(os.environ, env, clear=True), patch.object(C, '_download', side_effect=local_asset):
                    for name in ('qwen', 'node'):
                        C.ensure(name, print)
                check('one initial component download each after upgrading the old installation', len(calls) == 4)
            # Start the installed real app. Its startup retires the old helper.
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
            process = subprocess.Popen([str(install/'KaraokeStudio.exe'), '--no-browser', '--port', str(port)],
                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            try:
                deadline = time.monotonic()+45
                caps = None
                while time.monotonic() < deadline:
                    try:
                        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/state', timeout=2) as response:
                            caps = json.load(response)['caps']
                        break
                    except (OSError, ValueError):
                        time.sleep(.25)
                check(f'cycle {cycle+1}: installed EXE starts and sees cached Qwen runtime', caps and caps['qwen'] and caps['qwenRuntimeReady'])
                while Path(worker['helper']).exists() and time.monotonic() < deadline:
                    time.sleep(.25)
                check(f'cycle {cycle+1}: helper copy deleted after exit', not Path(worker['helper']).exists())
            finally:
                process.terminate(); process.wait(timeout=15)
            leftovers = [p.name for p in (work/'temp').iterdir() if p.name.startswith(('karaoke-update-', 'karaoke-updater-', 'karaoke-stage-', 'karaoke-rollback-'))]
            check(f'cycle {cycle+1}: no download, stage, helper or rollback leftovers', not leftovers)
            check(f'cycle {cycle+1}: projects, exports and settings unchanged', all(digest(install/p) == value for p, value in sentinels.items()))
            check(f'cycle {cycle+1}: existing weights unchanged', digest(weights) == weight_hash)
            with zipfile.ZipFile(args.new_archive) as z:
                expected = {n.split('/', 1)[1] for n in z.namelist() if not n.endswith('/')}
            current = inventory(install)
            obsolete = set(old_files)-expected
            check(f'cycle {cycle+1}: obsolete bundled libraries removed', not obsolete.intersection(current))
            # Real import smoke from installed EXE, using persistent components.
            probe = subprocess.run([str(install/'KaraokeStudio.exe'), '--internal-package-smoke'], env=env,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=90)
            check(f'cycle {cycle+1}: cached Qwen/Node imports and media exports work', probe.returncode == 0)
            with patch.dict(os.environ, env, clear=True), patch.object(C, '_download', side_effect=AssertionError('runtime downloaded again')):
                for name in ('qwen', 'node'):
                    C.ensure(name)
            runtime_now = [inventory(p) for p in runtime_dirs]
            if runtime_after_first is not None:
                check('second update does not grow or duplicate runtime cache', runtime_now == runtime_after_first)
            runtime_after_first = runtime_now
            report['cycles'].append(dict(seconds=elapsed, install_bytes=sum(current.values()), obsolete_paths_absent=len(obsolete), leftovers=leftovers))
        report['result'] = 'passed'
    finally:
        for pid in workers:
            U.wait_for(pid, seconds=240)
        if server:
            server.shutdown(); server.server_close()
        assert work.parent == output.resolve() and work.name.startswith('isolated-')
        shutil.rmtree(work)
        report['sandbox_removed'] = not work.exists()
        (output/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old-archive')
    parser.add_argument('--new-archive')
    parser.add_argument('--driver', action='store_true')
    for name in ('install', 'url', 'worker-log', 'worker-state'):
        parser.add_argument('--'+name)
    arguments = parser.parse_args()
    driver(arguments) if arguments.driver else run(arguments)
