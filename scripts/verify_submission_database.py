"""Read-only checks after importing the submission SQL with MySQL Workbench."""
from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from connectors.Connector import Connector


def verify(manifest_path):
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    database = Connector()
    database.connect()
    checks = {}
    try:
        database.execute('SET SESSION TRANSACTION READ ONLY')
        for table, expected in manifest['expected_table_counts'].items():
            if not table.replace('_', '').isalnum():
                raise ValueError('Invalid table identifier')
            actual = int(database.queryDataset(f'SELECT COUNT(*) AS n FROM `{table}`').iloc[0]['n'])
            checks[table] = {'expected': expected, 'actual': actual, 'passed': actual == expected}
            print(f'{table}: {actual} / {expected}', flush=True)
    finally:
        database.disConnect()
    if not all(row['passed'] for row in checks.values()):
        raise ValueError('Database counts differ from bundle manifest')
    return checks


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=ROOT.parent / 'data_bundle/manifest.json')
    options = parser.parse_args()
    verify(options.manifest)
