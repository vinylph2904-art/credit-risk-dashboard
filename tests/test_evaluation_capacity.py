"""Review capacity uses frozen labeled scores and an exact, stable ranking."""
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal
import pytest

from web.evaluation import ranking_capacity


def test_capacity_rounds_up_and_breaks_ties_by_application_id():
    predictions = pd.DataFrame({'SK_ID_CURR': [30, 10, 20, 40, 50, 60, 70],
                                'TARGET': [1, 0, 1, 0, 1, 0, 0],
                                'score': [.9, .9, .8, .7, .6, .5, .4]})
    before = predictions.copy(deep=True)
    rows, gains = ranking_capacity(predictions)
    assert [row['review_n'] for row in rows] == [1, 1, 2]
    assert [row['captured_n'] for row in rows] == [0, 0, 1]
    assert rows[-1]['precision'] == .5
    assert rows[-1]['recall'] == pytest.approx(1 / 3)
    assert rows[-1]['lift'] == pytest.approx(.5 / (3 / 7))
    assert gains.data[0].x[0] == 0 and gains.data[0].y[0] == 0
    assert gains.data[0].x[-1] == 1 and gains.data[0].y[-1] == 1
    assert np.diff(gains.data[0].y).min() >= 0
    assert list(gains.data[2].x) == pytest.approx([1 / 7, 1 / 7, 2 / 7])
    assert_frame_equal(before, predictions)


def test_active_validation_capacity_matches_saved_research_report():
    root = Path(__file__).resolve().parents[1]
    predictions = pd.read_parquet(root / 'reports/modeling/catboost_finalization/validation_predictions.parquet')
    saved = pd.read_csv(root / 'reports/modeling/operational_assessment_20261026/capacity.csv')
    saved = saved.loc[(saved['dataset'] == 'active_validation') & saved['fraction'].isin([.05, .10, .20])]
    rows, _ = ranking_capacity(predictions)
    for row, record in zip(rows, saved.itertuples()):
        assert row['fraction'] == record.fraction
        assert row['review_n'] == record.review_n
        assert row['captured_n'] == record.captured_positive_n
        for field in ['precision', 'recall', 'lift']:
            assert row[field] == pytest.approx(getattr(record, field), abs=1e-12)
