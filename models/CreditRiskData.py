"""Đọc hồ sơ và lưu kết quả chấm điểm qua Connector."""
import hashlib
import json

FINANCIAL_FIELDS = [
    'NAME_CONTRACT_TYPE', 'NAME_INCOME_TYPE', 'NAME_EDUCATION_TYPE',
    'NAME_FAMILY_STATUS', 'NAME_HOUSING_TYPE', 'OCCUPATION_TYPE',
    'FLAG_OWN_CAR', 'FLAG_OWN_REALTY', 'AMT_CREDIT', 'AMT_INCOME_TOTAL',
    'AMT_ANNUITY', 'AMT_GOODS_PRICE', 'AGE_YEARS', 'EMPLOYED_YEARS',
    'EMPLOYED_SENTINEL', 'RATIO_CREDIT_INCOME_RECORDED',
    'RATIO_ANNUITY_INCOME_RECORDED', 'RATIO_CREDIT_GOODS_RECORDED',
    'EXT_SOURCE_1', 'EXT_SOURCE_2', 'EXT_SOURCE_3', 'HAS_USABLE_BUREAU',
    'HAS_USABLE_BUREAU_BALANCE', 'HAS_USABLE_PREVIOUS', 'HAS_USABLE_POS',
    'HAS_USABLE_CARD', 'HAS_USABLE_INSTALLMENTS', 'BUR_LOAN_N',
    'PREV_APPLICATION_N', 'PREV_REFUSED_N', 'POS_KNOWN_DPD_MONTH_N',
    'POS_DPD_MONTH_SHARE', 'BB_KNOWN_DPD_MONTH_N', 'BB_DPD_MONTH_SHARE',
    'CC_KNOWN_DPD_MONTH_N', 'CC_DPD_MONTH_SHARE',
    'INS_OBS_VERSIONED_PERIOD_N', 'INS_PERIOD_WITH_AFTER_DUE_PAYMENT_SHARE',
]


PROFILE_SQL = '''
SELECT p.*, f.NAME_CONTRACT_TYPE, f.NAME_INCOME_TYPE,
       f.OCCUPATION_TYPE, f.NAME_EDUCATION_TYPE, f.NAME_HOUSING_TYPE,
       f.AMT_INCOME_TOTAL, f.AMT_CREDIT, f.AMT_ANNUITY,
       f.EXT_SOURCE_1, f.EXT_SOURCE_2, f.EXT_SOURCE_3, f.HAS_USABLE_BUREAU,
       f.AGE_YEARS, f.BUR_OVERDUE_DAYS_MAX, f.BUR_C1_OVERDUE_MAX,
       f.HAS_USABLE_INSTALLMENTS, f.INS_PERIOD_WITH_AFTER_DUE_PAYMENT_SHARE,
       e.event_id, e.score, e.threshold, e.alert, e.scored_at
FROM demo_profiles AS p
JOIN application_features AS f ON f.SK_ID_CURR=p.source_application_id
LEFT JOIN scoring_events AS e ON e.event_id=(
    SELECT MAX(s.event_id) FROM scoring_events AS s
    WHERE s.profile_id=p.profile_id AND s.model_version=%s)
'''


class CreditRiskData:
    def __init__(self, connector, model_version, feature_order):
        self.connector = connector
        self.model_version = model_version
        self.feature_order = feature_order

    def getProfiles(self, include_archived=False):
        where = ' WHERE p.is_archived=0'
        if include_archived:
            where = ''
        return self.connector.queryDataset(
            PROFILE_SQL + where + ' ORDER BY p.profile_id', (self.model_version,))

    def getFinancialPortfolio(self, scope):
        """Reporting only: keep labeled research and managed cases separate."""
        fields = ', '.join('f.`' + name + '`' for name in FINANCIAL_FIELDS)
        if scope == 'research':
            sql = f'''SELECT f.SK_ID_CURR AS source_application_id, a.TARGET, {fields}
                FROM application_features f
                JOIN application_split s USING(SK_ID_CURR)
                JOIN raw_application_train a USING(SK_ID_CURR)
                WHERE s.dataset_role='train' ORDER BY f.SK_ID_CURR'''
            data = self.connector.queryDataset(sql)
        elif scope == 'managed':
            sql = f'''SELECT p.*, {fields}, e.score, e.alert, e.scored_at
                FROM demo_profiles p JOIN application_features f
                ON f.SK_ID_CURR=p.source_application_id
                LEFT JOIN scoring_events e ON e.event_id=(
                    SELECT MAX(x.event_id) FROM scoring_events x
                    WHERE x.profile_id=p.profile_id AND x.model_version=%s)
                WHERE p.is_archived=0 ORDER BY p.source_application_id'''
            data = self.connector.queryDataset(sql, (self.model_version,))
        else:
            raise ValueError('Phạm vi dữ liệu không hợp lệ.')
        if data['source_application_id'].duplicated().any():
            raise ValueError('Hồ sơ bị nhân dòng trong báo cáo tài chính.')
        return data

    def getFinancialBureau(self, scope, currency, credit_status):
        """Aggregate each bureau source once before joining the application cohort."""
        if scope not in ['research', 'managed']:
            raise ValueError('Phạm vi dữ liệu không hợp lệ.')
        cohort = ("SELECT SK_ID_CURR FROM application_split WHERE dataset_role='train'"
                  if scope == 'research' else
                  'SELECT source_application_id FROM demo_profiles WHERE is_archived=0')
        cohort_params = ()
        if scope == 'managed':
            ids = self.connector.queryDataset(cohort)['source_application_id'].tolist()
            cohort = ','.join(['%s'] * len(ids)) if ids else 'SELECT NULL WHERE FALSE'
            cohort_params = tuple(int(value) for value in ids)
        status_sql = '' if credit_status == 'all' else ' AND CREDIT_ACTIVE=%s'
        params = cohort_params + ((currency,) if credit_status == 'all' else (currency, credit_status))
        pair = '''(AMT_CREDIT_SUM_DEBT>=0 AND AMT_CREDIT_SUM_OVERDUE>=0
                    AND NOT(AMT_CREDIT_SUM_DEBT=0 AND AMT_CREDIT_SUM_OVERDUE>0))'''
        sql = f'''SELECT SK_ID_CURR AS source_application_id,
            COUNT(*) AS loan_n, COUNT(DISTINCT SK_ID_BUREAU) AS unique_n,
            SUM(CASE WHEN {pair} THEN 1 ELSE 0 END) AS money_n,
            SUM(CASE WHEN {pair} THEN AMT_CREDIT_SUM_DEBT END) AS debt,
            SUM(CASE WHEN {pair} THEN AMT_CREDIT_SUM_OVERDUE END) AS overdue,
            SUM(CASE WHEN AMT_CREDIT_SUM_OVERDUE>=0 AND
                (AMT_CREDIT_SUM_DEBT IS NULL OR NOT {pair})
                THEN AMT_CREDIT_SUM_OVERDUE END) AS outside_overdue,
            SUM(CASE WHEN CREDIT_DAY_OVERDUE>=0 THEN 1 ELSE 0 END) AS dpd_n,
            SUM(CASE WHEN CREDIT_DAY_OVERDUE>0 THEN 1 ELSE 0 END) AS overdue_n
            FROM raw_bureau WHERE SK_ID_CURR IN ({cohort})
            AND DAYS_CREDIT<=0 AND DAYS_CREDIT_UPDATE<=0
            AND DAYS_CREDIT_UPDATE>=DAYS_CREDIT AND CREDIT_CURRENCY=%s {status_sql}
            GROUP BY SK_ID_CURR'''
        data = self.connector.queryDataset(sql, params)
        if (data['loan_n'] != data['unique_n']).any():
            raise ValueError('Khoản bureau bị trùng; cần đối soát trước khi tổng hợp tiền.')
        return data

    def getFinancialPrevious(self, scope):
        if scope not in ['research', 'managed']:
            raise ValueError('Phạm vi dữ liệu không hợp lệ.')
        cohort = ("SELECT SK_ID_CURR FROM application_split WHERE dataset_role='train'"
                  if scope == 'research' else
                  'SELECT source_application_id FROM demo_profiles WHERE is_archived=0')
        params = ()
        if scope == 'managed':
            ids = self.connector.queryDataset(cohort)['source_application_id'].tolist()
            cohort = ','.join(['%s'] * len(ids)) if ids else 'SELECT NULL WHERE FALSE'
            params = tuple(int(value) for value in ids)
        return self.connector.queryDataset(f'''SELECT SK_ID_CURR AS source_application_id,
            COUNT(*) AS previous_n, COUNT(DISTINCT SK_ID_PREV) AS unique_n,
            SUM(CASE WHEN NAME_CONTRACT_STATUS IN
                ('Approved','Refused','Canceled','Unused offer') THEN 1 ELSE 0 END) AS known_n,
            SUM(CASE WHEN NAME_CONTRACT_STATUS='Refused' THEN 1 ELSE 0 END) AS refused_n
            FROM raw_previous_application WHERE SK_ID_CURR IN ({cohort})
            AND DAYS_DECISION<0 GROUP BY SK_ID_CURR''', params)

    def getProfile(self, profile_id):
        return self.connector.queryDataset(
            PROFILE_SQL + ' WHERE p.profile_id=%s', (self.model_version, profile_id))

    def getFeatures(self, profile_ids):
        placeholders = ','.join(['%s'] * len(profile_ids))
        fields = ', '.join('f.`' + name + '`' for name in self.feature_order)
        data = self.connector.queryDataset(f'''
            SELECT p.profile_id, {fields} FROM demo_profiles AS p
            JOIN application_features AS f ON f.SK_ID_CURR=p.source_application_id
            WHERE p.profile_id IN ({placeholders}) AND p.is_archived=0
            ORDER BY p.profile_id''', tuple(profile_ids))
        data = data.set_index('profile_id')
        return data.loc[:, self.feature_order]

    def getSourceFeatures(self, source_id):
        return self.connector.queryDataset(
            'SELECT * FROM application_features WHERE SK_ID_CURR=%s', (source_id,))

    def getEvents(self, profile_id):
        return self.connector.queryDataset(
            'SELECT * FROM scoring_events WHERE profile_id=%s ORDER BY event_id DESC LIMIT 10',
            (profile_id,))

    def getNotes(self, profile_id):
        return self.connector.queryDataset('''SELECT n.*, e.profile_id FROM review_notes n
            JOIN scoring_events e USING(event_id) WHERE e.profile_id=%s ORDER BY n.note_id DESC''',
            (profile_id,))

    def getNoteProfile(self, note_id):
        return self.connector.queryDataset('''SELECT e.profile_id FROM review_notes n
            JOIN scoring_events e USING(event_id) WHERE n.note_id=%s''', (note_id,))

    def saveScores(self, data, scores, threshold):
        snapshots = data.astype(object).where(data.notna(), None).to_dict('index')
        rows = []
        for result in scores.itertuples():
            profile_id = result.Index
            snapshot = json.dumps(snapshots[profile_id], ensure_ascii=False, sort_keys=True,
                                  separators=(',', ':'), allow_nan=False)
            rows.append((int(profile_id), self.model_version, float(result.score),
                threshold, int(result.alert), hashlib.sha256(snapshot.encode()).hexdigest(), snapshot))
        return self.connector.executeMany('''INSERT INTO scoring_events
            (profile_id,model_version,score,threshold,alert,input_sha256,input_snapshot)
            VALUES (%s,%s,%s,%s,%s,%s,%s)''', rows)
