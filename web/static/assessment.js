// Preserve the exact queue and scroll position while reviewing a profile.
(() => {
  const key = 'assessment-queue-return';
  function readState() {
    try { return JSON.parse(sessionStorage.getItem(key) || 'null'); } catch { return null; }
  }
  function saveState(state) {
    try { sessionStorage.setItem(key, JSON.stringify(state)); } catch { /* Storage may be disabled. */ }
  }
  function returnUrl(state) {
    if (!state) return null;
    try {
      const url = new URL(state.url, location.origin);
      return url.origin === location.origin && url.pathname === state.listPath ? url : null;
    } catch { return null; }
  }
  function setupSuggestions() {
    const form = document.querySelector('.assessment-search[data-suggestion-url]');
    const input = form?.querySelector('#application-search');
    const list = form?.querySelector('#application-search-suggestions');
    const popup = form?.querySelector('.assessment-suggestions');
    const status = form?.querySelector('.assessment-search-status');
    if (!form || !input || !list) return;
    let timer = 0;
    let controller = null;
    let active = -1;
    let renderedTerm = '';
    const hide = () => {
      popup.hidden = true;
      input.setAttribute('aria-expanded', 'false');
      input.removeAttribute('aria-activedescendant');
      active = -1;
    };
    const show = () => {
      if (!form.contains(document.activeElement)) return;
      popup.hidden = false;
      input.setAttribute('aria-expanded', 'true');
    };
    const showStatus = message => {
      list.replaceChildren();
      status.textContent = message;
      status.hidden = false;
      active = -1;
      input.removeAttribute('aria-activedescendant');
      show();
    };
    const highlight = (node, value) => {
      const term = input.value.trim();
      const position = value.toLocaleLowerCase('vi').indexOf(term.toLocaleLowerCase('vi'));
      if (position < 0) { node.textContent = value; return; }
      const match = document.createElement('mark');
      match.textContent = value.slice(position, position + term.length);
      node.append(document.createTextNode(value.slice(0, position)), match,
        document.createTextNode(value.slice(position + term.length)));
    };
    const render = results => {
      list.replaceChildren();
      active = -1;
      renderedTerm = input.value.trim();
      input.removeAttribute('aria-activedescendant');
      status.hidden = true;
      if (!results.length) {
        showStatus('Không tìm thấy hồ sơ phù hợp. Thử mã hoặc tên khác.');
        return;
      }
      results.forEach((row, index) => {
        const link = document.createElement('a');
        link.className = 'assessment-suggestion';
        link.id = `application-suggestion-${index}`;
        link.href = row.url;
        link.tabIndex = -1;
        link.dataset.assessmentDetail = '';
        link.setAttribute('role', 'option');
        link.setAttribute('aria-selected', 'false');
        const name = document.createElement('strong');
        highlight(name, row.case_label);
        const detail = document.createElement('span');
        highlight(detail, `#${row.source_application_id} · ${row.review_status}`);
        link.append(name, detail);
        list.append(link);
      });
      show();
    };
    const setActive = index => {
      const options = [...list.querySelectorAll('[role="option"]:not([aria-disabled="true"])')];
      options.forEach((option, position) => {
        const selected = position === index;
        option.setAttribute('aria-selected', String(selected));
        option.classList.toggle('is-active', selected);
      });
      active = index;
      if (options[index]) input.setAttribute('aria-activedescendant', options[index].id);
      else input.removeAttribute('aria-activedescendant');
      options[index]?.scrollIntoView({block: 'nearest'});
    };
    input.addEventListener('input', () => {
      clearTimeout(timer);
      controller?.abort();
      hide();
      const filterSearch = document.querySelector('#cohort-filter-form input[name="q"]');
      if (filterSearch) filterSearch.value = input.value;
      const term = input.value.trim();
      if (!term) { hide(); return; }
      timer = setTimeout(async () => {
        controller = new AbortController();
        const requestController = controller;
        showStatus('Đang tìm hồ sơ…');
        const url = new URL(form.dataset.suggestionUrl, location.origin);
        url.searchParams.set('q', term);
        const archived = new URLSearchParams(location.search).get('archived');
        if (archived) url.searchParams.set('archived', archived);
        try {
          const response = await fetch(url, {headers: {'Accept': 'application/json'}, signal: requestController.signal});
          if (!response.ok) throw new Error('Suggestion request failed');
          const payload = await response.json();
          if (!requestController.signal.aborted && input.value.trim() === term) render(payload.results || []);
        } catch (error) {
          if (error.name !== 'AbortError') showStatus('Chưa tải được gợi ý. Bạn vẫn có thể bấm Tìm kiếm.');
        }
      }, 180);
    });
    input.addEventListener('keydown', event => {
      const options = list.querySelectorAll('[role="option"]:not([aria-disabled="true"])');
      if (event.isComposing) return;
      if (event.key === 'ArrowDown' && !popup.hidden && options.length) {
        event.preventDefault(); setActive(Math.min(active + 1, options.length - 1));
      } else if (event.key === 'ArrowUp' && !popup.hidden && options.length) {
        event.preventDefault(); setActive(Math.max(active - 1, 0));
      } else if (event.key === 'Enter' && !popup.hidden && active >= 0 && options[active]) {
        event.preventDefault(); options[active].click();
      } else if (event.key === 'Escape') {
        clearTimeout(timer); controller?.abort(); hide();
      }
    });
    document.addEventListener('click', event => {
      if (!form.contains(event.target)) hide();
    });
    input.addEventListener('focus', () => {
      if (input.value.trim() === renderedTerm && list.childElementCount) show();
    });
    form.addEventListener('focusout', event => {
      if (!form.contains(event.relatedTarget)) { clearTimeout(timer); controller?.abort(); hide(); }
    });
    form.addEventListener('submit', hide);
  }
  function initialize() {
    const state = readState();
    const back = document.querySelector('[data-assessment-back]');
    const url = returnUrl(state);
    if (back && url && state.detailPath === location.pathname) back.href = url.href;
    const navigation = performance.getEntriesByType('navigation')[0];
    if (document.querySelector('.assessment-table-panel') && url &&
        url.href === location.href && (state.returning || navigation?.type === 'back_forward')) {
      requestAnimationFrame(() => {
        window.scrollTo(0, state.windowY || 0);
        const page = document.querySelector('.page');
        if (page) page.scrollTop = state.pageY || 0;
        const table = document.querySelector('.assessment-table-panel .table-scroll');
        if (table) { table.scrollLeft = state.tableX || 0; table.scrollTop = state.tableY || 0; }
      });
      state.returning = false;
      saveState(state);
    }
  }
  setupSuggestions();
  const filterForm = document.getElementById('cohort-filter-form');
  const scoreInputs = [...document.querySelectorAll('[data-score-percent]')];
  function syncScoreRange() {
    scoreInputs.forEach(field => {
      filterForm.elements[field.dataset.scorePercent].value = field.value === '' ? '' : String(Number((Number(field.value) / 100).toFixed(10)));
      field.setCustomValidity('');
    });
    const low = scoreInputs.find(field => field.dataset.scorePercent === 'score_min');
    const high = scoreInputs.find(field => field.dataset.scorePercent === 'score_max');
    if (low?.value && high?.value && Number(low.value) > Number(high.value)) {
      high.setCustomValidity('Điểm đến cần lớn hơn hoặc bằng điểm từ.');
    }
  }
  scoreInputs.forEach(field => field.addEventListener('input', syncScoreRange));
  filterForm?.addEventListener('submit', syncScoreRange);
  document.querySelectorAll('select[form="assessment-page-size"]').forEach(select => {
    select.addEventListener('change', () => select.form.requestSubmit());
  });
  document.addEventListener('click', event => {
    const detail = event.target.closest('[data-assessment-detail]');
    if (detail && !event.ctrlKey && !event.metaKey && !event.shiftKey) {
      const table = document.querySelector('.assessment-table-panel .table-scroll');
      saveState({url: location.href, listPath: location.pathname,
        detailPath: new URL(detail.href).pathname, windowY: window.scrollY,
        pageY: document.querySelector('.page')?.scrollTop || 0,
        tableX: table?.scrollLeft || 0, tableY: table?.scrollTop || 0});
    }
    if (event.target.closest('[data-assessment-back]')) {
      const state = readState();
      if (state && returnUrl(state) && state.detailPath === location.pathname) {
        state.returning = true;
        saveState(state);
      }
    }
    const action = event.target.closest('.assessment-actions [data-open]');
    if (action) action.closest('details.assessment-export')?.removeAttribute('open');
  });
  window.addEventListener('pageshow', initialize);
})();
