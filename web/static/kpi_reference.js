function compareKpiReference(value, reference) {
  if (!Number.isFinite(value) || !Number.isFinite(reference)) return 'unavailable';
  const tolerance = Math.max(1, Math.abs(value), Math.abs(reference)) * 1e-10;
  if (Math.abs(value - reference) <= tolerance) return 'equal';
  return value > reference ? 'above' : 'below';
}

function formatKpiReference(value, unit) {
  if (!Number.isFinite(value)) return 'Chưa đủ dữ liệu';
  const percent = unit === 'percent';
  const formatted = new Intl.NumberFormat('vi-VN', {
    maximumFractionDigits: percent ? 2 : 3
  }).format(percent ? value * 100 : value);
  if (percent) return formatted + '%';
  if (unit === 'times') return formatted + ' lần';
  return formatted + ' đơn vị tiền nguồn';
}

function createKpiReferenceDialog() {
  const dialog = document.createElement('dialog');
  dialog.id = 'kpi-reference-info';
  dialog.setAttribute('aria-labelledby', 'reference-info-title');
  dialog.innerHTML='<div class="dialog-header"><h2 id="reference-info-title">Tham chiếu nội bộ</h2><button type="button" class="icon-button" aria-label="Đóng">×</button></div><div class="dialog-body"><p class="reference-values"></p><p class="reference-scope"></p><p>Cùng dataset và cùng nguồn dữ liệu; mốc tham chiếu được tính trên toàn phạm vi gốc trước bộ lọc phân khúc, theo cùng công thức của KPI. Đây không phải benchmark ngành, không phải tháng trước và không phải ngưỡng mô hình. Các chỉ số lịch sử không được coi là kết quả tín dụng hiện tại.</p><p>Đỏ/xanh ở tỷ lệ khó khăn chỉ nhấn mạnh cao/thấp hơn tham chiếu, không kết luận an toàn hay phê duyệt tín dụng. Các tỷ số và quy mô chỉ mang tính mô tả. Thiếu dữ liệu giữ trung tính.</p></div>';
  dialog.querySelector('button').onclick = () => dialog.close();
  document.body.append(dialog);
  return dialog;
}

function attachKpiReference(card, dialog) {
  const number = raw => raw === '' ? NaN : Number(raw);
  const value = number(card.dataset.levelValue);
  const base = number(card.dataset.referenceValue);
  const state = compareKpiReference(value, base);
  const key = card.dataset.financialKpi;
  card.dataset.level = 'neutral';
  if (card.dataset.referenceActive === '1' && ['rate', 'credit_share'].includes(key)) {
    card.dataset.level = {above: 'danger', below: 'good'}[state] || 'neutral';
  }
  const label = document.createElement('span');
  label.className = 'kpi-level-label';
  label.textContent = {
    above: 'Cao hơn tham chiếu', below: 'Thấp hơn tham chiếu',
    equal: 'Bằng tham chiếu', unavailable: 'Chưa đủ dữ liệu so sánh'
  }[state];
  if (card.dataset.referenceActive === '1') card.append(label);

  const format = value => formatKpiReference(value, card.dataset.levelUnit);
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'kpi-info-button';
  button.textContent = 'ⓘ';
  button.setAttribute('aria-label', 'Xem tham chiếu: ' + card.querySelector('.label').textContent);
  button.onclick = event => {
    event.preventDefault();
    event.stopPropagation();
    dialog.querySelector('h2').textContent = card.querySelector('.label').textContent;
    dialog.querySelector('.reference-values').textContent =
      'Đang xem: ' + format(value) + '. Tham chiếu nội bộ: ' + format(base) + '.';
    dialog.querySelector('.reference-scope').textContent =
      'Tập tham chiếu: ' + new Intl.NumberFormat('vi-VN').format(Number(card.dataset.referenceCount)) +
      ' hồ sơ. Mỗi KPI chỉ tính trên các hồ sơ đủ dữ liệu tương ứng.';
    dialog.showModal();
  };
  card.append(button);
}

function initializeKpiReference() {
  const root = document.querySelector('.page');
  if (!root) return;
  const cards = [...root.querySelectorAll('[data-reference-value]')];
  if (root._referenceFirst === cards[0]) return;
  root._referenceFirst = cards[0];
  document.getElementById('kpi-reference-info')?.remove();
  if (!cards.length) return;
  const dialog = createKpiReferenceDialog();
  cards.forEach(card => attachKpiReference(card, dialog));
}

document.addEventListener('DOMContentLoaded', () => {
  initializeKpiReference();
  new MutationObserver(initializeKpiReference).observe(document.body, {childList: true, subtree: true});
});
