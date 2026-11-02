"""Read-only consistency audit; no notebook execution, fitting, DDL or DML."""
from pathlib import Path
import ast
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding='utf-8')

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from IPython.core.inputtransformer2 import TransformerManager
from connectors.Connector import Connector
from models.CreditRiskModel import CreditRiskModel
from models.HomeCreditTraining import HomeCreditTraining

REPORT = ROOT / 'reports/modeling/selected_model_evaluation_20261030'
SELECTION = ROOT / 'reports/modeling/feature_selection_redo_20261029'
results = {}


def check(name, action):
    try:
        results[name] = {'status': 'passed', 'details': action()}
    except Exception as error:
        results[name] = {'status': 'failed', 'error': type(error).__name__ + ': ' + str(error)}
    print(name, results[name]['status'], flush=True)


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sources():
    for name in ['application_train','application_test','bureau','bureau_balance',
                 'previous_application','pos_cash_balance','credit_card_balance','installments_payments']:
        assert (ROOT / 'data/parquet' / (name + '.parquet')).is_file(), name
    return {path.name: pq.ParquetFile(path).metadata.num_rows
            for path in (ROOT / 'data/parquet').glob('*.parquet')}


def notebooks():
    count = 0
    imports = set()
    for path in sorted((ROOT / 'notebooks').glob('*.ipynb')):
        notebook = read_json(path)
        for index, cell in enumerate(notebook['cells']):
            if cell['cell_type'] != 'code':
                continue
            source = TransformerManager().transform_cell(''.join(cell['source']))
            tree = ast.parse(source)
            compile(tree, str(path) + ':cell' + str(index+1), 'exec')
            count += 1
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(('models.','connectors.','utils.')):
                    dependency = ROOT / (node.module.replace('.', '/') + '.py')
                    assert dependency.exists(), str(dependency)
                    imports.add(node.module)
    return {'notebooks': 8, 'compiled_code_cells': count, 'project_imports': sorted(imports)}




def split_check():
    manifest = read_json(ROOT / 'data/splits/split_manifest.json')
    digest = hashlib.sha256((ROOT / 'data/splits/application_split.parquet').read_bytes()).hexdigest()
    assert digest == manifest['id_manifest_sha256']
    assert split['SK_ID_CURR'].is_unique and 'TARGET' not in split
    assert split.groupby('split').size().to_dict() == {'train':184506,'validation':61502,'test':61503}
    assert set(split.loc[split['split'].eq('train'),'cv_fold']) == {0,1,2}
    assert split.loc[~split['split'].eq('train'),'cv_fold'].eq(-1).all()
    # Reproduce the documented split in memory, without replacing the frozen file.
    from sklearn.model_selection import StratifiedKFold, train_test_split
    labels = pd.read_parquet(ROOT / 'data/parquet/application_train.parquet', columns=['SK_ID_CURR','TARGET'])
    indices = np.arange(len(labels))
    remaining, test = train_test_split(indices,test_size=.2,stratify=labels.TARGET,random_state=42)
    train, validation = train_test_split(remaining,test_size=.25,stratify=labels.iloc[remaining].TARGET,random_state=42)
    regenerated = labels[['SK_ID_CURR']].copy()
    regenerated['split'] = ''
    for role, selected in [('train',train),('validation',validation),('test',test)]:
        regenerated.loc[selected,'split'] = role
    regenerated['cv_fold'] = -1
    for fold,(_, held_out) in enumerate(StratifiedKFold(3,shuffle=True,random_state=42).split(np.zeros(len(train)),labels.iloc[train].TARGET)):
        regenerated.loc[train[held_out],'cv_fold'] = fold
    pd.testing.assert_frame_equal(regenerated.sort_values('SK_ID_CURR').reset_index(drop=True),split,check_dtype=False)
    return {'counts': split.groupby('split').size().to_dict(), 'sha256':digest,
            'seed_42_split_and_folds_reproduced_in_memory':True,
            'train_folds': split.loc[split['split'].eq('train')].groupby('cv_fold').size().to_dict()}


def feature_schema():
    schema = read_json(ROOT / 'configs/preprocessing_schema.json')['schemas']
    assert len(schema['A']['feature_order']) == 127
    assert len(schema['B']['feature_order']) == 199
    assert len(model.feature_order) == len(set(model.feature_order)) == 182
    assert set(model.feature_order).issubset(schema['B']['feature_order'])
    assert not {'SK_ID_CURR','TARGET','split','cv_fold'} & set(model.feature_order)
    assert set(model.numeric).isdisjoint(model.categorical)
    assert set(model.numeric + model.categorical) == set(model.feature_order)
    folds = read_json(SELECTION / 'selected_features_by_fold.json')
    assert {key:len(value) for key,value in folds.items()} == {'0':181,'1':181,'2':181}
    final = read_json(SELECTION / 'selected_schema_train_only.json')
    assert final['feature_order'] == model.feature_order
    for role in ['train','validation','test','application_test']:
        feature_path = ROOT / 'data/features/b' / (role+'.parquet')
        names = pq.ParquetFile(feature_path).schema_arrow.names
        assert set(names) == {'SK_ID_CURR', *schema['B']['feature_order']}
        ids = pd.read_parquet(feature_path,columns=['SK_ID_CURR'])['SK_ID_CURR']
        assert ids.is_unique
        if role!='application_test':
            assert set(ids)==set(split.loc[split['split'].eq(role),'SK_ID_CURR'])
    return {'A':127,'B':199,'per_fold':181,'runtime':182,'runtime_matches_final_selection':True}


def cv_records():
    data = pd.read_csv(SELECTION / 'selected_cv_folds.csv')
    assert len(data) == 63 and data['case_id'].nunique() == 21
    assert data.groupby('case_id')['fold'].apply(lambda values: sorted(values)==[0,1,2]).all()
    assert data['features_n'].eq(181).all()
    assert set(data['model']) == {'Dummy','LR','DT','RF','XGB','CAT'}
    execution = read_json(SELECTION / 'execution.json')
    files = list((SELECTION/'cache').rglob('fold_*.npz'))
    verified = 0
    labels = pd.read_parquet(ROOT/'data/parquet/application_train.parquet',columns=['SK_ID_CURR','TARGET']).set_index('SK_ID_CURR')['TARGET']
    expected_folds = split.loc[split['split'].eq('train')].set_index('SK_ID_CURR')['cv_fold']
    for path in files:
        with np.load(path, allow_pickle=False) as saved:
            ids = saved['ids']
            fold = int(path.stem.split('_')[-1])
            assert len(ids) == len(set(ids.tolist()))
            assert expected_folds.loc[ids].eq(fold).all()
            np.testing.assert_array_equal(saved['y'],labels.loc[ids].to_numpy())
            assert np.isfinite(saved['score']).all()
            assert ((saved['score']>=0)&(saved['score']<=1)).all()
            assert str(saved['cache_key']) in [execution['baseline_cache_key'],execution['boosting_cache_key']]
            verified += 1
    assert verified >= 63
    return {'cv_rows':len(data),'configurations':21,'checkpoint_files_verified':verified}


def artifact():
    decision = read_json(REPORT / 'project_model_decision.json')
    digest = hashlib.sha256((ROOT / metadata['model_path']).read_bytes()).hexdigest()
    assert digest == decision['model_sha256']
    assert metadata['main_threshold'] == decision['threshold'] == .14539365168823878
    assert metadata['model_path'] == decision['model_path']
    local = read_json(ROOT / decision['metadata_path'])
    for key in ['model_path','feature_order','numeric','categorical','main_threshold','use_sigmoid']:
        assert local[key] == metadata[key], key
    return {'family':model.family,'loaded_class':type(model.model).__module__+'.'+type(model.model).__name__,
            'feature_count':len(model.feature_order),'threshold':model.threshold,
            'sha256':digest,'use_sigmoid':metadata['use_sigmoid']}


def evaluation():
    expected = pd.read_csv(REPORT/'evaluation_metrics.csv')
    output = {}
    for role,name in [('validation','validation'),('test','historical_internal_test')]:
        filename = 'validation_predictions.parquet' if role=='validation' else 'historical_test_predictions.parquet'
        predictions = pd.read_parquet(REPORT/filename)
        ids = split.loc[split['split'].eq(role),'SK_ID_CURR']
        assert predictions['SK_ID_CURR'].is_unique
        assert set(predictions['SK_ID_CURR']) == set(ids)
        computed = HomeCreditTraining.policyMetrics(predictions.TARGET,predictions.score,model.threshold,name,'CatBoost_Filter_182')
        stored = expected.loc[expected['dataset'].eq(name)].iloc[0]
        for key in ['n','positive_n','ap','roc_auc','brier','accuracy','precision','recall','f1','alert_rate','tn','fp','fn','tp','cost_5_to_1']:
            np.testing.assert_allclose(computed[key],stored[key],rtol=0,atol=1e-12)
        table = pq.ParquetFile(ROOT/'data/features/b'/(role+'.parquet'))
        saved_by_id = predictions.set_index('SK_ID_CURR')['score']
        maximum_error, rescored_rows = 0., 0
        for batch in table.iter_batches(batch_size=5000,columns=['SK_ID_CURR']+model.feature_order):
            inputs = batch.to_pandas().set_index('SK_ID_CURR')
            rescored = model.predict(model.prepareInput(inputs))['score']
            saved = saved_by_id.loc[inputs.index]
            maximum_error = max(maximum_error,float(np.max(np.abs(rescored-saved))))
            rescored_rows += len(inputs)
        assert maximum_error<=1e-12 and rescored_rows==len(predictions)
        output[role] = {'rows':len(predictions),'ap':computed['ap'],'roc_auc':computed['roc_auc'],
                        'rescored_rows':rescored_rows,'max_score_error':maximum_error}
    oof = pd.read_parquet(REPORT/'train_oof_predictions.parquet')
    comparison = pd.read_csv(REPORT/'calibration_comparison.csv').set_index('method')
    from sklearn.metrics import brier_score_loss
    for method,column in [('raw','raw_score'),('sigmoid','sigmoid_score')]:
        np.testing.assert_allclose(brier_score_loss(oof.TARGET,oof[column]),comparison.loc[method,'brier'],rtol=0,atol=1e-12)
    assert set(oof.SK_ID_CURR) == set(split.loc[split['split'].eq('train'),'SK_ID_CURR'])
    assert not metadata['use_sigmoid'] and comparison.loc['raw','brier'] < comparison.loc['sigmoid','brier']
    validation = pd.read_parquet(REPORT/'validation_predictions.parquet')
    _, sensitivity = HomeCreditTraining.thresholdEvaluation(validation.TARGET,validation.score)
    selected = sensitivity.loc[sensitivity['fn_cost'].eq(5),'threshold'].iloc[0]
    assert selected == model.threshold
    output['calibration_and_validation_threshold_match'] = True
    return output


def database():
    connection=Connector()
    connection.connect()
    try:
        # Enforce read-only mode in addition to using SELECT statements only.
        cursor=connection.conn.cursor()
        cursor.execute('SET SESSION TRANSACTION READ ONLY')
        cursor.close()
        db_split=connection.queryDataset('SELECT SK_ID_CURR,dataset_role AS split,cv_fold FROM application_split ORDER BY SK_ID_CURR')
        labelled=db_split.loc[~db_split['split'].eq('application_test')].reset_index(drop=True)
        expected=split.sort_values('SK_ID_CURR').reset_index(drop=True)
        pd.testing.assert_frame_equal(labelled.astype(expected.dtypes.to_dict()),expected)
        assert len(db_split.loc[db_split['split'].eq('application_test')])==48744
        tables=connection.queryDataset('SELECT TABLE_NAME FROM information_schema.tables WHERE TABLE_SCHEMA=DATABASE()')
        names=set(tables.iloc[:,0])
        assert {'raw_application_train','raw_application_test','raw_bureau','raw_bureau_balance',
                'raw_previous_application','raw_pos_cash_balance','raw_credit_card_balance','raw_installments_payments',
                'application_split','application_features','dataset_metadata','demo_profiles','model_versions',
                'scoring_events','review_notes','users','user_audit'}.issubset(names)
        feature_count=connection.queryDataset('SELECT COUNT(*) AS n FROM application_features').iloc[0,0]
        assert feature_count==356255
        fields=connection.queryDataset('SHOW COLUMNS FROM application_features')['Field'].tolist()
        assert 'TARGET' not in fields and set(model.feature_order).issubset(fields)
        events=connection.queryDataset('SELECT score,threshold,alert,input_sha256,input_snapshot FROM scoring_events WHERE model_version=%s ORDER BY event_id DESC LIMIT 50',(model.version,))
        maximum_error=0
        for row in events.itertuples():
            assert hashlib.sha256(row.input_snapshot.encode()).hexdigest()==row.input_sha256
            payload=json.loads(row.input_snapshot)
            assert set(payload)==set(model.feature_order)
            score=float(model.predict(model.prepareInput(pd.DataFrame([payload])))['score'].iloc[0])
            maximum_error=max(maximum_error,abs(score-row.score))
            assert abs(score-row.score)<=1e-12
            assert row.threshold==model.threshold and row.alert==int(score>=row.threshold)
        return {'split_rows':len(db_split),'feature_rows':int(feature_count),
                'required_tables_present':True,'scoring_events_verified':len(events),'max_score_error':maximum_error}
    finally:
        connection.disConnect()


def main():
    global metadata, model, split
    metadata = read_json(ROOT / 'artifacts/inference_metadata.json')
    model = CreditRiskModel(ROOT).loadModel()
    split = pd.read_parquet(ROOT / 'data/splits/application_split.parquet')

    check('raw_parquet_sources',sources)
    check('notebooks_source_and_imports',notebooks)
    check('frozen_split',split_check)
    check('feature_schema',feature_schema)
    check('cv_and_checkpoints',cv_records)
    check('active_model_artifact',artifact)
    check('saved_metrics_and_inference',evaluation)
    check('mysql_read_only_consistency',database)
    path=ROOT/'reports/system_audit/20261101/checks.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(results,ensure_ascii=False,indent=2,default=lambda value:value.item()),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=False,indent=2))
    return 0 if all(result['status'] == 'passed' for result in results.values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
