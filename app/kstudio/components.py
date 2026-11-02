"""Versioned optional runtimes, cached separately from replaceable Studio files."""
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import urllib.request
import zipfile
from pathlib import Path

from .i18n import tr

REVISION = '1'
RELEASE = 'runtime-v1'
_lock = threading.RLock()
_dll_handles = []
_verified = {}


def supported():
    return bool(getattr(sys, 'frozen', False) and sys.platform == 'win32')


def abi():
    return f'cp{sys.version_info.major}{sys.version_info.minor}-win_amd64'


def filename(name):
    return f'KaraokeStudio-{name}-runtime-v{REVISION}-{abi()}.zip'


def cache_root():
    from . import models
    return Path(models.qwen_dir()).parent / 'runtimes'


def component_dir(name):
    if name not in ('qwen', 'node'):
        raise ValueError('Unknown runtime component')
    override = os.environ.get('KARAOKE_COMPONENTS_DIR')
    return Path(override) / name if override else cache_root() / f'{name}-{REVISION}-{abi()}'


def ready(name):
    root = component_dir(name)
    try:
        anchor = root/('site-packages/qwen_asr/__init__.py' if name == 'qwen' else 'node.exe')
        if not anchor.is_file():
            return False
        stamp = (root/'runtime.json').stat().st_mtime_ns
        key = str(root.resolve())
        if _verified.get(key) == stamp:
            return True
        manifest = json.loads((root/'runtime.json').read_text(encoding='utf-8'))
        if manifest.get('revision') != REVISION or manifest.get('abi') != abi() or manifest.get('component') != name:
            return False
        files = manifest.get('files') or []
        valid = bool(files) and all((root/f['path']).is_file() and (root/f['path']).stat().st_size == f['size'] for f in files)
        if valid:
            _verified[key] = stamp
        return valid
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False


def _download(url, path, log, limit):
    from . import jobcontrol as JC
    request = urllib.request.Request(url, headers={'User-Agent': 'KaraokeStudio'})
    done, next_note = 0, 16 * 1024 * 1024
    with urllib.request.urlopen(request, timeout=45) as source, open(path, 'wb') as dest:
        while True:
            JC.checkpoint()
            block = source.read(1024 * 1024)
            if not block:
                break
            done += len(block)
            if done > limit:
                raise ValueError('Runtime component exceeds download limit')
            dest.write(block)
            if done >= next_note:
                log(tr(f'Runtime: downloaded {done//1024//1024} MB…', f'Движок: скачано {done//1024//1024} МБ…'))
                next_note += 16 * 1024 * 1024


def ensure(name, log=lambda message: None):
    from . import jobcontrol as JC, update
    with _lock:
        if ready(name):
            return component_dir(name)
        if os.environ.get('KARAOKE_COMPONENTS_DIR'):
            raise RuntimeError('Local runtime component is incomplete: ' + str(component_dir(name)))
        root = cache_root()
        root.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix=name+'-download-', dir=str(root)))
        try:
            log(tr(f'Downloading the {name} runtime once; it will survive application updates…',
                   f'Скачиваю движок {name} один раз; он сохранится между обновлениями программы…'))
            url = f'https://github.com/{update.repository()}/releases/download/{RELEASE}/{filename(name)}'
            checksum, archive, staged = work/'checksum.txt', work/'runtime.zip', work/'unpacked'
            _download(url+'.sha256', checksum, log, 65536)
            _download(url, archive, log, 800 * 1024 * 1024)
            match = re.search(r'\b[0-9a-fA-F]{64}\b', checksum.read_text(encoding='ascii'))
            digest = hashlib.sha256()
            with archive.open('rb') as stream:
                for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
                    JC.checkpoint(); digest.update(block)
            if not match or digest.hexdigest() != match.group(0).lower():
                raise ValueError('Runtime checksum does not match')
            with zipfile.ZipFile(archive) as z:
                for entry in z.infolist():
                    JC.checkpoint()
                    target = (staged/entry.filename).resolve()
                    if os.path.commonpath([str(staged.resolve()), str(target)]) != str(staged.resolve()) or '\\' in entry.filename or ':' in entry.filename:
                        raise ValueError('Unsafe path in runtime archive')
                    z.extract(entry, staged)
            manifest = json.loads((staged/'runtime.json').read_text(encoding='utf-8'))
            if manifest.get('revision') != REVISION or manifest.get('abi') != abi() or manifest.get('component') != name:
                raise ValueError('Incompatible runtime component')
            for entry in manifest.get('files') or []:
                path = (staged/entry['path']).resolve()
                if os.path.commonpath([str(staged.resolve()), str(path)]) != str(staged.resolve()) or path.stat().st_size != entry['size']:
                    raise ValueError('Incomplete runtime component')
            JC.checkpoint()
            destination = component_dir(name)
            if destination.exists():
                if ready(name):
                    return destination
                # Only this versioned component cache can be replaced; weights
                # and user projects are outside it.
                if destination.parent.resolve() != root.resolve():
                    raise ValueError('Invalid component cache path')
                shutil.rmtree(destination)
            os.replace(staged, destination)
            if not ready(name):
                raise ValueError('Runtime component is incomplete')
            return destination
        finally:
            if work.parent.resolve() != root.resolve():
                raise ValueError('Invalid runtime temporary path')
            shutil.rmtree(work, ignore_errors=True)


def activate_qwen(log=lambda message: None):
    root = ensure('qwen', log)
    site = str(root/'site-packages')
    if site not in sys.path:
        sys.path.insert(0, site)
        if hasattr(os, 'add_dll_directory'):
            for folder in [root/'site-packages', *(root/'site-packages').glob('*.libs')]:
                _dll_handles.append(os.add_dll_directory(str(folder)))
        import importlib
        importlib.invalidate_caches()
    return root
