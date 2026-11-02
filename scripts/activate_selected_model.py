"""Activate the frozen 182-feature model and append scores without resetting data."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from connectors.Connector import Connector
from models.CreditRiskData import CreditRiskData
from models.CreditRiskModel import CreditRiskModel


def activate():
    folder = ROOT / 'reports/modeling/selected_model_evaluation_20261030'
    decision = json.loads((folder / 'project_model_decision.json').read_text(encoding='utf-8'))
    path = ROOT / decision['metadata_path']
    metadata = json.loads(path.read_text(encoding='utf-8'))
    model_hash = hashlib.sha256((ROOT / metadata['model_path']).read_bytes()).hexdigest()
    if model_hash != decision['model_sha256']:
        raise ValueError('Artifact khác phiên bản đã chốt.')
    metadata.update({
        'log_columns': [],
        'input_preparation': 'numeric float32 with NaN; categorical missing __MISSING__, strings; no OHE/log/scale',
        'positive_rule': 'score >= threshold',
        'cost_ratio': {'fn': 5, 'fp': 1},
        'train_n': 184506,
        'data_version': 'home-credit-v1',
        'test_status': 'previously observed historical test; not a new independent evaluation',
        'calibration_scope': 'nested train OOF; raw selected by lower Brier',
        'evaluation': {
            'folder': str(folder.relative_to(ROOT)).replace('\\', '/'),
            'dataset': 'validation', 'label': 'Validation · dùng để chọn ngưỡng',
            'predictions': 'validation_predictions.parquet', 'metrics': 'validation_metrics.csv',
            'policy': 'CatBoost_Filter_182', 'threshold_candidates': 'threshold_candidates.csv',
            'importance': 'interpretation/feature_importance.csv', 'image': 'figures/validation.png',
        },
        'legacy_registration': {
            'model_sha256': model_hash,
            'policy_sha256': hashlib.sha256(json.dumps({
                'model_version': metadata['model_version'], 'feature_order': metadata['feature_order'],
                'main_threshold': metadata['main_threshold'], 'use_sigmoid': metadata['use_sigmoid'],
            }, sort_keys=True).encode()).hexdigest(),
        },
    })
    model = CreditRiskModel(ROOT).loadModel(path)
    if len(model.feature_order) != 182 or model.threshold != decision['threshold']:
        raise ValueError('Schema/ngưỡng khác quyết định chốt.')
    db = Connector()
    db.connect()
    try:
        before = db.queryDataset('SELECT * FROM demo_profiles ORDER BY profile_id')
        notes = db.queryDataset('SELECT * FROM review_notes ORDER BY note_id')
        old_events = db.queryDataset('SELECT * FROM scoring_events ORDER BY event_id')
        registration = db.queryDataset('SELECT * FROM model_versions WHERE model_version=%s', (model.version,))
        if registration.empty:
            db.execute('''INSERT INTO model_versions
                (model_version,case_id,model_path,model_sha256,policy_sha256,feature_n,threshold)
                VALUES (%s,%s,%s,%s,%s,%s,%s)''',
                (model.version, metadata['case_id'], metadata['model_path'], model_hash,
                 metadata['legacy_registration']['policy_sha256'], 182, model.threshold))
        else:
            row = registration.iloc[0]
            if row['model_sha256'] != model_hash or row['feature_n'] != 182 or row['threshold'] != model.threshold:
                raise ValueError('Đăng ký model hiện có không khớp.')
        data = CreditRiskData(db, model.version, model.feature_order)
        profiles = data.getProfiles()
        ids = profiles.loc[profiles['score'].isna(), 'profile_id'].tolist()
        scored_n = 0
        for start in range(0, len(ids), 200):
            inputs = model.prepareInput(data.getFeatures(ids[start:start + 200]))
            scored_n += data.saveScores(inputs, model.predict(inputs), model.threshold)
        import pandas as pd
        pd.testing.assert_frame_equal(before, db.queryDataset('SELECT * FROM demo_profiles ORDER BY profile_id'))
        pd.testing.assert_frame_equal(notes, db.queryDataset('SELECT * FROM review_notes ORDER BY note_id'))
        after = db.queryDataset('SELECT * FROM scoring_events ORDER BY event_id')
        pd.testing.assert_frame_equal(old_events.reset_index(drop=True),
            after.loc[after['event_id'].isin(old_events['event_id'])].reset_index(drop=True))
        if data.getProfiles()['score'].isna().any():
            raise ValueError('Còn hồ sơ hoạt động chưa có điểm phiên bản mới.')
        active = ROOT / 'artifacts/inference_metadata.json'
        backup = ROOT / 'backups/dashboard_activation_20261031'
        backup.mkdir(parents=True, exist_ok=True)
        if not (backup / 'inference_metadata.json').exists():
            (backup / 'inference_metadata.json').write_bytes(active.read_bytes())
        serialized = json.dumps(metadata, ensure_ascii=False, indent=2) + '\n'
        path.write_text(serialized, encoding='utf-8')
        active.with_suffix('.json.tmp').write_text(serialized, encoding='utf-8')
        active.with_suffix('.json.tmp').replace(active)
        result = {'model_version': model.version, 'feature_n': 182, 'threshold': model.threshold,
                  'model_sha256': model_hash, 'new_scoring_events': scored_n,
                  'active_profiles': len(profiles), 'old_events_preserved': len(old_events),
                  'profiles_unchanged': True, 'notes_unchanged': True}
        report = folder / 'dashboard_activation.json'
        if report.exists():
            report = folder / 'dashboard_activation_latest.json'
        report.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(result))
    finally:
        db.disConnect()


if __name__ == '__main__':
    activate()
