"""Read profile imports and format downloadable Excel/PDF lists."""
from io import BytesIO
from html import escape
from zipfile import BadZipFile
from pathlib import Path

import fitz
from flask import send_file
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
import pandas as pd


def read_profile_file(upload):
    extension = upload.filename.lower().rsplit('.', 1)[-1]
    if extension not in ['csv', 'xlsx']:
        raise ValueError('Chọn file CSV UTF-8 hoặc Excel .xlsx theo mẫu.')
    stream = BytesIO(upload.read())
    try:
        if extension == 'csv':
            return pd.read_csv(stream, dtype=str, keep_default_na=False,
                               encoding='utf-8-sig', nrows=1001)
        workbook = load_workbook(stream, read_only=True, data_only=False, keep_links=False)
        try:
            if len(workbook.worksheets) != 1:
                raise ValueError('File Excel nhập cần đúng một sheet theo mẫu.')
            rows = []
            for row in workbook.active.iter_rows():
                if any(cell.data_type == 'f' for cell in row):
                    raise ValueError('File Excel nhập cần giá trị, không chứa công thức.')
                rows.append(['' if cell.value is None else str(cell.value) for cell in row])
                if len(rows) > 1001:
                    break
            if not rows:
                raise ValueError('File nhập không có dữ liệu.')
            return pd.DataFrame(rows[1:], columns=rows[0])
        finally:
            workbook.close()
    except (UnicodeError, pd.errors.ParserError, pd.errors.EmptyDataError, BadZipFile, OSError, KeyError):
        raise ValueError('Không đọc được file. Dùng mẫu CSV UTF-8 hoặc Excel .xlsx hợp lệ.') from None


def excel_response(frame, filename):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'Ho so'
    sheet.append(list(frame.columns))
    for row in frame.astype(object).where(frame.notna(), None).itertuples(index=False, name=None):
        sheet.append(row)
        for cell in sheet[sheet.max_row]:
            cell.font = Font(name='Times New Roman', size=11)
            if isinstance(cell.value, str):
                # User text remains text, including leading '='; never create formulas.
                cell.data_type = 's'
            if frame.columns[cell.column - 1] in ['score', 'threshold'] and cell.data_type == 'n':
                cell.number_format = '0.00%'
    for cell in sheet[1]:
        cell.font = Font(name='Times New Roman', size=11, bold=True, color='FFFFFF')
        cell.fill = PatternFill('solid', fgColor='B51C31')
        cell.alignment = Alignment(wrap_text=True, vertical='center')
    sheet.row_dimensions[1].height = 30
    for column in sheet.columns:
        letter = column[0].column_letter
        sheet.column_dimensions[letter].width = min(42, max(18, max(len(str(c.value or '')) for c in column) + 2))
    sheet.freeze_panes = 'A2'
    sheet.auto_filter.ref = sheet.dimensions
    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    return send_file(output, as_attachment=True, download_name=filename,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


def pdf_response(frame, filename):
    labels = ['Mã nguồn', 'Tên hồ sơ', 'Phụ trách', 'Trạng thái', 'Lưu trữ',
              'Score', 'Ngưỡng', 'Cảnh báo', 'Giá trị khoản vay', 'Chấm điểm (UTC)']
    headers = ''.join('<th>' + escape(label) + '</th>' for label in labels)
    rows = []
    for row in frame.itertuples(index=False, name=None):
        cells = []
        for column, value in zip(frame.columns, row):
            if pd.isna(value):
                text = '-'
            elif column in ['score', 'threshold']:
                text = f'{float(value):.2%}'
            elif column == 'AMT_CREDIT':
                text = f'{float(value):,.1f}'
            elif column == 'review_status':
                text = {'new':'Mới', 'in_review':'Đang xem xét', 'reviewed':'Đã rà soát'}.get(value, str(value))
            elif column in ['source_application_id', 'is_archived', 'alert']:
                text = str(int(value))
            else:
                text = str(value)
            cells.append('<td>' + escape(text) + '</td>')
        rows.append('<tr>' + ''.join(cells) + '</tr>')
    html = '<h1>Danh sách hồ sơ</h1><p>Home Credit Analytics | ' + str(len(frame)) + ' hồ sơ sau lọc</p>'
    html += '<p>Score hỗ trợ rà soát, không tự duyệt/từ chối. Tiền theo đơn vị nguồn. Thời gian chấm: UTC.</p>'
    html += '<table><thead><tr>' + headers + '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table>'
    if frame.empty:
        html += '<p>Không có hồ sơ phù hợp bộ lọc.</p>'
    font_directory = Path(__file__).parent / 'assets/fonts'
    story = fitz.Story(html=html, archive=fitz.Archive(str(font_directory)),
                       user_css='@font-face{font-family:ExportTimes;src:url(times.ttf)}'
                       '@font-face{font-family:ExportTimes;src:url(timesbd.ttf);font-weight:bold}'
                       'body{font-family:ExportTimes;font-size:11pt;color:#253449}'
                       'h1{font-size:20pt;color:#b51c31}p{font-size:11pt}'
                       'table{width:100%;border-collapse:collapse}th{background:#f4e9ec;color:#8b1b30}'
                       'th,td{text-align:left;font-size:11pt;line-height:1.4;'
                       'border-bottom:1px solid #dde3e9;padding:8px 6px;vertical-align:top;overflow-wrap:anywhere}')
    output = BytesIO()
    writer = fitz.DocumentWriter(output)
    page = fitz.paper_rect('a3-l')
    area = page + (28, 28, -28, -38)
    more = True
    while more:
        device = writer.begin_page(page)
        more, _ = story.place(area)
        story.draw(device)
        writer.end_page()
    writer.close()
    document = fitz.open(stream=output.getvalue(), filetype='pdf')
    for index, sheet in enumerate(document):
        sheet.insert_font(fontname='ExportTimes', fontfile=str(font_directory / 'times.ttf'))
        sheet.insert_text((sheet.rect.width - 100, sheet.rect.height - 18),
                          f'{index + 1} / {len(document)}', fontsize=9, fontname='ExportTimes')
    result = BytesIO(document.tobytes())
    document.close()
    return send_file(result, as_attachment=True, download_name=filename, mimetype='application/pdf')
