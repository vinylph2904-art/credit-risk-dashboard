"""Tải mô hình đã fit và chấm điểm, không huấn luyện trong luồng web."""
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from utils.FileUtil import FileUtil


class CreditRiskModel:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.model = None

    def loadModel(self, metadata_path=None):
        if metadata_path is None:
            metadata_path = self.root / 'artifacts/inference_metadata.json'
        self.metadata = FileUtil.readJson(metadata_path)
        model_path = self.root / self.metadata['model_path']
        if not model_path.resolve().is_relative_to(self.root):
            raise ValueError('Đường dẫn mô hình nằm ngoài dự án.')
        self.model = joblib.load(model_path)
        self.feature_order = self.metadata['feature_order']
        self.numeric = self.metadata['numeric']
        self.categorical = self.metadata['categorical']
        self.log_columns = self.metadata['log_columns']
        self.threshold = self.metadata['main_threshold']
        self.version = self.metadata['model_version']
        self.family = self.metadata.get('model_family', 'LR')
        calibrated = getattr(self.model, 'calibrated_classifiers_', [])
        base_model = calibrated[0].estimator if calibrated else self.model
        names = base_model.feature_names_ if self.family == 'CAT' else self.model.feature_names_in_
        if list(names) != self.feature_order:
            raise ValueError('Thứ tự đặc trưng không khớp pipeline.')
        return self

    def prepareInput(self, frame):
        if frame.empty or frame.columns.has_duplicates:
            raise ValueError('Đầu vào rỗng hoặc có tên cột trùng.')
        if set(frame.columns) != set(self.feature_order):
            raise ValueError(f'Đầu vào phải có đúng {len(self.feature_order)} đặc trưng theo schema.')
        data = frame.loc[:, self.feature_order].copy()
        for column in self.numeric:
            values = pd.to_numeric(data[column], errors='raise')
            data[column] = values.astype('float32' if self.family == 'CAT' else float)
        if np.isinf(data[self.numeric].to_numpy()).any():
            raise ValueError('Biến số chứa giá trị vô hạn.')
        has_negative_log_input = (data[self.log_columns] < 0).any().any()
        if has_negative_log_input:
            raise ValueError('Các biến tiền dùng log phải không âm.')
        for column in self.categorical:
            observed_values = data[column].dropna()
            is_text = observed_values.map(lambda value: isinstance(value, str))
            if not is_text.all():
                raise ValueError('Biến phân loại phải là chuỗi hoặc giá trị thiếu.')
            if self.family == 'CAT':
                data[column] = data[column].astype(object).fillna('__MISSING__').astype(str)
            else:
                data[column] = data[column].astype(object).where(data[column].notna(), np.nan)
        return data

    def predict(self, frame):
        """Chấm DataFrame đã qua prepareInput; trả score, threshold và alert."""
        scores = self.model.predict_proba(frame)[:, 1]
        if not np.isfinite(scores).all() or not ((scores >= 0) & (scores <= 1)).all():
            raise ValueError('Mô hình trả điểm ngoài phạm vi hợp lệ.')
        return pd.DataFrame({'score': scores, 'threshold': self.threshold,
                             'alert': scores >= self.threshold}, index=frame.index)

    def simulate(self, frame, changes):
        """Thử đầu vào một hồ sơ trên bản sao; không lưu điểm hoặc sửa model."""
        from models.HomeCreditPreparation import HomeCreditPreparation

        if len(frame) != 1 or not isinstance(changes, dict):
            raise ValueError('Mô phỏng cần đúng một hồ sơ và các giá trị giả định.')
        fields = set(changes)
        if fields not in [set(), {'AMT_INCOME_TOTAL'}, {'AMT_CREDIT', 'AMT_ANNUITY'}]:
            raise ValueError('Chỉ thay thu nhập hoặc nhập đồng thời khoản vay và niên kim.')
        scenario = frame.copy(deep=True)
        dependencies = {
            'AMT_INCOME_TOTAL': ['RATIO_CREDIT_INCOME_RECORDED',
                'RATIO_ANNUITY_INCOME_RECORDED', 'INCOME_DIV_FAMILY_SIZE_RECORDED'],
            'AMT_CREDIT': ['RATIO_CREDIT_INCOME_RECORDED', 'RATIO_CREDIT_GOODS_RECORDED'],
            'AMT_ANNUITY': ['RATIO_ANNUITY_INCOME_RECORDED'],
        }
        ratio_columns = []
        for name, value in changes.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError('Giá trị giả định phải là số.')
            try:
                value = float(value)
            except OverflowError:
                raise ValueError('Giá trị giả định quá lớn.') from None
            if not np.isfinite(value) or value <= 0:
                raise ValueError('Giá trị giả định phải hữu hạn và lớn hơn 0.')
            if pd.notna(frame.iloc[0][name]) and value == frame.iloc[0][name]:
                continue
            scenario[name] = float(value)
            for column in dependencies[name]:
                if column not in ratio_columns:
                    ratio_columns.append(column)
        if ratio_columns:
            calculated = HomeCreditPreparation.addApplicationRatios(scenario.copy())
            scenario[ratio_columns] = calculated[ratio_columns]

        baseline_score = float(self.predict(self.prepareInput(frame.loc[:, self.feature_order]))['score'].iloc[0])
        scenario_score = float(self.predict(self.prepareInput(scenario.loc[:, self.feature_order]))['score'].iloc[0])
        comparisons = []
        labels = [
            ('AMT_INCOME_TOTAL', 'Thu nhập ghi nhận', 'amount'),
            ('AMT_CREDIT', 'Giá trị khoản vay', 'amount'),
            ('AMT_ANNUITY', 'Niên kim ghi nhận', 'amount'),
            ('RATIO_CREDIT_INCOME_RECORDED', 'Credit / Income', 'ratio'),
            ('RATIO_ANNUITY_INCOME_RECORDED', 'Annuity / Income', 'ratio'),
            ('RATIO_CREDIT_GOODS_RECORDED', 'Credit / Goods price', 'ratio'),
            ('INCOME_DIV_FAMILY_SIZE_RECORDED', 'Income / Family size', 'amount'),
        ]
        for column, label, kind in labels:
            before, after = frame.iloc[0][column], scenario.iloc[0][column]
            comparisons.append({'label': label, 'kind': kind,
                'baseline': float(before) if pd.notna(before) else None,
                'scenario': float(after) if pd.notna(after) else None,
                'changed': column in ratio_columns or column in changes})
        return {'baseline_score': baseline_score, 'scenario_score': scenario_score,
            'delta_pp': 100 * (scenario_score - baseline_score),
            'baseline_alert': baseline_score >= self.threshold,
            'scenario_alert': scenario_score >= self.threshold,
            'threshold': self.threshold, 'version': self.version, 'comparisons': comparisons}
