USE home_credit_ml;

-- Du lieu nguon duoc nap truoc khi kiem tra/lam sach trong Python.
-- Bang tien do phuc vu kiem tra lan nap ban dau, khong phai bang dac trung.
SELECT table_name, source_rows, loaded_rows
FROM raw_load_manifest
ORDER BY table_name;

-- Vi du doc ho so nguon: giu NULL/sentinel va cac cot ban dau.
-- Notebook 01 doc du tam bang theo lo va doi soat toan bo voi nguon.
SELECT SK_ID_CURR, TARGET, AMT_INCOME_TOTAL, AMT_CREDIT, DAYS_EMPLOYED
FROM raw_application_train
ORDER BY _source_row
LIMIT 5;

-- Quy mo tung tap: phan tap da co tu notebook 01.
SELECT dataset_role, COUNT(*) AS n
FROM application_split
GROUP BY dataset_role;

-- Dem ho so co dac trung va kiem tra quan he mot-mot.
SELECT s.dataset_role, COUNT(*) AS n_with_features
FROM application_split AS s
JOIN application_features AS f USING (SK_ID_CURR)
GROUP BY s.dataset_role;

-- Dau vao train: notebook chon dung cot theo schema A hoac B va loai ID khoi X.
SELECT f.*
FROM application_features AS f
JOIN application_split AS s USING (SK_ID_CURR)
WHERE s.dataset_role = 'train'
ORDER BY f.SK_ID_CURR;

-- Kiem tra chi muc khong co bang dac trung tuong ung.
SELECT COUNT(*) AS missing_feature_rows
FROM application_split AS s
LEFT JOIN application_features AS f USING (SK_ID_CURR)
WHERE f.SK_ID_CURR IS NULL;

-- Phien ban du lieu duoc import.
SELECT name, value
FROM dataset_metadata
ORDER BY name;
