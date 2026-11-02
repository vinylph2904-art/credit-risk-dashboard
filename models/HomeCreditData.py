"""Đọc dữ liệu nguồn từ MySQL và dùng lại trong phiên phân tích."""
import gc

import numpy as np
import pandas as pd


class HomeCreditData:
    def __init__(self, connector):
        self.connector = connector
        self.table_names = [
            'application_train', 'application_test', 'bureau', 'bureau_balance',
            'previous_application', 'pos_cash_balance', 'installments_payments',
            'credit_card_balance'
        ]
        self.columns = None
        self.application = None
        self.scoring = None
        self.bureau_links = None
        self.previous_links = None
        self.preview = {}
        self.overview = None
        self.key_checks = None
        self.relationships = None

    def loadColumns(self):
        if self.columns is not None:
            return self.columns

        sql = '''
            SELECT TABLE_NAME AS raw_table, COLUMN_NAME AS `column`,
                   DATA_TYPE AS dtype
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME LIKE 'raw_%'
              AND COLUMN_NAME <> '_source_row'
            ORDER BY TABLE_NAME, ORDINAL_POSITION
        '''
        columns = self.connector.queryDataset(sql)
        columns['table'] = columns['raw_table'].str.removeprefix('raw_')
        columns = columns.loc[columns['table'].isin(self.table_names)]
        if set(columns['table']) != set(self.table_names):
            raise ValueError('CSDL chưa có đủ tám bảng raw_*.')

        self.columns = columns[['table', 'column', 'dtype']].reset_index(drop=True)
        return self.columns

    def _selectColumns(self, table_name, columns):
        # Tên bảng/cột phải có trong metadata, không lấy trực tiếp từ input tự do.
        if table_name not in self.table_names:
            raise ValueError('Tên bảng nguồn không hợp lệ.')
        metadata = self.loadColumns()
        table_columns = metadata.loc[metadata['table'] == table_name, 'column'].tolist()
        if columns is None:
            columns = table_columns
        if not columns or not set(columns).issubset(table_columns):
            raise ValueError('Cột không có trong bảng nguồn.')

        sql_columns = []
        for column in columns:
            sql_columns.append(f'`{column}`')
        return ', '.join(sql_columns)

    def _convertTypes(self, data, table_name):
        # DOUBLE toàn NULL vẫn là float; biến phân loại thiếu dùng NaN.
        metadata = self.loadColumns()
        metadata = metadata.loc[metadata['table'] == table_name]
        column_types = metadata.set_index('column')['dtype'].to_dict()
        for column in data.columns:
            dtype = column_types[column]
            if dtype == 'double':
                data[column] = data[column].astype('float64')
            elif dtype == 'bigint':
                if data[column].isna().any():
                    data[column] = data[column].astype('float64')
                else:
                    data[column] = data[column].astype('int64')
            else:
                data[column] = data[column].astype(object)
                data[column] = data[column].where(data[column].notna(), np.nan)
        return data

    def readTable(self, table_name, columns=None):
        sql_columns = self._selectColumns(table_name, columns)
        sql = f'SELECT {sql_columns} FROM `raw_{table_name}` ORDER BY _source_row'
        parts = []
        for batch in self.connector.queryBatches(sql):
            parts.append(batch)
        data = pd.concat(parts, ignore_index=True)
        return self._convertTypes(data, table_name)

    def loadApplications(self):
        if self.application is None:
            self.application = self.readTable('application_train')
        if self.scoring is None:
            self.scoring = self.readTable('application_test')
        return self.application, self.scoring

    def getPreview(self, table_name, n=5):
        if n <= 0:
            raise ValueError('Số dòng xem trước phải lớn hơn 0.')
        if table_name == 'application_train' and self.application is not None:
            return self.application.head(n)
        if table_name == 'application_test' and self.scoring is not None:
            return self.scoring.head(n)

        cache_key = (table_name, n)
        if cache_key not in self.preview:
            sql_columns = self._selectColumns(table_name, None)
            sql = f'SELECT {sql_columns} FROM `raw_{table_name}` ORDER BY _source_row LIMIT %s'
            data = self.connector.queryDataset(sql, (n,))
            self.preview[cache_key] = self._convertTypes(data, table_name)
        return self.preview[cache_key]

    def processOverview(self):
        if self.overview is not None:
            return self.overview
        metadata = self.loadColumns()
        rows = []
        for table_name in self.table_names:
            sql = f'SELECT COUNT(*) AS n FROM `raw_{table_name}`'
            row_count = int(self.connector.queryDataset(sql).iloc[0]['n'])
            column_count = int((metadata['table'] == table_name).sum())
            rows.append({
                'table': table_name,
                'rows': row_count,
                'columns': column_count
            })
        self.overview = pd.DataFrame(rows)
        return self.overview

    def _checkRelationship(self, table_name, history, current_ids, bureau_owner, previous_owner):
        missing_parent = 0
        owner_conflicts = 0
        if table_name == 'bureau_balance':
            owners = history['SK_ID_BUREAU'].map(bureau_owner)
            missing_parent = int(owners.isna().sum())
        else:
            owners = history['SK_ID_CURR']
            if 'SK_ID_PREV' in history.columns:
                parent_owners = history['SK_ID_PREV'].map(previous_owner)
                missing_parent = int(parent_owners.isna().sum())
                conflicts = parent_owners.notna() & (parent_owners != owners)
                owner_conflicts = int(conflicts.sum())

        known_owners = owners.dropna().astype('int64')
        in_scope = known_owners.isin(current_ids)
        return {
            'table': table_name,
            'missing_parent_rows': missing_parent,
            'owner_conflict_rows': owner_conflicts,
            'unresolved_owner_rows': int(owners.isna().sum()),
            'outside_scope_rows': int((~in_scope).sum()),
            'applications_with_history': int(known_owners.loc[in_scope].nunique()),
            'total_applications': len(current_ids)
        }

    def processKeyChecks(self, candidate_keys):
        if self.key_checks is not None:
            return self.key_checks
        self.loadApplications()
        if self.bureau_links is None:
            self.bureau_links = self.readTable('bureau', ['SK_ID_BUREAU', 'SK_ID_CURR'])
        if self.previous_links is None:
            self.previous_links = self.readTable('previous_application', ['SK_ID_PREV', 'SK_ID_CURR'])
        bureau_owner = self.bureau_links.set_index('SK_ID_BUREAU')['SK_ID_CURR']
        previous_owner = self.previous_links.set_index('SK_ID_PREV')['SK_ID_CURR']
        current_ids = pd.concat([self.application['SK_ID_CURR'], self.scoring['SK_ID_CURR']])
        key_rows = []
        relationship_rows = []

        for table_name, key_columns in candidate_keys.items():
            if table_name == 'application_train':
                data = self.application
            elif table_name == 'application_test':
                data = self.scoring
            elif table_name == 'bureau':
                data = self.bureau_links
            elif table_name == 'previous_application':
                data = self.previous_links
            else:
                columns = list(key_columns)
                if table_name != 'bureau_balance' and 'SK_ID_CURR' not in columns:
                    columns.append('SK_ID_CURR')
                data = self.readTable(table_name, columns)

            keys = data[key_columns]
            key_rows.append({
                'table': table_name,
                'key': ', '.join(key_columns),
                'rows': len(data),
                'missing_key_rows': int(keys.isna().any(axis=1).sum()),
                'duplicate_key_rows': int(keys.duplicated().sum()),
                'expected_unique': table_name != 'installments_payments'
            })
            if not table_name.startswith('application'):
                relationship_rows.append(self._checkRelationship(
                    table_name, data, current_ids, bureau_owner, previous_owner))
            print(table_name, ': đã kiểm tra', len(data), 'dòng', flush=True)
            del data, keys
            gc.collect()

        self.key_checks = pd.DataFrame(key_rows)
        self.relationships = pd.DataFrame(relationship_rows)
        self.relationships['coverage_pct'] = (
            100 * self.relationships['applications_with_history']
            / self.relationships['total_applications']
        )
        return self.key_checks

    def processRelationships(self):
        if self.relationships is None:
            raise ValueError('Chạy processKeyChecks trước để kiểm tra trên cùng dữ liệu.')
        return self.relationships

    def saveSplit(self, split_ids):
        """Lưu ID và phân tập, giữ nguyên các bản ghi đã có trong CSDL."""
        sql = '''CREATE TABLE IF NOT EXISTS application_split (
            SK_ID_CURR BIGINT PRIMARY KEY,
            dataset_role VARCHAR(24) NOT NULL,
            cv_fold SMALLINT NOT NULL,
            INDEX ix_role(dataset_role)
        ) ENGINE=InnoDB'''
        self.connector.execute(sql)
        scoring_split = self.scoring[['SK_ID_CURR']].copy()
        scoring_split['split'] = 'application_test'
        scoring_split['cv_fold'] = -1
        expected = pd.concat([split_ids, scoring_split], ignore_index=True)
        expected = expected.sort_values('SK_ID_CURR').reset_index(drop=True)
        if not expected['SK_ID_CURR'].is_unique:
            raise ValueError('ID phân tập bị trùng.')

        sql = '''SELECT SK_ID_CURR, dataset_role AS split, cv_fold
                 FROM application_split ORDER BY SK_ID_CURR'''
        existing = self.connector.queryDataset(sql)
        existing_ids = existing['SK_ID_CURR']
        if not existing_ids.isin(expected['SK_ID_CURR']).all():
            raise ValueError('CSDL có ID ngoài bộ phân tập hiện tại.')
        known = expected.loc[expected['SK_ID_CURR'].isin(existing_ids)].reset_index(drop=True)
        if not existing.empty:
            existing = existing.astype(expected.dtypes.to_dict())
            pd.testing.assert_frame_equal(existing, known)

        missing = expected.loc[~expected['SK_ID_CURR'].isin(existing_ids)]
        if not missing.empty:
            rows = list(missing.itertuples(index=False, name=None))
            sql = '''INSERT INTO application_split (SK_ID_CURR, dataset_role, cv_fold)
                     VALUES (%s, %s, %s)'''
            self.connector.executeMany(sql, rows)
        return len(expected)
