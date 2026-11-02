let pageRequest;
let detailRequest;
let detailUrl;
const loadingTimers = new WeakMap();

function setLoadingState(element, loading, message = 'Đang tải dữ liệu…',
    slowMessage = 'Đang tổng hợp số liệu theo bộ lọc…') {
  clearTimeout(loadingTimers.get(element));
  loadingTimers.delete(element);
  element.classList.toggle('is-loading', loading);
  if (loading) {
    element.setAttribute('aria-busy', 'true');
    element.textContent = message;
    loadingTimers.set(element, setTimeout(() => { element.textContent = slowMessage; }, 5000));
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
  setLoadingState(status, loading, message);
  status.textContent = message;
  status.hidden = !message;
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
    if (pageRequest === controller) page.removeAttribute('aria-busy');
  }
}

