"""Verify and unpack the separately supplied data bundle using Python stdlib."""
from pathlib import Path
import argparse
import gzip
import hashlib
import json
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def prepare(bundle, research=False):
    manifest = json.loads((bundle / 'manifest.json').read_text(encoding='utf-8'))
    for name in ['database.sql.gz'] + (['research_data.zip'] if research else []):
        path = bundle / name
        if sha256(path) != manifest['files'][name]['sha256']:
            raise ValueError(f'Checksum mismatch: {name}')
        print(f'Checksum OK: {name}', flush=True)
    sql = bundle / 'database.sql'
    if sql.exists():
        if sha256(sql) != manifest['uncompressed_sql']['sha256']:
            raise FileExistsError(f'Existing SQL differs from bundle: {sql}')
        print('Existing SQL checksum OK; reusing it.', flush=True)
    else:
        temporary = bundle / 'database.sql.partial'
        if temporary.exists():
            raise FileExistsError(temporary)
        with gzip.open(bundle / 'database.sql.gz', 'rb') as source, temporary.open('xb') as destination:
            shutil.copyfileobj(source, destination, length=4 * 1024 * 1024)
        if sha256(temporary) != manifest['uncompressed_sql']['sha256']:
            raise ValueError('Uncompressed SQL checksum mismatch')
        temporary.replace(sql)
    print(f'Import this file with MySQL Workbench: {sql}', flush=True)
    if research:
        entries = {entry['path']: entry for entry in manifest['research_files']}
        with zipfile.ZipFile(bundle / 'research_data.zip') as archive:
            for member in archive.infolist():
                path = (ROOT / member.filename).resolve()
                if member.filename not in entries or not path.is_relative_to(ROOT / 'data'):
                    raise ValueError(f'Unexpected archive path: {member.filename}')
                if path.exists() and sha256(path) != entries[member.filename]['sha256']:
                    raise FileExistsError(f'Existing data differs: {path}')
            for member in archive.infolist():
                path = Path(archive.extract(member, ROOT))
                if sha256(path) != entries[member.filename]['sha256']:
                    raise ValueError(f'Extracted data mismatch: {member.filename}')
        print('Research data extracted and verified.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, default=ROOT.parent / 'data_bundle')
    parser.add_argument('--research', action='store_true')
    options = parser.parse_args()
    prepare(options.bundle.resolve(), options.research)
