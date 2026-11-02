"""Nạp đặc trưng vào MySQL và đọc dữ liệu cho thực nghiệm mô hình."""
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


class HomeCreditModelData:
    def __init__(self, connector, schema):
        self.connector = connector
        self.schema = schema
        self.train = None

    def createTables(self, sql_path, data_version='home-credit-v1'):
        statements = Path(sql_path).read_text(encoding='utf-8').split(';')
        for sql in statements:
            if sql.strip():
                self.connector.execute(sql)

        sql = 'SELECT value FROM dataset_metadata WHERE name = %s'
        existing = self.connector.queryDataset(sql, ('data_version',))
        if existing.empty:
            sql = 'INSERT INTO dataset_metadata (name, value) VALUES (%s, %s)'
            self.connector.execute(sql, ('data_version', data_version))
        elif existing.iloc[0]['value'] != data_version:
            raise ValueError('CSDL hiện có thuộc phiên bản dữ liệu khác.')

    def readSplitIndex(self):
        sql = '''
            SELECT SK_ID_CURR, dataset_role AS split, cv_fold
            FROM application_split
            ORDER BY SK_ID_CURR
        '''
        return self.connector.queryDataset(sql)

    def importFeatures(self, features_dir, feature_index):
        existing = self.readSplitIndex()
        known = feature_index.loc[feature_index['SK_ID_CURR'].isin(existing['SK_ID_CURR'])]
        if not existing.empty:
            existing = existing.astype(feature_index.dtypes.to_dict())
            pd.testing.assert_frame_equal(known.reset_index(drop=True), existing)

        missing = feature_index.loc[~feature_index['SK_ID_CURR'].isin(existing['SK_ID_CURR'])]
        rows = list(missing.itertuples(index=False, name=None))
        sql = '''INSERT INTO application_split (SK_ID_CURR, dataset_role, cv_fold)
                 VALUES (%s, %s, %s)'''
        for start in range(0, len(rows), 2000):
            self.connector.executeMany(sql, rows[start:start + 2000])

        sql = 'SELECT SK_ID_CURR FROM application_features'
        existing_ids = self.connector.queryDataset(sql)['SK_ID_CURR']
        if not existing_ids.isin(feature_index['SK_ID_CURR']).all():
            raise ValueError('Bảng đặc trưng có ID ngoài bộ phân tập hiện tại.')

        columns = ', '.join('`' + name + '`' for name in self.schema.names)
        placeholders = ', '.join(['%s'] * len(self.schema))
        insert_sql = f'INSERT INTO application_features ({columns}) VALUES ({placeholders})'
        results = []
        for role in ['train', 'validation', 'test', 'application_test']:
            expected_ids = feature_index.loc[(feature_index['split'] == role), 'SK_ID_CURR']
            missing_ids = expected_ids.loc[~expected_ids.isin(existing_ids)]
            inserted = 0
            if not missing_ids.empty:
                path = Path(features_dir) / 'b' / (role + '.parquet')
                for batch in pq.ParquetFile(path).iter_batches(batch_size=1000):
                    frame = batch.to_pandas()
                    frame = frame.loc[frame['SK_ID_CURR'].isin(missing_ids)]
                    if frame.empty:
                        continue
                    values = frame.astype(object)
                    values = values.where(frame.notna(), None)
                    rows = list(values.itertuples(index=False, name=None))
                    inserted += self.connector.executeMany(insert_sql, rows)

            sql = '''
                SELECT COUNT(*) AS n
                FROM application_features f
                JOIN application_split s USING (SK_ID_CURR)
                WHERE s.dataset_role = %s
            '''
            count = int(self.connector.queryDataset(sql, (role,)).iloc[0]['n'])
            if count != len(expected_ids):
                raise ValueError('Số dòng đặc trưng không khớp phân tập: ' + role)
            results.append({'split': role, 'expected_n': len(expected_ids),
                            'mysql_n': count, 'inserted_this_run': inserted})
            print(role, ':', count, 'hồ sơ, thêm mới', inserted)
        return pd.DataFrame(results)

    def validateFeatures(self, features_dir):
        """Dừng trước CV nếu dữ liệu MySQL khác đầu ra Feature Engineering."""
        fields = ', '.join('f.`' + name + '`' for name in self.schema.names)
        results = []
        for role in ['train', 'validation', 'test', 'application_test']:
            path = Path(features_dir) / 'b' / (role + '.parquet')
            expected = pd.read_parquet(path).sort_values('SK_ID_CURR').reset_index(drop=True)
            sql = f'''SELECT {fields} FROM application_features f
                      JOIN application_split s USING (SK_ID_CURR)
                      WHERE s.dataset_role = %s ORDER BY f.SK_ID_CURR'''
            offset = 0
            for batch in self.connector.queryBatches(sql, (role,), batch_size=5000):
                frame = pa.Table.from_pandas(batch, schema=self.schema,
                                            preserve_index=False).to_pandas()
                reference = expected.iloc[offset:offset + len(frame)].reset_index(drop=True)
                if not frame.equals(reference):
                    raise ValueError(
                        'Dữ liệu MySQL khác Parquet ở tập ' + role +
                        '. Dừng trước CV; đối soát và nạp lại đặc trưng có chủ đích.')
                offset += len(frame)
            if offset != len(expected):
                raise ValueError('Số dòng MySQL khác Parquet ở tập ' + role)
            results.append({'split': role, 'verified_rows': offset,
                            'verified_features': len(self.schema) - 1,
                            'values_match': True})
        return pd.DataFrame(results)

    def readFeatures(self, role):
        if role == 'train' and self.train is not None:
            return self.train

        fields = ', '.join('f.`' + name + '`' for name in self.schema.names)
        sql = f'''
            SELECT {fields}
            FROM application_features f
            JOIN application_split s USING (SK_ID_CURR)
            WHERE s.dataset_role = %s
            ORDER BY f.SK_ID_CURR
        '''
        parts = []
        for batch in self.connector.queryBatches(sql, (role,), batch_size=5000):
            # Giữ đúng kiểu cột đã chốt ở notebook 04, kể cả cột thiếu toàn bộ.
            table = pa.Table.from_pandas(batch, schema=self.schema, preserve_index=False)
            parts.append(table.to_pandas())
        if not parts:
            raise ValueError('Không tìm thấy đặc trưng cho phân tập: ' + role)
        data = pd.concat(parts, ignore_index=True)
        data = data.set_index('SK_ID_CURR')
        if not data.index.is_unique:
            raise ValueError('ID đặc trưng bị trùng.')
        if role == 'train':
            self.train = data
        return data

    def readLabels(self, role):
        if role not in ['train', 'validation', 'test']:
            raise ValueError('Chỉ ba tập nội bộ có nhãn TARGET.')
        sql = '''
            SELECT a.SK_ID_CURR, a.TARGET
            FROM raw_application_train a
            JOIN application_split s USING (SK_ID_CURR)
            WHERE s.dataset_role = %s
            ORDER BY a.SK_ID_CURR
        '''
        data = self.connector.queryDataset(sql, (role,)).set_index('SK_ID_CURR')
        if not data.index.is_unique or data['TARGET'].isna().any():
            raise ValueError('Nhãn có ID trùng hoặc TARGET bị thiếu.')
        if not data['TARGET'].isin([0, 1]).all():
            raise ValueError('TARGET phải bằng 0 hoặc 1.')
        return data['TARGET'].astype('int8')

