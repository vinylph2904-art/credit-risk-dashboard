"""CatBoost with a feature selector fitted inside each calibration fold."""
import numpy as np
from catboost import CatBoostClassifier
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.utils.validation import check_is_fitted

from models.FeatureSelection import select_filter_features
from models.HomeCreditTraining import HomeCreditTraining


class SelectedCatBoostClassifier(ClassifierMixin, BaseEstimator):
    def __init__(self, schema, parameters, correlation_limit=0.90,
                 min_pairwise_overlap=0.50):
        self.schema = schema
        self.parameters = parameters
        self.correlation_limit = correlation_limit
        self.min_pairwise_overlap = min_pairwise_overlap

    def fit(self, X, y):
        self.selected_features_, self.dropped_features_ = select_filter_features(
            X, self.schema, self.correlation_limit, self.min_pairwise_overlap)
        self.selected_schema_ = {
            'feature_order': self.selected_features_,
            'numeric': [c for c in self.schema['numeric'] if c in self.selected_features_],
            'categorical': [c for c in self.schema['categorical'] if c in self.selected_features_],
        }
        data = HomeCreditTraining.prepareBoostingData(X, self.selected_schema_, 'CAT')
        print('CatBoost fit:', len(X), 'rows,', len(self.selected_features_), 'features', flush=True)
        self.model_ = CatBoostClassifier(
            **self.parameters, cat_features=tuple(self.selected_schema_['categorical']))
        self.model_.fit(data, y)
        self.classes_ = self.model_.classes_
        self.feature_names_ = self.model_.feature_names_
        self.n_features_in_ = X.shape[1]
        self.feature_names_in_ = np.asarray(X.columns, dtype=object)
        return self

    def predict_proba(self, X):
        check_is_fitted(self, 'model_')
        data = HomeCreditTraining.prepareBoostingData(X, self.selected_schema_, 'CAT')
        return self.model_.predict_proba(data)

    def predict(self, X):
        return self.classes_[self.predict_proba(X).argmax(axis=1)]
