let workspaceHeaderObserver;

function updateWorkspaceHeaderOffset() {
  const body = document.body;
  const header = document.querySelector('.topbar');
  if (!header) {
    body.style.removeProperty('--workspace-topbar-offset');
    return;
  }
  const offset = Math.ceil(header.getBoundingClientRect().bottom) + 12 + 'px';
  if (body.style.getPropertyValue('--workspace-topbar-offset') !== offset) {
    body.style.setProperty('--workspace-topbar-offset', offset);
  }
}

function initializeWorkspaceHeader() {
  workspaceHeaderObserver?.disconnect();
  updateWorkspaceHeaderOffset();
  const header = document.querySelector('.topbar');
  if (header && typeof ResizeObserver !== 'undefined') {
    workspaceHeaderObserver = new ResizeObserver(updateWorkspaceHeaderOffset);
    workspaceHeaderObserver.observe(header);
  }
}

function initializePage() {
initializeWorkspaceHeader();
  if (window.location.hash === '#assignment-summary') {
    const workload = document.getElementById('assignment-summary');
    if (workload) workload.open = true;
  }
  document.querySelectorAll('details.financial-extra, details.history-details').forEach(details => {
    details.addEventListener('toggle', () => requestAnimationFrame(() => resizeReportCanvas()));
  });
const pageRoot = document.querySelector('.page') || document;
initializeScenarios(pageRoot);
document.querySelectorAll('.page [data-report-navigation], .topbar [data-report-navigation]').forEach(select => {
  select.addEventListener('change', () => {
    if (!filtersHaveDraft()) updateDashboard(select.value);
  });
});
// Tương tác giao diện; các thao tác lưu/chấm điểm đều gửi đến Flask.
pageRoot.querySelectorAll('form[data-auto-filter]').forEach(form => {
  form.querySelectorAll('select').forEach(select => {
    select.addEventListener('change', () => form.requestSubmit());
  });
});

// Mục tiêu minh họa chỉ dùng để so sánh trên giao diện, không đổi model/ngưỡng.
initializeKpiTargets(pageRoot);

pageRoot.querySelectorAll('form[data-confirm]').forEach(form => {
  form.addEventListener('submit', event => {
    if (!window.confirm(form.dataset.confirm)) event.preventDefault();
  });
});
const selectAll = document.getElementById('select-all');
const checkboxes = pageRoot.querySelectorAll('.row-checkbox:not(:disabled)');
const batchBar = document.getElementById('batch-actions');
function updateSelection() {
  const selected = pageRoot.querySelectorAll('.row-checkbox:checked:not(:disabled)').length;
  if (!batchBar) return;
  batchBar.hidden = selected === 0;
  document.getElementById('selected-count').textContent = selected;
  if (selectAll) {
    selectAll.checked = selected === checkboxes.length && selected > 0;
    selectAll.indeterminate = selected > 0 && selected < checkboxes.length;
  }
}
if (selectAll) selectAll.addEventListener('change', () => {
  checkboxes.forEach(box => { if (!box.disabled) box.checked = selectAll.checked; });
  updateSelection();
});
checkboxes.forEach(box => box.addEventListener('change', updateSelection));
const clearSelection = document.getElementById('clear-selection');
if (clearSelection) clearSelection.addEventListener('click', () => {
  checkboxes.forEach(box => { box.checked = false; });
  updateSelection();
});
const featureSearch = document.getElementById('feature-search');
if (featureSearch) featureSearch.addEventListener('input', () => {
  const query = featureSearch.value.toLocaleLowerCase('vi');
  pageRoot.querySelectorAll('#feature-table tbody tr').forEach(row => {
    row.hidden = !row.textContent.toLocaleLowerCase('vi').includes(query);
  });
});
document.querySelectorAll('.page [data-print], .topbar [data-print]').forEach(button => {
  button.addEventListener('click', () => window.print());
});
pageRoot.querySelectorAll('form[data-loading]').forEach(form => {
  form.addEventListener('submit', () => {
    const button = form.querySelector('button[type="submit"]');
    if (button) { button.disabled = true; button.textContent = 'Đang xử lý…'; }
  });
});

// Tổng quan: giữ nguyên chỉ số đang xem cho đến khi bấm Áp dụng.
const cohortForm = document.getElementById('cohort-filter-form');
if (cohortForm) {
  const notice = document.getElementById('cohort-draft-notice');
  function markCohortDraft() {
    pageRoot.dataset.filterDirty = 'true';
    if (notice) notice.hidden = false;
  }
  cohortForm.addEventListener('input', markCohortDraft);
  cohortForm.addEventListener('change', markCohortDraft);
}

initializeReportCanvas();
}
document.querySelectorAll('[data-menu]').forEach(button => {
  button.addEventListener('click', () => {
    const open = document.body.classList.toggle('menu-open');
    document.querySelector('.mobile-menu').setAttribute('aria-expanded', String(open));
  });
});

initializePage();

document.addEventListener('keydown', event => {
  if (event.key !== 'Escape') return;
  document.querySelectorAll('.report-menu[open]').forEach(menu => {
    menu.removeAttribute('open');
    menu.querySelector('summary').focus();
  });
});

// Biểu đồ và bộ lọc dùng chung một phạm vi; cập nhật phần nội dung, giữ nguyên trang.
document.addEventListener('click', event => {
  if (event.target.closest('[data-cohort-link]') && filtersHaveDraft()) {
    event.preventDefault();
    return;
  }
  if (event.target.closest('.queue-tabs a[href="#assignment-summary"]')) {
    document.getElementById('assignment-summary').open = true;
  }
  const opener = event.target.closest('[data-open]');
  if (opener) {
    const dialog = document.getElementById(opener.dataset.open);
    if (dialog) {
      event.preventDefault();
      opener.closest('.report-menu')?.removeAttribute('open');
      if (!dialog.open) dialog.showModal();
      requestAnimationFrame(() => resizeReportCanvas(dialog));
    }
    return;
  }
  if (event.target.tagName === 'DIALOG') {
    const box = event.target.getBoundingClientRect();
    if (event.clientX < box.left || event.clientX > box.right ||
        event.clientY < box.top || event.clientY > box.bottom) event.target.close();
  }
  document.querySelectorAll('.report-menu[open]').forEach(menu => {
    if (!menu.contains(event.target)) menu.removeAttribute('open');
  });
  const cohortLink = event.target.closest('a[data-cohort-link]');
  const profileRow = event.target.closest('[data-profile-href]');
  if (profileRow && !event.defaultPrevented && !event.target.closest('a,button,input,select,textarea,label')) {
    if (!filtersHaveDraft()) window.location.assign(profileRow.dataset.profileHref);
  }
  const close = event.target.closest('[data-close]');
  if (close) close.closest('dialog').close();
  const paging = event.target.closest('[data-detail-page]');
  if (paging && detailUrl) {
    openChartDetails(detailUrl.searchParams.get('kind'), detailUrl.searchParams.get('value'),
      Number(paging.dataset.detailPage));
  }
  const drill = event.target.closest('[data-drill-kind]');
  if (drill) {
    event.preventDefault();
    openChartDetails(drill.dataset.drillKind, drill.dataset.drillValue);
  }
  const link = event.target.closest('a[data-dashboard-nav]');
  if (link && !event.defaultPrevented && !event.ctrlKey && !event.metaKey && !event.shiftKey) {
    event.preventDefault();
    if (!filtersHaveDraft()) updateDashboard(link.href);
  }
  if (cohortLink && !event.defaultPrevented && event.button === 0 &&
      !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey &&
      !cohortLink.hasAttribute('download') && (!cohortLink.target || cohortLink.target === '_self')) {
    showDashboardMessage('Đang chuẩn bị dữ liệu…', true);
    document.querySelector('.page').setAttribute('aria-busy', 'true');
  }
});
document.addEventListener('keydown', event => {
  if (event.key !== 'Enter' || !event.target.matches('[data-profile-href]')) return;
  event.preventDefault();
  if (!filtersHaveDraft()) window.location.assign(event.target.dataset.profileHref);
});
document.addEventListener('submit', event => {
  const form = event.target;
  if (form.id !== 'cohort-filter-form' || !window.Plotly ||
      !['/', '/payments', '/risk'].includes(window.location.pathname)) return;
  event.preventDefault();
  const url = new URL(form.action);
  url.search = new URLSearchParams(new FormData(form)).toString();
  form.closest('dialog')?.close();
  updateDashboard(url);
});
document.addEventListener('toggle', event => {
  if (event.target.tagName === 'DETAILS' && event.target.open && window.Plotly) {
    event.target.querySelectorAll('.dashboard-chart').forEach(chart => {
      if (chart.data) Plotly.Plots.resize(chart);
    });
  }
}, true);
window.addEventListener('popstate', () => {
  if (['/', '/payments', '/risk'].includes(window.location.pathname) && window.Plotly) {
    updateDashboard(window.location.href, false);
  } else {
    window.location.reload();
  }
});
window.addEventListener('resize', () => {
  updateWorkspaceHeaderOffset();
  cancelAnimationFrame(reportResizeFrame);
  reportResizeFrame = requestAnimationFrame(() => resizeReportCanvas());
});
window.addEventListener('pageshow', event => {
  if (event.persisted) {
    showDashboardMessage('');
    document.querySelector('.page').removeAttribute('aria-busy');
  }
});
renderDashboardCharts().catch(() => showDashboardMessage('Không tải được biểu đồ. Tải lại trang để thử lại.'));

