"""Cache nghiên cứu phải giữ kết quả và không dùng lại phiên bản cũ."""
from pathlib import Path
from uuid import uuid4

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from web.report_cache import read_research_cache


@pytest.fixture
def tmp_path():
    # Thư mục test nằm trong workspace, không phụ thuộc quyền Temp của Windows.
    folder=Path(__file__).resolve().parents[1]/'tmp'/('report_cache_test_'+uuid4().hex)
    folder.mkdir(parents=True)
    return folder


def test_disk_cache_survives_another_call_and_preserves_values(tmp_path):
    original=pd.DataFrame({'source_application_id':[12,8,15], 'amount':[1.5,None,0.0],
                           'category':['A',None,'B'], 'count':[1,0,3]})
    first=read_research_cache(tmp_path,'version-1:portfolio',lambda:original)
    def no_database():
        raise AssertionError('Existing cache must avoid another database query')
    second=read_research_cache(tmp_path,'version-1:portfolio',no_database)
    assert_frame_equal(first,second)
    assert list(second.source_application_id)==[12,8,15]


def test_version_and_query_revision_change_cache_key(tmp_path):
    calls=[]
    def load(value):
        calls.append(value)
        return pd.DataFrame({'value':[value]})
    for key,value in [('query1:dataset1',1),('query1:dataset2',2),('query2:dataset2',3)]:
        assert read_research_cache(tmp_path,key,lambda:load(value)).iloc[0,0]==value
    assert calls==[1,2,3]


def test_corrupt_cache_is_rebuilt_without_using_stale_data(tmp_path):
    read_research_cache(tmp_path,'version',lambda:pd.DataFrame({'value':[1]}))
    path=next(tmp_path.glob('*.parquet'))
    path.write_bytes(b'incomplete cache')
    data=read_research_cache(tmp_path,'version',lambda:pd.DataFrame({'value':[2]}))
    assert data.iloc[0,0]==2
    assert pd.read_parquet(path).iloc[0,0]==2


def test_database_error_is_not_cached(tmp_path):
    def failed_query():
        raise ValueError('Unavailable data')
    with pytest.raises(ValueError):
        read_research_cache(tmp_path,'version',failed_query)
    assert not list(tmp_path.glob('*.parquet'))


def test_unwritable_cache_does_not_block_database_result(tmp_path):
    folder=tmp_path/'file-not-directory'
    folder.write_text('occupied')
    data=read_research_cache(folder,'version',lambda:pd.DataFrame({'value':[7]}))
    assert data.iloc[0,0]==7
