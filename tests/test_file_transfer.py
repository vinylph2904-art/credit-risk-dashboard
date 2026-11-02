from io import BytesIO
from pathlib import Path

import fitz
from flask import Flask
from openpyxl import Workbook, load_workbook
import pandas as pd
import pytest
from werkzeug.datastructures import FileStorage

from web.file_transfer import read_profile_file, excel_response, pdf_response


def upload_excel(rows, extra_sheet=False):
    book = Workbook()
    for row in rows:
        book.active.append(row)
    if extra_sheet:
        book.create_sheet('extra')
    stream = BytesIO()
    book.save(stream)
    stream.seek(0)
    return FileStorage(stream=stream, filename='profiles.xlsx')


def test_import_csv_and_excel_preserve_values():
    columns = ['source_application_id', 'case_label', 'assignee', 'review_status']
    values = ['100001', 'Hồ sơ cần đối chiếu', '', 'new']
    csv = pd.DataFrame([values], columns=columns).to_csv(index=False).encode('utf-8-sig')
    for upload in [FileStorage(stream=BytesIO(csv), filename='profiles.csv'), upload_excel([columns, values])]:
        frame = read_profile_file(upload)
        assert frame.columns.tolist() == columns
        assert frame.iloc[0].tolist() == values


@pytest.mark.parametrize('rows,extra_sheet', [([['id'], ['=1+1']], False), ([['id'], [1]], True)])
def test_excel_rejects_formulas_and_multiple_sheets(rows, extra_sheet):
    with pytest.raises(ValueError):
        read_profile_file(upload_excel(rows, extra_sheet))


@pytest.mark.parametrize('filename,content', [('bad.xls', b'bad'), ('bad.xlsx', b'bad'), ('bad.csv', b'')])
def test_invalid_files_have_validation_error(filename, content):
    with pytest.raises(ValueError):
        read_profile_file(FileStorage(stream=BytesIO(content), filename=filename))


def test_excel_export_keeps_untrusted_text_as_text():
    with Flask(__name__).test_request_context():
        response = excel_response(pd.DataFrame({'label': ['=1+1', '+SUM(A1)', 'Hồ sơ']}), 'profiles.xlsx')
        response.direct_passthrough = False
        book = load_workbook(BytesIO(response.get_data()))
        assert book.active['A2'].value == '=1+1'
        assert book.active['A2'].data_type == 's'
        assert book.active['A1'].font.name == 'Times New Roman'
        assert book.active['A2'].font.name == 'Times New Roman'
        assert book.active.freeze_panes == 'A2'


@pytest.mark.parametrize('count', [0, 150])
def test_pdf_export_unicode_and_pagination(count):
    columns = ['source_application_id', 'case_label', 'assignee', 'review_status',
               'is_archived', 'score', 'threshold', 'alert', 'AMT_CREDIT', 'scored_at']
    frame = pd.DataFrame([[100001 + i, 'Hồ sơ cần đối chiếu thu nhập', 'analyst', 'new',
                           0, .25, .148, 1, 123456, '2026-10-27 10:00:00'] for i in range(count)], columns=columns)
    with Flask(__name__).test_request_context():
        response = pdf_response(frame, 'profiles.pdf')
        response.direct_passthrough = False
        content = response.get_data()
    document = fitz.open(stream=content, filetype='pdf')
    text = ''.join(page.get_text() for page in document).replace('\xa0', ' ')
    assert 'Danh sách hồ sơ' in text
    assert any('TimesNewRoman' in font[3].replace(' ', '') for font in document[0].get_fonts())
    if count:
        assert len(document) > 1
        assert str(100000 + count) in text
        assert 'Hồ sơ cần đối chiếu' in text
        spans = [span for block in document[0].get_text('dict')['blocks'] if 'lines' in block
                 for line in block['lines'] for span in line['spans']]
        header_start = next(i for i, span in enumerate(spans) if span['text'].replace('\xa0', ' ') == 'Mã nguồn')
        headers = spans[header_start:header_start + 10]
        first_row = spans[header_start + 10:header_start + 20]
        for header, cell in zip(headers, first_row):
            assert header['bbox'][0] == pytest.approx(cell['bbox'][0], abs=.1)
            assert header['size'] == cell['size'] == 11
        destination = Path('tmp/file_transfer_qa')
        destination.mkdir(parents=True, exist_ok=True)
        (destination / 'profiles.pdf').write_bytes(content)
        document[0].get_pixmap(matrix=fitz.Matrix(1, 1)).save(destination / 'page1.png')
