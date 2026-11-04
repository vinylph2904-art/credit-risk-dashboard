let pageRequest;
let detailRequest;
let detailUrl;
function skeletonMarkup(kind = 'table') {
  const line = '<span class="loading-line"></span>';
  const card = `<div class="loading-card">${line}${line}${line}</div>`;
  const row = `<div class="loading-table-row">${line}${line}${line}${line}</div>`;
  const table = `<div class="loading-table">${row.repeat(7)}</div>`;
  if (kind === 'table') return `<div class="loading-skeleton" aria-hidden="true">${table}</div>`;
  const chart = `<div class="loading-card loading-chart">${line}<div class="loading-bars">${line.repeat(7)}</div></div>`;
  return `<div class="loading-skeleton" aria-hidden="true"><div class="loading-heading">${line}${line}</div>
    <div class="loading-kpis">${card.repeat(4)}</div><div class="loading-charts">${chart.repeat(3)}</div>${table}</div>`;
}

function setPageSkeleton(loading) {
  const page = document.querySelector('.page');
  if (!page) return;
  page.classList.toggle('page-loading', loading);
  page.querySelector(':scope > .page-loading-overlay')?.remove();
  if (!loading) {
    page.removeAttribute('aria-busy');
    return;
  }
  page.setAttribute('aria-busy', 'true');
  const overlay = document.createElement('div');
  overlay.className = 'page-loading-overlay';
  overlay.innerHTML = '<span class="loading-accessible" role="status">Đang tải nội dung…</span>' + skeletonMarkup('page');
  page.append(overlay);
}

function setLoadingState(element, loading, message = 'Đang tải dữ liệu…',
    slowMessage = 'Đang tổng hợp số liệu theo bộ lọc…') {
  element.classList.toggle('is-loading', loading);
  if (loading) {
    element.setAttribute('aria-busy', 'true');
    const label = document.createElement('span');
    label.className = 'loading-accessible';
    label.setAttribute('role', 'status');
    label.textContent = message;
    element.innerHTML = skeletonMarkup();
    element.prepend(label);
  } else element.removeAttribute('aria-busy');
}

function filtersHaveDraft() {
  const page = document.querySelector('.page');
  if (page.dataset.filterDirty !== 'true') return false;
  openReportFilters();
  document.getElementById('cohort-draft-notice')?.focus();
  return true;
}

function showDashboardMessage(message, loading = false) {
  const status = document.getElementById('dashboard-status');
  setPageSkeleton(loading);
  status.classList.remove('is-loading');
  status.textContent = message;
  status.hidden = loading || !message;
}

async function updateDashboard(target, pushHistory = true) {
  const url = new URL(target, window.location.href);
  if (url.origin !== window.location.origin || url.pathname !== window.location.pathname) {
    if (url.origin === window.location.origin) {
      showDashboardMessage('Đang chuẩn bị dữ liệu…', true);
      document.querySelector('.page').setAttribute('aria-busy', 'true');
    }
    window.location.assign(url);
    return;
  }
  if (pageRequest) pageRequest.abort();
  const controller = new AbortController();
  pageRequest = controller;
  const page = document.querySelector('.page');
  page.setAttribute('aria-busy', 'true');
  if (detailRequest) detailRequest.abort();
  showDashboardMessage('Đang chuẩn bị dữ liệu…', true);
  try {
    const response = await fetch(url, {signal: controller.signal, cache: 'no-store'});
    if (response.redirected && new URL(response.url).pathname === '/login') {
      window.location.assign(response.url);
      return;
    }
    if (!response.ok) throw new Error('Không tải được phân tích. Kiểm tra lại bộ lọc hoặc thử lại.');
    const html = await response.text();
    if (controller.signal.aborted) return;
    const next = new DOMParser().parseFromString(html, 'text/html');
    const currentAssets = [...document.querySelectorAll('script[src],link[rel="stylesheet"]')]
      .map(node => node.getAttribute('src') || node.getAttribute('href'));
    const nextAssets = [...next.querySelectorAll('script[src],link[rel="stylesheet"]')]
      .map(node => node.getAttribute('src') || node.getAttribute('href'));
    if (currentAssets.join('|') !== nextAssets.join('|')) {
      window.location.assign(url);
      return;
    }
    const content = next.querySelector('.page');
    if (!content) throw new Error('Không tải được nội dung.');
    document.querySelectorAll('.compact-chart-tooltip').forEach(node => node.remove());
    page.querySelectorAll('.dashboard-chart').forEach(chart => Plotly.purge(chart));
    page.replaceChildren(...content.childNodes);
    const toolbar = document.querySelector('.topbar-content');
    const nextToolbar = next.querySelector('.topbar-content');
    if (toolbar && nextToolbar) toolbar.replaceChildren(...nextToolbar.childNodes);
    document.body.className = next.body.className;
    delete page.dataset.filterDirty;
    document.getElementById('chart-details')?.close();
    // Các link điều hướng tiếp tục giữ phân khúc vừa chọn.
    document.querySelectorAll('.sidebar [data-cohort-link]').forEach((link, index) => {
      const nextLink = next.querySelectorAll('.sidebar [data-cohort-link]')[index];
      if (nextLink) {
        link.href = nextLink.href;
        link.classList.toggle('active', nextLink.classList.contains('active'));
        if (nextLink.hasAttribute('aria-current')) link.setAttribute('aria-current', nextLink.getAttribute('aria-current'));
        else link.removeAttribute('aria-current');
      }
    });
    if (pushHistory) window.history.pushState({}, '', url);
    document.title = next.title;
    initializePage();
    await renderDashboardCharts();
    if (pageRequest === controller) showDashboardMessage('');
  } catch (error) {
    if (pageRequest === controller && error.name !== 'AbortError') showDashboardMessage(error.message);
  } finally {
    if (pageRequest === controller) setPageSkeleton(false);
  }
}

// Native page navigation and form posts also retain the shell while loading.
document.addEventListener('click', event => {
  if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
  const link = event.target.closest('a[href]');
  if (!link || link.hasAttribute('download') || (link.target && link.target !== '_self')) return;
  const url = new URL(link.href, window.location.href);
  if (url.origin !== window.location.origin || url.pathname.startsWith('/api/') || /export|download|template/.test(url.pathname)) return;
  if (url.pathname === window.location.pathname && url.search === window.location.search) return;
  queueMicrotask(() => { if (!event.defaultPrevented) setPageSkeleton(true); });
});
document.addEventListener('submit', event => {
  const form = event.target;
  if (form.target && form.target !== '_self') return;
  if (/export|download|template/.test(new URL(form.action, window.location.href).pathname)) return;
  queueMicrotask(() => { if (!event.defaultPrevented) setPageSkeleton(true); });
});
window.addEventListener('pageshow', () => setPageSkeleton(false));

