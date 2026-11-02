import math

import pandas as pd


def select_filter_features(frame, schema, correlation_limit=0.90,
                           min_pairwise_overlap=0.50):
    """Remove constant columns and redundant numeric columns using Pearson correlation."""
    original = schema["feature_order"]
    constants = [column for column in original if frame[column].nunique(dropna=False) <= 1]
    candidates = [column for column in original if column not in constants]
    numeric = [column for column in candidates if column in schema["numeric"]]
    categorical = [column for column in candidates if column in schema["categorical"]]

    min_overlap = max(100, math.ceil(len(frame) * min_pairwise_overlap))
    corr = frame[numeric].corr(method="pearson", min_periods=min_overlap).abs()
    order = sorted(numeric, key=lambda column: (frame[column].isna().mean(), original.index(column)))
    kept_numeric = []
    dropped = [{"feature": column, "reason": "zero_variance", "kept_instead": None}
               for column in constants]
    for column in order:
        redundant_with = next((kept for kept in kept_numeric
                               if pd.notna(corr.at[column, kept])
                               and corr.at[column, kept] >= correlation_limit), None)
        if redundant_with is None:
            kept_numeric.append(column)
        else:
            dropped.append({
                "feature": column,
                "reason": f"pearson_correlation_ge_{correlation_limit:.2f}",
                "kept_instead": redundant_with,
                "absolute_correlation": float(corr.at[column, redundant_with])
            })

    kept = set(kept_numeric + categorical)
    selected = [column for column in original if column in kept]
    return selected, dropped
