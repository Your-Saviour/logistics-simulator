"""Bind persistent PLC binaries to the exact compiled source bundle."""
import hashlib
import json
from pathlib import Path


def source_hash(source):
    digest = hashlib.sha256()
    for file in sorted(Path(source).rglob('*')):
        if file.is_file() and file.name != 'compiler-package-lock.json':
            digest.update(file.relative_to(source).as_posix().encode() + b'\0' + file.read_bytes() + b'\0')
    return digest.hexdigest()


def verify(source, build):
    source, build = Path(source), Path(build)
    marker = build / 'cell-program.json'
    if not marker.exists():
        if list(build.glob('libplc_*.so')):
            raise RuntimeError('Untracked PLC binary; supervised cold provisioning required')
        return False
    metadata = json.loads(marker.read_text())
    library = metadata['library']
    if Path(library).name != library or not library.startswith('libplc_') or not library.endswith('.so'):
        raise RuntimeError('Invalid PLC program marker')
    if metadata['source_sha256'] != source_hash(source):
        raise RuntimeError('PLC source changed; provision a new release without replacing live state')
    if hashlib.sha256((build / library).read_bytes()).hexdigest() != metadata['binary_sha256']:
        raise RuntimeError('PLC binary changed; reconciliation required')
    return True


def record(source, build):
    build = Path(build)
    libraries = sorted(build.glob('libplc_*.so'))
    if len(libraries) != 1:
        raise RuntimeError('Exactly one compiled PLC binary required')
    library = libraries[0]
    metadata = {'library': library.name, 'source_sha256': source_hash(Path(source)),
                'binary_sha256': hashlib.sha256(library.read_bytes()).hexdigest()}
    temporary = build / 'cell-program.json.tmp'
    temporary.write_text(json.dumps(metadata, sort_keys=True))
    temporary.replace(build / 'cell-program.json')
