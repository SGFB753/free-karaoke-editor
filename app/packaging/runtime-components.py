"""Build ordinary Python wheel files as a separate, persistent Qwen runtime."""
import hashlib
import importlib.metadata as metadata
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'app'))
from kstudio import components as C


def graph(roots):
    seen, todo = {}, [Requirement(r) for r in roots]
    while todo:
        requirement = todo.pop()
        name, extras = canonicalize_name(requirement.name), set(requirement.extras) | {''}
        if name in seen and extras <= seen[name]:
            continue
        seen.setdefault(name, set()).update(extras)
        distribution = metadata.distribution(name)
        for raw in distribution.requires or []:
            child = Requirement(raw)
            if child.marker is None or any(child.marker.evaluate({'extra': e}) for e in extras):
                todo.append(child)
    return set(seen)


def requirements(path):
    return [line.split('#')[0].strip() for line in path.read_text(encoding='utf-8').splitlines()
            if line.strip() and not line.lstrip().startswith('#')]


def build():
    core = graph(requirements(ROOT/'app/requirements.txt') + ['imageio-ffmpeg'])
    extra = graph(requirements(ROOT/'app/requirements-qwen.txt')) - core
    stage, public = ROOT/'build/components-stage', ROOT/'dist'
    if stage.exists():
        assert stage.resolve().parent == (ROOT/'build').resolve()
        shutil.rmtree(stage)
    public.mkdir(exist_ok=True)
    exclusions = set()
    for name in sorted(extra):
        distribution = metadata.distribution(name)
        top = distribution.read_text('top_level.txt')
        if top:
            exclusions.update(n.strip() for n in top.splitlines() if n.strip().isidentifier())
        for file in distribution.files or []:
            if '..' in file.parts or '__pycache__' in file.parts or file.suffix == '.pyc':
                continue
            source = Path(distribution.locate_file(file))
            if not source.is_file():
                continue
            first = file.parts[0]
            module = first.split('.')[0]
            if module.isidentifier() and not first.endswith('.dist-info'):
                exclusions.add(module)
            destination = stage/'qwen/site-packages'/str(file)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    import nodejs_wheel
    node = Path(nodejs_wheel.__file__).parent
    (stage/'node').mkdir(parents=True, exist_ok=True)
    shutil.copy2(node/'node.exe', stage/'node/node.exe')
    node_version = subprocess.run([str(node/'node.exe'), '--version'], check=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout.decode().strip()
    license_cache = ROOT/'build'/('node-license-'+node_version+'.txt')
    if not license_cache.is_file():
        with urllib.request.urlopen('https://raw.githubusercontent.com/nodejs/node/'+node_version+'/LICENSE', timeout=45) as response:
            license_cache.write_bytes(response.read())
    shutil.copy2(license_cache, stage/'node/LICENSE-node.txt')
    for source in node.glob('LICENSE*'):
        if source.is_file():
            shutil.copy2(source, stage/'node'/source.name)
    for name in ('qwen', 'node'):
        folder = stage/name
        files = [{'path': str(p.relative_to(folder)).replace('\\', '/'), 'size': p.stat().st_size}
                 for p in sorted(folder.rglob('*')) if p.is_file()]
        manifest = dict(component=name, revision=C.REVISION, abi=C.abi(), files=files)
        (folder/'runtime.json').write_text(json.dumps(manifest), encoding='utf-8')
        archive = public/C.filename(name)
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for p in sorted(folder.rglob('*')):
                if p.is_file():
                    z.write(p, str(p.relative_to(folder)).replace('\\', '/'))
        checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
        Path(str(archive)+'.sha256').write_text(checksum+'  '+archive.name+'\n', encoding='ascii')
        print(name, len(files), 'files;', round(archive.stat().st_size/1024**2, 1), 'MiB', flush=True)
    # Keep Qwen-specific dependencies out of the core EXE/PYZ too, not only
    # their data directories. Node is loaded as an independent executable.
    exclusions.discard('nodejs_wheel')  # tiny Python shim is used by pytubefix
    (ROOT/'build/component-exclusions.json').write_text(json.dumps(sorted(exclusions)), encoding='utf-8')
    (ROOT/'build/component-distributions.json').write_text(json.dumps(sorted(extra)), encoding='utf-8')


if __name__ == '__main__':
    build()
