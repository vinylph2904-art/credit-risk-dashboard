function initializeKpiTargets(pageRoot) {
const kpiItems = pageRoot.querySelectorAll('[data-kpi]');
const targetForm = document.getElementById('kpi-target-form');
if (targetForm && kpiItems.length) {
  const params = new URLSearchParams(window.location.search);
  const scopeFields = ['product', 'income', 'amount_min', 'amount_max', 'age_min',
    'age_max', 'availability', 'currency', 'credit_status', 'financial_filter',
    'source', 'months', 'from_state', 'to_state', 'archived', 'drill_kind', 'drill_value'];
  const scope = [window.location.pathname];
  scopeFields.forEach(name => scope.push([name, params.get(name) || '']));
  const storageKey = 'home-credit-kpi-targets:' + JSON.stringify(scope);
  const error = document.getElementById('kpi-target-error');
  let targets = {};
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) || '{}');
    if (saved && typeof saved === 'object' && !Array.isArray(saved)) targets = saved;
  } catch (error) {
    targets = {};
  }

  function displayTargets() {
    kpiItems.forEach(item => {
      const target = targets[item.dataset.kpi];
      item.classList.remove('target-met', 'target-missed');
      if (!target || !Number.isFinite(target.value) || target.value < 0 ||
          !['minimum', 'maximum'].includes(target.direction)) {
        item.hidden = true;
        return;
      }
      item.hidden = false;
      const unit = item.dataset.unit === 'percent' ? '%' :
        (item.dataset.unit === 'count' ? 'hồ sơ / kỳ' : item.dataset.currency);
      const format = new Intl.NumberFormat('vi-VN', {maximumFractionDigits: 4});
      const sign = target.direction === 'minimum' ? '≥' : '≤';
      const label = `Mục tiêu demo ${sign} ${format.format(target.value)} ${unit}. `;
      if (item.dataset.value === '') {
        item.textContent = label + 'Chưa đủ dữ liệu để so sánh.';
        return;
      }
      let current = Number(item.dataset.value);
      if (item.dataset.unit === 'percent') current *= 100;
      // Khớp độ chính xác hiển thị, tránh báo "thấp hơn 0" do số thực.
      const difference = Number((current - target.value).toFixed(4));
      const differenceUnit = item.dataset.unit === 'percent' ? 'đpt' : unit;
      const met = target.direction === 'minimum' ? difference >= 0 : difference <= 0;
      let comparison = 'Bằng mục tiêu';
      if (difference > 0) comparison = `Cao hơn ${format.format(difference)} ${differenceUnit}`;
      if (difference < 0) comparison = `Thấp hơn ${format.format(-difference)} ${differenceUnit}`;
      item.textContent = label + comparison + (met ? ' · Đạt' : ' · Chưa đạt');
      item.classList.add(met ? 'target-met' : 'target-missed');
    });
  }

  kpiItems.forEach(item => {
    const key = item.dataset.kpi;
    const group = document.createElement('div');
    group.className = 'target-field';
    const label = document.createElement('label');
    label.htmlFor = 'target-' + key;
    label.textContent = item.dataset.label;
    const fields = document.createElement('div');
    fields.className = 'target-inputs';
    const direction = document.createElement('select');
    direction.name = key + '-direction';
    direction.setAttribute('aria-label', 'Hướng mục tiêu: ' + item.dataset.label);
    direction.add(new Option('Tối thiểu (≥)', 'minimum'));
    direction.add(new Option('Không vượt (≤)', 'maximum'));
    const input = document.createElement('input');
    input.type = 'number';
    input.id = 'target-' + key;
    input.name = key;
    input.min = '0';
    input.step = item.dataset.unit === 'count' ? '1' : 'any';
    input.placeholder = 'Chưa đặt mục tiêu';
    const target = targets[key];
    if (target && Number.isFinite(target.value) && target.value >= 0 &&
        ['minimum', 'maximum'].includes(target.direction)) {
      input.value = target.value;
      direction.value = target.direction;
    }
    const note = document.createElement('small');
    note.textContent = item.dataset.unit === 'percent' ? 'Nhập %, ví dụ 95 tương ứng 95%.' :
      (item.dataset.unit === 'count' ? 'Đơn vị: số hồ sơ hoặc nhóm kỳ theo thẻ KPI.' :
        'Đơn vị tiền nguồn: ' + item.dataset.currency);
    fields.append(direction, input);
    group.append(label, fields, note);
    document.getElementById('kpi-target-fields').append(group);
  });

  targetForm.addEventListener('submit', event => {
    event.preventDefault();
    const updated = {};
    kpiItems.forEach(item => {
      const key = item.dataset.kpi;
      const input = targetForm.elements.namedItem(key);
      if (input.value !== '') {
        updated[key] = {value: Number(input.value),
          direction: targetForm.elements.namedItem(key + '-direction').value};
      }
    });
    try {
      localStorage.setItem(storageKey, JSON.stringify(updated));
    } catch (storageError) {
      error.textContent = 'Trình duyệt chưa cho lưu mục tiêu. Hãy bật lưu trữ cho trang này rồi thử lại.';
      error.hidden = false;
      return;
    }
    targets = updated;
    error.hidden = true;
    displayTargets();
    document.getElementById('kpi-targets').close();
  });
  document.getElementById('kpi-targets').addEventListener('close', () => {
    // Hủy/đóng hộp thoại bỏ các chỉnh sửa chưa lưu.
    kpiItems.forEach(item => {
      const key = item.dataset.kpi;
      const target = targets[key];
      const valid = target && Number.isFinite(target.value) && target.value >= 0 &&
        ['minimum', 'maximum'].includes(target.direction);
      targetForm.elements.namedItem(key).value = valid ? target.value : '';
      targetForm.elements.namedItem(key + '-direction').value = valid ? target.direction : 'minimum';
    });
    error.hidden = true;
  });
  displayTargets();
}

}
