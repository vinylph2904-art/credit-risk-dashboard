"""A path migration must not disable protocol or frozen-test integrity checks."""
import ast
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest


SOURCE = Path(__file__).resolve().parents[1] / 'scripts/feature_study/run_study.py'


def run_guard(condition, namespace):
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    statement = next(node for node in tree.body
                     if isinstance(node, ast.If) and ast.unparse(node.test) == condition)
    exec(compile(ast.Module(body=[statement], type_ignores=[]), str(SOURCE), 'exec'), namespace)


@pytest.fixture
def study():
    root = Path(__file__).resolve().parents[1] / 'tmp' / ('migration_test_' + uuid4().hex)
    root.mkdir(parents=True)
    model = root / 'model.joblib'
    model.write_bytes(b'unchanged-model')
    digest = lambda value: hashlib.sha256(value).hexdigest()
    protocol = {'active_metadata_sha256': digest(b'new-path'), 'active_model_version': 'same-model'}
    saved = {**protocol, 'active_metadata_sha256': digest(b'old-path')}
    protocol_path = root / 'protocol.json'
    protocol_path.write_text(json.dumps(saved), encoding='utf-8')
    migration = {'metadata_before_sha256': saved['active_metadata_sha256'],
                 'metadata_after_sha256': protocol['active_metadata_sha256'],
                 'model_sha256': digest(model.read_bytes()),
                 'decision_before_sha256': digest(b'old-decision-path'),
                 'decision_after_sha256': digest(b'new-decision-path')}
    (root / 'path_migration_20261027.json').write_text(json.dumps(migration), encoding='utf-8')
    return {'ROOT': root, 'REPORTS': root, 'json': json, 'hashlib': hashlib,
            'active': {'model_path': model.name}, 'protocol_path': protocol_path,
            'protocol': protocol, 'fixture_migration': migration}


def test_known_path_migration_preserves_historical_protocol_identity(study):
    run_guard('protocol_path.exists()', study)
    assert study['protocol'] == json.loads(study['protocol_path'].read_text(encoding='utf-8'))


@pytest.mark.parametrize('change', ['metadata', 'model', 'protocol'])
def test_migration_rejects_unregistered_metadata_model_or_experiment_changes(study, change):
    if change == 'metadata':
        study['protocol']['active_metadata_sha256'] = hashlib.sha256(b'unregistered-change').hexdigest()
    elif change == 'model':
        (study['ROOT'] / 'model.joblib').write_bytes(b'changed-model')
    else:
        study['protocol']['active_model_version'] = 'changed-experiment'
    with pytest.raises(AssertionError):
        run_guard('protocol_path.exists()', study)


@pytest.mark.parametrize('change', [None, 'recorded-decision', 'current-decision'])
def test_cached_test_requires_the_exact_registered_decision_pair(study, change):
    path = study['ROOT'] / 'predictions.parquet'
    path.touch()
    migration = study['fixture_migration']
    recorded = migration['decision_before_sha256'] if change != 'recorded-decision' else 'unregistered'
    (study['ROOT'] / 'test_execution.json').write_text(json.dumps({'decision_sha256': recorded}), encoding='utf-8')
    study.update(test_path=path, pd=SimpleNamespace(read_parquet=lambda path: 'frozen-predictions'),
                 freeze_sha=migration['decision_after_sha256'] if change != 'current-decision' else 'changed')
    if change:
        with pytest.raises(AssertionError):
            run_guard('test_path.exists()', study)
    else:
        run_guard('test_path.exists()', study)
        assert study['test_predictions'] == 'frozen-predictions'
