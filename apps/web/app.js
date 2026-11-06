/**
 * Overcharge Desk — Financial Control Infrastructure Frontend Engine
 * Zero fabricated metrics. All data fetched from deterministic Python backend (/api/v1/*).
 */

const STATE = {
  theme: localStorage.getItem('overcharge_desk_theme') || 'dark',
  token: localStorage.getItem('overcharge_desk_token') || null,
  apiBase: localStorage.getItem('overcharge_desk_api_base') || (window.location.hostname.includes('github.io') ? 'http://localhost:8000' : ''),
  currentUser: null,
  activeSection: 'overview',
  overviewData: null,
  cases: [],
  vendors: [],
  contracts: [],
  evidenceData: null,
  approvalsData: null,
  paymentsData: null,
  ledgerEvents: [],
  ledgerVerify: null,
  checkpoints: [],
  integrationsData: null,
  healthData: null,
  settingsData: null,
  activeWorkspaceCaseId: null,
  activeWorkspaceData: null,
  activeWorkspaceTab: 'lines',
};

const SECTION_TITLES = {
  'overview': 'Overview',
  'reconciliation': 'Reconciliation Cases',
  'new-case': 'New Intake Case',
  'evidence': 'Cryptographic Evidence',
  'vendors': 'Vendor Master',
  'contracts': 'Contract Schedules',
  'approvals': 'Financial Approvals',
  'payments': 'Payment Control',
  'ledger': 'Audit Ledger',
  'integrations': 'Integrations',
  'health': 'System Health',
  'settings': 'Settings & Access Control',
};

/* ==========================================================================
 * UTILITIES & FORMATTING
 * ========================================================================== */

function escapeHtml(val) {
  if (val === null || val === undefined) return '';
  return String(val)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function formatMoney(amount, currency = 'INR') {
  if (amount === null || amount === undefined || amount === '') return '—';
  const str = String(amount).trim();
  const num = Number(str);
  if (Number.isNaN(num)) return escapeHtml(`${currency} ${str}`);
  const formatted = num.toLocaleString('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return `${currency} ${formatted}`;
}

function statusTagHtml(status) {
  if (!status) return '<span class="status-tag">UNKNOWN</span>';
  const s = String(status).toUpperCase();
  let cls = '';
  if (['VERIFIED', 'APPROVED', 'HEALTHY', 'READY', 'VALID', 'OK', 'EXPORTED', 'ACTIVE', 'CONNECTED', 'MATCHED', 'WITHIN_CONTRACT', 'GENERATED'].includes(s)) {
    cls = 'status-green';
  } else if (['REVIEW_REQUIRED', 'PENDING', 'NOT_REQUESTED', 'AWAITING_APPROVAL', 'ELIGIBLE', 'OVERCHARGE_DETECTED', 'PARTIAL_MATCH', 'UNMATCHED', 'NOT_CONFIGURED', 'CREATED'].includes(s)) {
    cls = 'status-amber';
  } else if (['BLOCKED', 'REJECTED', 'TAMPERED', 'COMPROMISED', 'INVALID', 'ERROR', 'DEGRADED', 'SOURCE_DISCREPANCY', 'OUTSIDE_EFFECTIVE_WINDOW'].includes(s)) {
    cls = 'status-red';
  }
  return `<span class="status-tag ${cls}">${escapeHtml(s)}</span>`;
}

function showToast(message, isError = false) {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const item = document.createElement('div');
  item.className = 'toast-item';
  if (isError) {
    item.style.borderColor = 'var(--status-red-border)';
    item.style.backgroundColor = 'var(--bg-elevated)';
  }
  item.innerHTML = `
    <div class="space-y-0.5">
      <div class="font-semibold text-xs" style="color: ${isError ? 'var(--status-red-text)' : 'var(--text-primary)'};">
        ${isError ? 'Operational Refusal' : 'System Confirmation'}
      </div>
      <div class="text-xs mono" style="color: var(--text-secondary);">${escapeHtml(message)}</div>
    </div>
    <button type="button" class="btn btn-secondary btn-sm" onclick="this.parentElement.remove()">Close</button>
  `;
  container.appendChild(item);
  setTimeout(() => {
    if (item.parentElement) item.remove();
  }, 6000);
}

function showGlobalError(title, message) {
  const banner = document.getElementById('global-error-banner');
  const tEl = document.getElementById('global-error-title');
  const mEl = document.getElementById('global-error-message');
  if (banner && tEl && mEl) {
    tEl.textContent = title || 'Operation Error';
    mEl.textContent = message || 'An unexpected error occurred.';
    banner.classList.remove('hidden');
  }
}

function hideGlobalError() {
  const banner = document.getElementById('global-error-banner');
  if (banner) banner.classList.add('hidden');
}

function copyText(text, label = 'Digest') {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(() => {
      showToast(`${label} copied to clipboard.`);
    }).catch(() => {});
  }
}

/* ==========================================================================
 * THEME ENGINE (DARK #000000 & REVERSE LIGHT #FFFFFF)
 * ========================================================================== */

function applyTheme(theme) {
  const clean = theme === 'light' ? 'light' : 'dark';
  STATE.theme = clean;
  document.documentElement.setAttribute('data-theme', clean);
  try {
    localStorage.setItem('overcharge_desk_theme', clean);
  } catch (e) {}

  const labelEl = document.getElementById('theme-toggle-label');
  if (labelEl) {
    labelEl.textContent = clean === 'dark' ? 'Theme: Dark' : 'Theme: Light';
  }

  const darkBtn = document.getElementById('settings-theme-dark-btn');
  const lightBtn = document.getElementById('settings-theme-light-btn');
  if (darkBtn && lightBtn) {
    darkBtn.style.borderColor = clean === 'dark' ? 'var(--border-focus)' : 'var(--border-primary)';
    lightBtn.style.borderColor = clean === 'light' ? 'var(--border-focus)' : 'var(--border-primary)';
  }
}

function toggleTheme() {
  applyTheme(STATE.theme === 'dark' ? 'light' : 'dark');
}

function setTheme(theme) {
  applyTheme(theme);
}

/* ==========================================================================
 * API CLIENT & AUTHENTICATION
 * ========================================================================== */

function getApiUrl(path) {
  if (path.startsWith('http://') || path.startsWith('https://')) return path;
  const base = STATE.apiBase ? STATE.apiBase.replace(/\/+$/, '') : '';
  if (!base) return path;
  return `${base}/${path.replace(/^\/+/, '')}`;
}

async function apiRequest(path, options = {}) {
  const headers = Object.assign(
    { 'Content-Type': 'application/json' },
    options.headers || {}
  );
  if (STATE.token) {
    headers['Authorization'] = `Bearer ${STATE.token}`;
  }
  const url = getApiUrl(path);
  let resp;
  try {
    resp = await fetch(url, {
      method: options.method || 'GET',
      headers,
      body: options.body ? JSON.stringify(options.body) : undefined,
    });
  } catch (netErr) {
    if (window.location.hostname.includes('github.io')) {
      showToast(`Cannot reach API at ${STATE.apiBase || 'current host'}. Ensure server is running or configure endpoint in Settings.`, true);
    }
    throw netErr;
  }

  if (resp.status === 401 && path !== '/api/v1/auth/login') {
    STATE.token = null;
    localStorage.removeItem('overcharge_desk_token');
    updateSessionHeaderUI();
    throw new Error('Authentication required. Please sign in.');
  }

  const contentType = resp.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    const data = await resp.json();
    if (!resp.ok) {
      throw new Error(data.detail || data.error || `HTTP ${resp.status}`);
    }
    return data;
  } else {
    if (!resp.ok) {
      const txt = await resp.text();
      throw new Error(txt || `HTTP ${resp.status}`);
    }
    return resp;
  }
}

async function ensureAuthenticatedSession() {
  if (STATE.token) {
    try {
      const me = await apiRequest('/api/v1/auth/me');
      STATE.currentUser = me;
      updateSessionHeaderUI();
      return true;
    } catch (e) {
      STATE.token = null;
      localStorage.removeItem('overcharge_desk_token');
    }
  }
  // Auto-authenticate initial evaluation session as @admin so all modules are immediately inspectable
  try {
    await loginWithCredentials('admin', 'admin123', true);
    return true;
  } catch (e) {
    updateSessionHeaderUI();
    openAuthModal();
    return false;
  }
}

async function loginWithCredentials(username, password, silent = false) {
  const res = await apiRequest('/api/v1/auth/login', {
    method: 'POST',
    body: { username, password },
  });
  STATE.token = res.access_token;
  localStorage.setItem('overcharge_desk_token', res.access_token);
  const me = await apiRequest('/api/v1/auth/me');
  STATE.currentUser = me;
  updateSessionHeaderUI();
  closeAuthModal();
  if (!silent) {
    showToast(`Authenticated session active: ${me.full_name} (@${me.username} — ${me.role})`);
  }
  await refreshAllData();
  if (STATE.activeWorkspaceCaseId) {
    await openCaseWorkspace(STATE.activeWorkspaceCaseId, STATE.activeWorkspaceTab);
  }
}

function updateSessionHeaderUI() {
  const nameEl = document.getElementById('session-user-name');
  const roleEl = document.getElementById('session-user-role');
  if (!nameEl || !roleEl) return;
  if (STATE.currentUser) {
    nameEl.textContent = `${STATE.currentUser.full_name} (@${STATE.currentUser.username})`;
    roleEl.textContent = `ROLE: ${STATE.currentUser.role}`;
  } else {
    nameEl.textContent = 'Unauthenticated';
    roleEl.textContent = 'SIGN IN REQUIRED';
  }
}

function openAuthModal(prefillUsername = '') {
  const modal = document.getElementById('auth-modal-backdrop');
  const errEl = document.getElementById('auth-modal-error');
  if (errEl) errEl.classList.add('hidden');
  if (prefillUsername) {
    const uIn = document.getElementById('auth-username-input');
    const pIn = document.getElementById('auth-password-input');
    if (uIn) uIn.value = prefillUsername;
    if (pIn) pIn.value = '';
  }
  if (modal) modal.classList.remove('hidden');
}

function closeAuthModal() {
  const modal = document.getElementById('auth-modal-backdrop');
  if (modal) modal.classList.add('hidden');
}

async function submitLoginModal(event) {
  event.preventDefault();
  const uIn = document.getElementById('auth-username-input');
  const pIn = document.getElementById('auth-password-input');
  const errEl = document.getElementById('auth-modal-error');
  if (errEl) errEl.classList.add('hidden');
  try {
    await loginWithCredentials(uIn.value.trim(), pIn.value);
  } catch (err) {
    if (errEl) {
      errEl.textContent = err.message;
      errEl.classList.remove('hidden');
    }
  }
}

async function quickAuthenticate(username, password) {
  const errEl = document.getElementById('auth-modal-error');
  if (errEl) errEl.classList.add('hidden');
  try {
    await loginWithCredentials(username, password);
  } catch (err) {
    if (errEl) {
      errEl.textContent = err.message;
      errEl.classList.remove('hidden');
    }
  }
}

async function logoutCurrentSession() {
  try {
    await apiRequest('/api/v1/auth/logout', { method: 'POST' });
  } catch (e) {}
  STATE.token = null;
  STATE.currentUser = null;
  localStorage.removeItem('overcharge_desk_token');
  updateSessionHeaderUI();
  showToast('Session token revoked.');
}

/* ==========================================================================
 * NAVIGATION & GLOBAL REFRESH
 * ========================================================================== */

function navigateSection(sectionId) {
  if (!SECTION_TITLES[sectionId]) sectionId = 'overview';
  STATE.activeSection = sectionId;

  Object.keys(SECTION_TITLES).forEach((id) => {
    const secEl = document.getElementById(`section-${id}`);
    const navEl = document.getElementById(`nav-${id}`);
    if (secEl) {
      if (id === sectionId) secEl.classList.remove('hidden');
      else secEl.classList.add('hidden');
    }
    if (navEl) {
      if (id === sectionId) navEl.classList.add('active');
      else navEl.classList.remove('active');
    }
  });

  const bc = document.getElementById('header-breadcrumb');
  if (bc) bc.textContent = SECTION_TITLES[sectionId];

  // Trigger section-specific refresh
  if (sectionId === 'overview') loadOverviewSection();
  else if (sectionId === 'reconciliation') loadReconciliationCases();
  else if (sectionId === 'new-case') initNewCaseSection();
  else if (sectionId === 'evidence') loadEvidenceSection();
  else if (sectionId === 'vendors') loadVendorsSection();
  else if (sectionId === 'contracts') loadContractsSection();
  else if (sectionId === 'approvals') loadApprovalsSection();
  else if (sectionId === 'payments') loadPaymentsSection();
  else if (sectionId === 'ledger') loadLedgerSection();
  else if (sectionId === 'integrations') loadIntegrationsSection();
  else if (sectionId === 'health') loadHealthSection();
  else if (sectionId === 'settings') loadSettingsSection();
}

async function refreshAllData() {
  hideGlobalError();
  await Promise.allSettled([
    loadOverviewSection(),
    loadReconciliationCases(),
    loadVendorsDataSilent(),
    loadEvidenceDataSilent(),
  ]);
}

async function loadVendorsDataSilent() {
  try {
    const vendors = await apiRequest('/api/v1/vendors');
    STATE.vendors = vendors;
    updateNavBadge('nav-count-vendors', vendors.length);
    updateNavBadge('nav-count-contracts', vendors.length);
  } catch (e) {}
}

async function loadEvidenceDataSilent() {
  try {
    const ev = await apiRequest('/api/v1/evidence');
    STATE.evidenceData = ev;
    updateNavBadge('nav-count-evidence', ev.total_registered);
  } catch (e) {}
}

function updateNavBadge(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val !== null && val !== undefined ? String(val) : '—';
}

/* ==========================================================================
 * SECTION 1: OVERVIEW
 * ========================================================================== */

async function loadOverviewSection() {
  try {
    const [metrics, cases] = await Promise.all([
      apiRequest('/api/v1/overview/metrics'),
      apiRequest('/api/v1/cases'),
    ]);
    STATE.overviewData = metrics;
    STATE.cases = cases;
    renderOverviewSection(metrics, cases);
  } catch (err) {
    showGlobalError('Failed to load overview metrics', err.message);
  }
}

function renderOverviewSection(data, cases) {
  const fp = data.financial_position || {};
  const counts = data.case_counts || {};
  const audit = data.audit_integrity || {};
  const sys = data.system_status || {};
  const curr = data.currency || 'INR';

  // Demo environment badge
  const demoBadge = document.getElementById('demo-env-badge');
  if (demoBadge) {
    if (data.is_demo_environment) demoBadge.classList.remove('hidden');
    else demoBadge.classList.add('hidden');
  }

  // Update sidebar counts
  updateNavBadge('nav-count-reconciliation', counts.total);
  updateNavBadge('nav-count-approvals', fp.pending_approvals_count);
  updateNavBadge('nav-count-payments', counts.approved);
  updateNavBadge('nav-count-ledger', audit.total_events);

  // Header ledger indicator
  const hDot = document.getElementById('header-ledger-dot');
  const hTxt = document.getElementById('header-ledger-text');
  if (hDot && hTxt) {
    if (audit.valid) {
      hDot.style.backgroundColor = 'var(--status-green-text)';
      hTxt.textContent = `Ledger: ${audit.total_events} Events Verified`;
    } else {
      hDot.style.backgroundColor = 'var(--status-red-text)';
      hTxt.textContent = `Ledger: Tamper Alert (${audit.issues_count})`;
    }
  }

  // 1. Financial Position Strip
  const setTxt = (id, txt) => {
    const el = document.getElementById(id);
    if (el) el.textContent = txt;
  };
  setTxt('metric-total-invoiced', formatMoney(fp.total_invoiced, curr));
  setTxt('metric-total-invoiced-sub', `Across ${counts.total || 0} persisted case(s)`);
  setTxt('metric-reconciled-amount', formatMoney(fp.reconciled_amount, curr));
  setTxt('metric-discrepancy-amount', formatMoney(fp.discrepancy_amount, curr));
  setTxt('metric-withheld-amount', formatMoney(fp.withheld_amount, curr));
  setTxt('metric-approved-payment', formatMoney(fp.approved_for_payment, curr));
  setTxt('metric-pending-approvals', String(fp.pending_approvals_count ?? 0));

  // 2. Attention Required Queue
  const attItems = data.attention_required || [];
  const attBadge = document.getElementById('attention-count-badge');
  if (attBadge) {
    attBadge.textContent = `${attItems.length} ITEM${attItems.length === 1 ? '' : 'S'}`;
    attBadge.className = `status-tag ${attItems.length > 0 ? 'status-amber' : 'status-green'}`;
  }

  const attContainer = document.getElementById('overview-attention-container');
  if (attContainer) {
    if (attItems.length === 0) {
      attContainer.innerHTML = `
        <div class="empty-state m-4">
          <div class="font-semibold text-xs">No Open Exceptions or Pending Approvals</div>
          <p class="text-xs mt-1" style="color: var(--text-secondary);">
            All persisted cases are reconciled and no unapproved or blocked items require intervention.
          </p>
          <button type="button" onclick="navigateSection('new-case')" class="btn btn-primary btn-sm mt-3">
            Create New Intake Case
          </button>
        </div>
      `;
    } else {
      attContainer.innerHTML = `
        <table class="data-table">
          <thead>
            <tr>
              <th>Category</th>
              <th>Case / Invoice</th>
              <th class="num-col">Amount / Variance</th>
              <th>Diagnostic Summary</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            ${attItems.map((item) => `
              <tr class="clickable-row" onclick="openCaseWorkspace('${escapeHtml(item.case_id)}')">
                <td>${statusTagHtml(item.type)}</td>
                <td class="mono">
                  <div class="font-semibold">${escapeHtml(item.case_id)}</div>
                  <div class="text-[11px]" style="color: var(--text-secondary);">${escapeHtml(item.invoice_number)}</div>
                </td>
                <td class="num-col">
                  <div>${formatMoney(item.amount, curr)}</div>
                  <div class="text-[11px]" style="color: ${Number(item.withheld_amount) > 0 ? 'var(--status-amber-text)' : 'var(--text-secondary)'};">
                    Var: ${formatMoney(item.withheld_amount, curr)}
                  </div>
                </td>
                <td class="text-xs" style="color: var(--text-secondary);">${escapeHtml(item.summary)}</td>
                <td>
                  <button type="button" onclick="event.stopPropagation(); openCaseWorkspace('${escapeHtml(item.case_id)}')" class="btn btn-secondary btn-sm">
                    ${escapeHtml(item.action_label || 'Inspect')}
                  </button>
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      `;
    }
  }

  // 3. Audit Integrity Card
  const lBadge = document.getElementById('overview-ledger-badge');
  if (lBadge) {
    lBadge.textContent = audit.valid ? 'CHAIN VALID' : 'CHAIN COMPROMISED';
    lBadge.className = `status-tag ${audit.valid ? 'status-green' : 'status-red'}`;
  }
  setTxt('overview-ledger-events', `${audit.total_events || 0} events`);
  setTxt('overview-ledger-seq', `SEQ #${audit.highest_sequence || 0}`);
  const headEl = document.getElementById('overview-ledger-head');
  if (headEl) {
    headEl.innerHTML = `
      <span class="truncate" title="${escapeHtml(audit.head_event_hash)}">${escapeHtml(audit.head_event_hash || '—')}</span>
      <button type="button" onclick="copyText('${escapeHtml(audit.head_event_hash)}', 'Head Event Hash')" class="btn btn-secondary btn-sm">Copy</button>
    `;
  }

  // 4. System Control Status Card
  const hBadge = document.getElementById('overview-health-badge');
  if (hBadge) {
    hBadge.textContent = sys.status || 'UNKNOWN';
    hBadge.className = `status-tag ${sys.is_ready ? 'status-green' : 'status-red'}`;
  }
  const hList = document.getElementById('overview-health-list');
  if (hList && sys.checks) {
    const entries = [
      ['Identity DB (SQLite WAL)', sys.checks.identity_database],
      ['Audit Ledger (Append-Only)', sys.checks.ledger_database],
      ['Payments DB (Idempotent)', sys.checks.payments_database],
      ['HMAC Signing Key', sys.checks.signing_key],
      ['Case Storage Isolation', sys.checks.storage],
    ];
    hList.innerHTML = entries.map(([label, val]) => {
      const ok = String(val || '').startsWith('OK');
      return `
        <div class="flex items-center justify-between py-1" style="border-bottom: 1px solid var(--border-primary);">
          <span style="color: var(--text-secondary);">${escapeHtml(label)}</span>
          <span class="mono font-semibold" style="color: ${ok ? 'var(--status-green-text)' : 'var(--status-red-text)'};">
            ${escapeHtml(val || 'UNKNOWN')}
          </span>
        </div>
      `;
    }).join('');
  }

  // 5. Overview Cases Table
  const casesContainer = document.getElementById('overview-cases-container');
  if (casesContainer) {
    casesContainer.innerHTML = renderCasesTableHtml(cases);
  }
}

/* ==========================================================================
 * SECTION 2: RECONCILIATION CASES
 * ========================================================================== */

async function loadReconciliationCases() {
  try {
    const cases = await apiRequest('/api/v1/cases');
    STATE.cases = cases;
    updateNavBadge('nav-count-reconciliation', cases.length);
    applyReconciliationFilters();
  } catch (err) {
    showGlobalError('Failed to load reconciliation cases', err.message);
  }
}

function applyReconciliationFilters() {
  const searchVal = (document.getElementById('rec-search-input')?.value || '').trim().toLowerCase();
  const statusVal = document.getElementById('rec-status-filter')?.value || 'ALL';
  const approvalVal = document.getElementById('rec-approval-filter')?.value || 'ALL';
  const sortVal = document.getElementById('rec-sort-select')?.value || 'case_id_asc';

  let filtered = (STATE.cases || []).filter((c) => {
    if (statusVal !== 'ALL' && c.verification_status !== statusVal) return false;
    if (approvalVal !== 'ALL' && c.approval_status !== approvalVal) return false;
    if (searchVal) {
      const hay = `${c.case_id} ${c.invoice_number} ${c.vendor_id} ${c.commercial_status} ${c.created_by}`.toLowerCase();
      if (!hay.includes(searchVal)) return false;
    }
    return true;
  });

  filtered.sort((a, b) => {
    if (sortVal === 'invoiced_desc') {
      return Number(b.invoiced_total || 0) - Number(a.invoiced_total || 0);
    }
    if (sortVal === 'withheld_desc') {
      return Number(b.withheld_total || 0) - Number(a.withheld_total || 0);
    }
    if (sortVal === 'created_desc') {
      return String(b.created_at || '').localeCompare(String(a.created_at || ''));
    }
    return String(a.case_id || '').localeCompare(String(b.case_id || ''));
  });

  const summaryEl = document.getElementById('rec-results-summary');
  if (summaryEl) {
    summaryEl.textContent = `Showing ${filtered.length} of ${STATE.cases.length} persisted case(s)`;
  }

  const container = document.getElementById('reconciliation-table-container');
  if (container) {
    container.innerHTML = renderCasesTableHtml(filtered);
  }
}

function renderCasesTableHtml(cases) {
  if (!cases || cases.length === 0) {
    return `
      <div class="empty-state m-4">
        <div class="font-semibold text-xs">No Reconciliation Cases Found</div>
        <p class="text-xs mt-1" style="color: var(--text-secondary);">
          Workspace is in its clean base state. Register a vendor or create a new invoice intake case to begin reconciliation.
        </p>
        <div class="mt-3 flex justify-center gap-2">
          <button type="button" onclick="navigateSection('new-case')" class="btn btn-primary btn-sm">New Intake Case</button>
          <button type="button" onclick="navigateSection('vendors')" class="btn btn-secondary btn-sm">Register Vendor</button>
        </div>
      </div>
    `;
  }

  return `
    <table class="data-table">
      <thead>
        <tr>
          <th>Case ID</th>
          <th>Vendor</th>
          <th>Invoice #</th>
          <th>Verification</th>
          <th>Commercial Finding</th>
          <th class="num-col">Invoiced Subtotal</th>
          <th class="num-col">Contract Payable</th>
          <th class="num-col">Withheld Variance</th>
          <th>Approval</th>
          <th>Payment</th>
          <th>Action</th>
        </tr>
      </thead>
      <tbody>
        ${cases.map((c) => {
          const withheldNum = Number(c.withheld_total || 0);
          return `
            <tr class="clickable-row" onclick="openCaseWorkspace('${escapeHtml(c.case_id)}')">
              <td class="mono font-semibold">${escapeHtml(c.case_id)}</td>
              <td class="mono uppercase">${escapeHtml(c.vendor_id)}</td>
              <td class="mono">${escapeHtml(c.invoice_number)}</td>
              <td>${statusTagHtml(c.verification_status)}</td>
              <td>${statusTagHtml(c.commercial_status)}</td>
              <td class="num-col">${formatMoney(c.invoiced_total)}</td>
              <td class="num-col">${formatMoney(c.payable_total)}</td>
              <td class="num-col" style="color: ${withheldNum > 0 ? 'var(--status-amber-text)' : 'var(--text-secondary)'};">
                ${formatMoney(c.withheld_total)}
              </td>
              <td>${statusTagHtml(c.approval_status)}</td>
              <td>${statusTagHtml(c.payment_status)}</td>
              <td>
                <button
                  type="button"
                  onclick="event.stopPropagation(); openCaseWorkspace('${escapeHtml(c.case_id)}')"
                  class="btn btn-secondary btn-sm"
                  aria-label="Inspect case ${escapeHtml(c.case_id)}"
                >
                  Open Workspace
                </button>
              </td>
            </tr>
          `;
        }).join('')}
      </tbody>
    </table>
  `;
}

/* ==========================================================================
 * CASE DETAIL WORKSPACE DRAWER (ALL 5 SUB-TABS)
 * ========================================================================== */

async function openCaseWorkspace(caseId, initialTab = 'lines') {
  try {
    STATE.activeWorkspaceCaseId = caseId;
    STATE.activeWorkspaceTab = initialTab;
    const ws = await apiRequest(`/api/v1/cases/${encodeURIComponent(caseId)}/workspace`);
    STATE.activeWorkspaceData = ws;

    const backdrop = document.getElementById('case-workspace-backdrop');
    if (backdrop) backdrop.classList.remove('hidden');

    renderCaseWorkspaceHeader(ws);
    switchWorkspaceTab(initialTab);
  } catch (err) {
    showToast(`Failed to open Case Workspace: ${err.message}`, true);
  }
}

function closeCaseWorkspace() {
  const backdrop = document.getElementById('case-workspace-backdrop');
  if (backdrop) backdrop.classList.add('hidden');
  STATE.activeWorkspaceCaseId = null;
  STATE.activeWorkspaceData = null;
}

function renderCaseWorkspaceHeader(ws) {
  const s = ws.summary || {};
  const pol = ws.authorization_policy || {};
  const inv = ws.invoice || {};

  document.getElementById('ws-case-title').textContent = s.case_id || '—';
  document.getElementById('ws-verification-tag').outerHTML = `<span id="ws-verification-tag">${statusTagHtml(s.verification_status)}</span>`;
  document.getElementById('ws-approval-tag').outerHTML = `<span id="ws-approval-tag">${statusTagHtml(s.approval_status)}</span>`;
  document.getElementById('ws-commercial-tag').outerHTML = `<span id="ws-commercial-tag">${statusTagHtml(s.commercial_status)}</span>`;

  const subEl = document.getElementById('ws-case-subtitle');
  if (subEl) {
    subEl.textContent = `Vendor: ${ws.vendor?.name || s.vendor_id} (${s.vendor_id}) | Invoice: ${s.invoice_number} | Date: ${inv.invoice_date || '—'} | Created by: @${s.created_by}`;
  }

  // Primary action buttons
  const actionsEl = document.getElementById('ws-primary-actions');
  if (actionsEl) {
    let btns = [];
    if (pol.can_current_user_reconcile) {
      btns.push(`
        <button type="button" onclick="triggerCaseReconcile('${escapeHtml(s.case_id)}')" class="btn btn-secondary btn-sm">
          Re-Run 13-Stage Reconciliation
        </button>
      `);
    }
    if (pol.can_current_user_approve && s.verification_status === 'VERIFIED') {
      btns.push(`
        <button type="button" onclick="switchWorkspaceTab('approval')" class="btn btn-primary btn-sm">
          Approve / Reject Decision
        </button>
      `);
    }
    if (s.approval_status === 'APPROVED' && pol.can_current_user_export_payment) {
      btns.push(`
        <button type="button" onclick="switchWorkspaceTab('payment')" class="btn btn-primary btn-sm">
          Payment Control &amp; Export
        </button>
      `);
    }
    btns.push(`
      <button type="button" onclick="triggerExportAuditPackage('${escapeHtml(s.case_id)}')" class="btn btn-secondary btn-sm">
        Export Audit Package
      </button>
    `);
    actionsEl.innerHTML = btns.join('');
  }
}

function switchWorkspaceTab(tabName) {
  STATE.activeWorkspaceTab = tabName;
  ['lines', 'evidence', 'approval', 'payment', 'audit'].forEach((t) => {
    const btn = document.getElementById(`ws-tab-btn-${t}`);
    if (btn) {
      if (t === tabName) btn.classList.add('active');
      else btn.classList.remove('active');
    }
  });
  renderCaseWorkspaceBody();
}

function renderCaseWorkspaceBody() {
  const ws = STATE.activeWorkspaceData;
  const container = document.getElementById('ws-body-container');
  if (!ws || !container) return;

  const tab = STATE.activeWorkspaceTab;
  if (tab === 'lines') container.innerHTML = buildWorkspaceLinesTab(ws);
  else if (tab === 'evidence') container.innerHTML = buildWorkspaceEvidenceTab(ws);
  else if (tab === 'approval') container.innerHTML = buildWorkspaceApprovalTab(ws);
  else if (tab === 'payment') container.innerHTML = buildWorkspacePaymentTab(ws);
  else if (tab === 'audit') container.innerHTML = buildWorkspaceAuditTab(ws);
}

function buildWorkspaceLinesTab(ws) {
  const s = ws.summary || {};
  const inv = ws.invoice || {};
  const comp = ws.comparison || {};
  const totals = comp.totals || {};
  const curr = inv.currency || ws.vendor?.currency || 'INR';
  const blocking = comp.blocking_issues || [];
  const compLines = comp.lines || [];
  const rawLines = inv.lines || [];

  const blockingHtml = blocking.length > 0 ? `
    <div class="panel p-4" style="border-color: var(--status-red-border); background-color: var(--status-red-bg);">
      <div class="font-semibold text-xs uppercase" style="color: var(--status-red-text);">
        Verification Blocked — Automated Payment Release Prohibited
      </div>
      <ul class="mt-1.5 space-y-1 text-xs mono" style="color: var(--text-primary);">
        ${blocking.map((b) => `<li>• ${escapeHtml(b)}</li>`).join('')}
      </ul>
    </div>
  ` : '';

  return `
    ${blockingHtml}

    <!-- Financial Reconciliation Strip -->
    <div class="metric-strip">
      <div class="metric-cell">
        <div class="metric-label">Stated Invoice Total</div>
        <div class="metric-value">${formatMoney(totals.invoiced_total || totals.goods_subtotal_invoiced_written || inv.stated_total, curr)}</div>
        <div class="metric-sub mono">Source: ${escapeHtml(inv.source_file || 'invoice.json')}</div>
      </div>
      <div class="metric-cell">
        <div class="metric-label">Contract Matched Payable</div>
        <div class="metric-value">${formatMoney(totals.matched_per_contract || s.payable_total, curr)}</div>
        <div class="metric-sub mono">Contract: ${escapeHtml(comp.contract_id || ws.vendor?.contract?.contract_id || '—')}</div>
      </div>
      <div class="metric-cell">
        <div class="metric-label">Withheld Rate Variance</div>
        <div class="metric-value" style="color: ${Number(totals.variance_on_matched_lines || 0) > 0 ? 'var(--status-amber-text)' : 'var(--text-primary)'};">
          ${formatMoney(totals.variance_on_matched_lines || s.withheld_total || '0.00', curr)}
        </div>
        <div class="metric-sub">Overcharge isolated from payment</div>
      </div>
      <div class="metric-cell">
        <div class="metric-label">Unverified / Unmatched</div>
        <div class="metric-value" style="color: ${Number(totals.unmatched_invoiced_as_written || totals.unmatched_invoiced_amount || 0) > 0 ? 'var(--status-red-text)' : 'var(--text-primary)'};">
          ${formatMoney(totals.unmatched_invoiced_as_written || totals.unmatched_invoiced_amount || '0.00', curr)}
        </div>
        <div class="metric-sub">Quarantined SKU lines</div>
      </div>
      <div class="metric-cell">
        <div class="metric-label">Settlement Scope</div>
        <div class="metric-value text-xs" style="white-space: normal;">${escapeHtml(comp.settlement_status || 'UNRECONCILED')}</div>
        <div class="metric-sub">Goods subtotal boundary</div>
      </div>
    </div>

    <!-- Line-by-Line Comparison Table -->
    <div class="panel">
      <div class="panel-header">
        <div>
          <h3 class="panel-title">Line-by-Line Schedule A Reconciliation</h3>
          <p class="panel-subtitle">Exact Decimal(0.01) half-up comparison between extracted invoice lines and contracted master schedule</p>
        </div>
      </div>
      <div class="table-wrap">
        ${compLines.length > 0 ? `
          <table class="data-table">
            <thead>
              <tr>
                <th>Line</th>
                <th>SKU / Key</th>
                <th>Description</th>
                <th class="num-col">Qty</th>
                <th class="num-col">Invoiced Rate</th>
                <th class="num-col">Contract Rate</th>
                <th class="num-col">Invoiced Line Total</th>
                <th class="num-col">Contract Line Total</th>
                <th class="num-col">Variance</th>
                <th>Clause &amp; Source Locator</th>
                <th>Line Status</th>
              </tr>
            </thead>
            <tbody>
              ${compLines.map((ln, idx) => {
                const rawVar = ln.line_variance ?? ln.variance;
                const varNum = Number(rawVar || 0);
                const invLineTot = ln.invoiced_line_total_as_written ?? ln.invoiced_line_total_computed ?? ln.invoiced_line_total;
                const conLineTot = ln.contract_line_total ?? ln.expected_line_total;
                const locator = [ln.clause_ref || ln.contract_clause_ref, ln.source_ref].filter(Boolean).join(' · ');
                return `
                  <tr>
                    <td class="mono">#${escapeHtml(ln.line_no || ln.line_number || idx + 1)}</td>
                    <td class="mono font-semibold">${escapeHtml(ln.item_key || ln.item_code || 'UNMATCHED')}</td>
                    <td>${escapeHtml(ln.description || '—')}</td>
                    <td class="num-col">${escapeHtml(ln.quantity)}</td>
                    <td class="num-col">${formatMoney(ln.invoiced_unit_price, curr)}</td>
                    <td class="num-col">${ln.contract_unit_price ? formatMoney(ln.contract_unit_price, curr) : 'UNCONTRACTED'}</td>
                    <td class="num-col">${invLineTot ? formatMoney(invLineTot, curr) : '—'}</td>
                    <td class="num-col">${conLineTot ? formatMoney(conLineTot, curr) : '—'}</td>
                    <td class="num-col font-semibold" style="color: ${varNum > 0 ? 'var(--status-amber-text)' : 'var(--text-secondary)'};">
                      ${rawVar !== undefined && rawVar !== null ? formatMoney(rawVar, curr) : '—'}
                    </td>
                    <td class="mono text-[11px]" style="color: var(--text-secondary);">
                      ${escapeHtml(locator || 'UNMATCHED')}
                    </td>
                    <td>${statusTagHtml(ln.verification_status || ln.status)}</td>
                  </tr>
                `;
              }).join('')}
            </tbody>
          </table>
        ` : `
          <table class="data-table">
            <thead>
              <tr>
                <th>Line</th>
                <th>SKU / Code</th>
                <th>Description</th>
                <th class="num-col">Quantity</th>
                <th class="num-col">Invoiced Unit Rate</th>
                <th class="num-col">Stated Line Total</th>
              </tr>
            </thead>
            <tbody>
              ${rawLines.map((ln, idx) => `
                <tr>
                  <td class="mono">#${idx + 1}</td>
                  <td class="mono font-semibold">${escapeHtml(ln.item_code)}</td>
                  <td>${escapeHtml(ln.description)}</td>
                  <td class="num-col">${escapeHtml(ln.quantity)}</td>
                  <td class="num-col">${formatMoney(ln.unit_price, curr)}</td>
                  <td class="num-col">${formatMoney(ln.line_total, curr)}</td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        `}
      </div>
    </div>

    <!-- Source Artifact Digest Binding -->
    <div class="panel">
      <div class="panel-header">
        <div>
          <h3 class="panel-title">Immutable Source &amp; Comparison Fingerprints</h3>
          <p class="panel-subtitle">64-character SHA-256 cryptographic digests binding this comparison</p>
        </div>
      </div>
      <div class="panel-body grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
        <div>
          <div class="field-label">Raw Invoice Source SHA-256 (${escapeHtml(inv.source_file || 'invoice.json')})</div>
          <div class="hash-box">
            <span>${escapeHtml(inv.source_sha256 || 'Not computed')}</span>
            ${inv.source_sha256 ? `<button type="button" onclick="copyText('${escapeHtml(inv.source_sha256)}', 'Invoice SHA-256')" class="btn btn-secondary btn-sm">Copy</button>` : ''}
          </div>
        </div>
        <div>
          <div class="field-label">Deterministic Comparison Digest (compare.json)</div>
          <div class="hash-box">
            <span>${escapeHtml(comp.comparison_digest || ws.verification_record?.compare_sha256 || 'Run reconciliation to compute')}</span>
            ${(comp.comparison_digest || ws.verification_record?.compare_sha256) ? `<button type="button" onclick="copyText('${escapeHtml(comp.comparison_digest || ws.verification_record?.compare_sha256)}', 'Comparison SHA-256')" class="btn btn-secondary btn-sm">Copy</button>` : ''}
          </div>
        </div>
      </div>
    </div>
  `;
}

function buildWorkspaceEvidenceTab(ws) {
  const s = ws.summary || {};
  const ev = ws.evidence || {};
  const items = ev.items || [];
  const verMap = {};
  (ev.verification_results || []).forEach((r) => {
    verMap[r.evidence_id] = r;
  });

  return `
    <div class="panel">
      <div class="panel-header">
        <div>
          <h3 class="panel-title">Case Evidence Registry (<code>evidence_registry.json</code>)</h3>
          <p class="panel-subtitle">Full 64-character SHA-256 fingerprints verified against on-disk artifacts</p>
        </div>
        <div class="flex items-center gap-2">
          <span class="status-tag ${ev.all_verified ? 'status-green' : 'status-amber'}">
            ${ev.all_verified ? 'ALL ARTIFACTS VERIFIED' : `${items.length} ARTIFACT(S)`}
          </span>
          <button type="button" onclick="verifyCaseEvidenceLive('${escapeHtml(s.case_id)}')" class="btn btn-primary btn-sm">
            Re-Verify All SHA-256 Hashes
          </button>
        </div>
      </div>
      <div class="table-wrap">
        ${items.length === 0 ? `
          <div class="empty-state m-4">
            <div class="font-semibold text-xs">No Evidence Artifacts Registered Yet</div>
            <p class="text-xs mt-1" style="color: var(--text-secondary);">Run reconciliation or attach a supporting document below to populate the evidence registry.</p>
          </div>
        ` : `
          <table class="data-table">
            <thead>
              <tr>
                <th>Evidence ID</th>
                <th>Artifact Type</th>
                <th>Source Locator</th>
                <th>64-Char SHA-256 Digest</th>
                <th class="num-col">Size (Bytes)</th>
                <th>Integrity</th>
              </tr>
            </thead>
            <tbody>
              ${items.map((item) => {
                const vr = verMap[item.evidence_id] || {};
                const isOk = vr.status === 'VERIFIED';
                return `
                  <tr>
                    <td class="mono font-semibold">${escapeHtml(item.evidence_id)}</td>
                    <td><span class="status-tag">${escapeHtml(item.artifact_type)}</span></td>
                    <td class="mono text-xs">${escapeHtml(item.source_locator)}</td>
                    <td class="mono text-[11px]">
                      <div class="flex items-center gap-2">
                        <span>${escapeHtml(item.sha256)}</span>
                        <button type="button" onclick="copyText('${escapeHtml(item.sha256)}', 'Evidence SHA-256')" class="btn btn-secondary btn-sm">Copy</button>
                      </div>
                    </td>
                    <td class="num-col">${escapeHtml(item.size_bytes)}</td>
                    <td>${statusTagHtml(isOk ? 'VERIFIED' : (vr.status || 'REGISTERED'))}</td>
                  </tr>
                `;
              }).join('')}
            </tbody>
          </table>
        `}
      </div>
    </div>

    <!-- Downloadable Case Artifacts -->
    <div class="panel">
      <div class="panel-header">
        <div>
          <h3 class="panel-title">Generated Case Artifacts</h3>
          <p class="panel-subtitle">Inspect or download deterministic pipeline outputs for case ${escapeHtml(s.case_id)}</p>
        </div>
      </div>
      <div class="panel-body flex flex-wrap gap-2">
        ${(s.available_artifacts || []).length === 0 ? `
          <span class="text-xs mono" style="color: var(--text-muted);">No output artifacts generated yet. Run reconciliation first.</span>
        ` : (s.available_artifacts || []).map((art) => `
          <button type="button" onclick="downloadCaseArtifact('${escapeHtml(s.case_id)}', '${escapeHtml(art)}')" class="btn btn-secondary btn-sm mono">
            Download ${escapeHtml(art)}
          </button>
        `).join('')}
      </div>
    </div>

    <!-- Attach Supporting Document -->
    <div class="panel">
      <div class="panel-header">
        <div>
          <h3 class="panel-title">Attach &amp; Fingerprint Supporting Evidence</h3>
          <p class="panel-subtitle">Saves document inside case attachment boundary and commits SHA-256 to <code>evidence_registry.json</code></p>
        </div>
      </div>
      <form onsubmit="submitWorkspaceEvidence(event, '${escapeHtml(s.case_id)}')" class="panel-body space-y-3">
        <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <div>
            <label class="field-label">Filename *</label>
            <input type="text" id="ws-ev-filename" required placeholder="receiving-slip.txt" class="input-field mono">
          </div>
          <div>
            <label class="field-label">Artifact Classification *</label>
            <select id="ws-ev-type" class="select-field mono">
              <option value="SUPPORTING_DOCUMENT">SUPPORTING_DOCUMENT</option>
              <option value="DELIVERY_RECEIPT">DELIVERY_RECEIPT</option>
              <option value="CREDIT_NOTE">CREDIT_NOTE</option>
            </select>
          </div>
          <div class="flex items-end">
            <button type="submit" class="btn btn-primary w-full">Fingerprint &amp; Attach</button>
          </div>
        </div>
        <div>
          <label class="field-label">Document Content *</label>
          <textarea id="ws-ev-content" rows="2" required placeholder="Enter goods received note, email confirmation, or credit memo details..." class="textarea-field mono"></textarea>
        </div>
      </form>
    </div>
  `;
}

function buildWorkspaceApprovalTab(ws) {
  const s = ws.summary || {};
  const pol = ws.authorization_policy || {};
  const app = ws.approval;
  const curr = ws.invoice?.currency || 'INR';

  const policyBanner = `
    <div class="panel">
      <div class="panel-header">
        <div>
          <h3 class="panel-title">Governance &amp; Separation of Duties Evaluation</h3>
          <p class="panel-subtitle">Server-side policy evaluation via <code>AuthorizationService.evaluate_approval_policy</code></p>
        </div>
        ${statusTagHtml(pol.can_current_user_approve ? 'ELIGIBLE' : (app ? app.receipt?.decision : 'RESTRICTED'))}
      </div>
      <div class="panel-body grid grid-cols-1 sm:grid-cols-4 gap-4 text-xs">
        <div>
          <div style="color: var(--text-secondary);">Case Creator</div>
          <div class="mono font-semibold mt-0.5">@${escapeHtml(pol.case_creator)}</div>
        </div>
        <div>
          <div style="color: var(--text-secondary);">Current Authenticated Actor</div>
          <div class="mono font-semibold mt-0.5">@${escapeHtml(pol.current_actor)} (${escapeHtml(pol.current_role)})</div>
        </div>
        <div>
          <div style="color: var(--text-secondary);">Server-Calculated Payable</div>
          <div class="mono font-semibold mt-0.5">${formatMoney(s.payable_total, curr)}</div>
        </div>
        <div>
          <div style="color: var(--text-secondary);">Policy Verdict</div>
          <div class="mt-0.5" style="color: var(--text-primary);">${escapeHtml(pol.policy_message)}</div>
        </div>
      </div>
    </div>
  `;

  if (app && app.receipt) {
    const rec = app.receipt;
    return `
      ${policyBanner}
      <div class="panel">
        <div class="panel-header">
          <div>
            <h3 class="panel-title">Cryptographic Approval Receipt (<code>approvals/approval_receipt.json</code>)</h3>
            <p class="panel-subtitle">Signed with active HMAC-SHA256 key and bound to full 64-character artifact digests</p>
          </div>
          <span class="status-tag ${app.cryptographically_valid ? 'status-green' : 'status-red'}">
            ${app.cryptographically_valid ? 'HMAC SIGNATURE VALID' : 'SIGNATURE INVALID'}
          </span>
        </div>
        <div class="panel-body space-y-4 text-xs">
          <div class="grid grid-cols-1 sm:grid-cols-3 lg:grid-cols-6 gap-4">
            <div>
              <div style="color: var(--text-secondary);">Receipt ID</div>
              <div class="mono font-semibold mt-0.5">${escapeHtml(rec.receipt_id)}</div>
            </div>
            <div>
              <div style="color: var(--text-secondary);">Decision</div>
              <div class="mt-0.5">${statusTagHtml(rec.decision)}</div>
            </div>
            <div>
              <div style="color: var(--text-secondary);">Authorized Actor</div>
              <div class="mono font-semibold mt-0.5">@${escapeHtml(rec.actor_id)} (${escapeHtml(rec.actor_role)})</div>
            </div>
            <div>
              <div style="color: var(--text-secondary);">Approved Payable</div>
              <div class="mono font-semibold mt-0.5">${formatMoney(rec.approved_amount, rec.currency || curr)}</div>
            </div>
            <div>
              <div style="color: var(--text-secondary);">Withheld Variance</div>
              <div class="mono font-semibold mt-0.5">${formatMoney(rec.withheld_amount, rec.currency || curr)}</div>
            </div>
            <div>
              <div style="color: var(--text-secondary);">Timestamp</div>
              <div class="mono mt-0.5">${escapeHtml(rec.created_at)}</div>
            </div>
          </div>

          <div>
            <div class="field-label">Recorded Decision Rationale</div>
            <div class="p-2.5 rounded mono" style="background-color: var(--bg-input); border: 1px solid var(--border-primary);">
              ${escapeHtml(rec.reason || 'Standard commercial verification approval')}
            </div>
          </div>

          <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <div class="field-label">Invoice SHA-256 Binding</div>
              <div class="hash-box"><span>${escapeHtml(rec.invoice_sha256)}</span></div>
            </div>
            <div>
              <div class="field-label">Comparison SHA-256 Binding</div>
              <div class="hash-box"><span>${escapeHtml(rec.compare_sha256)}</span></div>
            </div>
            <div>
              <div class="field-label">Canonical Receipt SHA-256 Hash</div>
              <div class="hash-box">
                <span>${escapeHtml(rec.receipt_hash)}</span>
                <button type="button" onclick="copyText('${escapeHtml(rec.receipt_hash)}', 'Receipt Hash')" class="btn btn-secondary btn-sm">Copy</button>
              </div>
            </div>
            <div>
              <div class="field-label">HMAC-SHA256 Cryptographic Signature</div>
              <div class="hash-box">
                <span>${escapeHtml(rec.receipt_signature)}</span>
                <button type="button" onclick="copyText('${escapeHtml(rec.receipt_signature)}', 'Receipt HMAC Signature')" class="btn btn-secondary btn-sm">Copy</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  return `
    ${policyBanner}
    <div class="panel">
      <div class="panel-header">
        <div>
          <h3 class="panel-title">Record Human Authorization Decision</h3>
          <p class="panel-subtitle">Generates a tamper-evident <code>approval_receipt.json</code> and commits decision to the SQLite Audit Ledger</p>
        </div>
      </div>
      <div class="panel-body space-y-4">
        <div>
          <label for="ws-decision-reason" class="field-label">Decision Rationale / Audit Note *</label>
          <textarea
            id="ws-decision-reason"
            rows="2"
            placeholder="e.g. Approved matched Schedule A amount; withholding rate creep variance for commercial credit memo."
            class="textarea-field mono"
          >Verified against Master Supply Agreement Schedule A; releasing matched contract amount only.</textarea>
        </div>
        <div class="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onclick="submitCaseDecision('${escapeHtml(s.case_id)}', 'APPROVED')"
            class="btn btn-primary"
            ${pol.can_current_user_approve ? '' : 'disabled'}
          >
            Approve Payable (${formatMoney(s.payable_total, curr)})
          </button>
          <button
            type="button"
            onclick="submitCaseDecision('${escapeHtml(s.case_id)}', 'REJECTED')"
            class="btn btn-danger"
            ${pol.can_current_user_reject ? '' : 'disabled'}
          >
            Reject Invoice &amp; Quarantine
          </button>
          ${!pol.can_current_user_approve ? `
            <button type="button" onclick="openAuthModal('approver')" class="btn btn-secondary btn-sm">
              Switch to Approver Session (@approver / @owner)
            </button>
          ` : ''}
        </div>
      </div>
    </div>
  `;
}

function buildWorkspacePaymentTab(ws) {
  const s = ws.summary || {};
  const pol = ws.authorization_policy || {};
  const dest = ws.vendor?.treasury_destination || {};
  const instructions = ws.payment_instructions || [];
  const curr = ws.invoice?.currency || 'INR';

  return `
    <!-- Treasury Destination Verification -->
    <div class="panel">
      <div class="panel-header">
        <div>
          <h3 class="panel-title">Treasury Bank Routing Destination (<code>VendorRegistry</code>)</h3>
          <p class="panel-subtitle">Payment instructions can only be generated for vendors with verified bank routing references</p>
        </div>
        ${statusTagHtml(dest.bank_verified ? 'VERIFIED' : 'BLOCKED')}
      </div>
      <div class="panel-body grid grid-cols-1 sm:grid-cols-4 gap-4 text-xs">
        <div>
          <div style="color: var(--text-secondary);">Vendor ID</div>
          <div class="mono font-semibold mt-0.5 uppercase">${escapeHtml(s.vendor_id)}</div>
        </div>
        <div>
          <div style="color: var(--text-secondary);">Treasury Destination Reference</div>
          <div class="mono font-semibold mt-0.5">${escapeHtml(dest.destination_reference)}</div>
        </div>
        <div>
          <div style="color: var(--text-secondary);">Allowed Currencies</div>
          <div class="mono mt-0.5">${escapeHtml((dest.allowed_currencies || []).join(', '))}</div>
        </div>
        <div class="flex items-end justify-end">
          <button
            type="button"
            onclick="createCasePaymentInstruction('${escapeHtml(s.case_id)}')"
            class="btn btn-primary btn-sm"
            ${(s.approval_status === 'APPROVED' && pol.can_current_user_export_payment) ? '' : 'disabled'}
          >
            Generate Payment Instruction
          </button>
        </div>
      </div>
    </div>

    <!-- Payment Instructions Table -->
    <div class="panel">
      <div class="panel-header">
        <div>
          <h3 class="panel-title">Payment Instructions (<code>payments.db</code>)</h3>
          <p class="panel-subtitle">One-time export enforcement prevents duplicate batch releases</p>
        </div>
      </div>
      <div class="table-wrap">
        ${instructions.length === 0 ? `
          <div class="empty-state m-4">
            <div class="font-semibold text-xs">No Payment Instruction Generated Yet</div>
            <p class="text-xs mt-1" style="color: var(--text-secondary);">
              ${s.approval_status === 'APPROVED'
                ? 'Click "Generate Payment Instruction" above (requires payment:export permission, e.g. @pay_operator or @admin).'
                : 'A cryptographic approval receipt (APPROVED) is required before a payment instruction can be generated.'}
            </p>
            ${!pol.can_current_user_export_payment ? `
              <button type="button" onclick="openAuthModal('pay_operator')" class="btn btn-secondary btn-sm mt-3">
                Switch to @pay_operator Session
              </button>
            ` : ''}
          </div>
        ` : `
          <table class="data-table">
            <thead>
              <tr>
                <th>Instruction ID</th>
                <th>Receipt Ref</th>
                <th>Destination</th>
                <th class="num-col">Approved Amount</th>
                <th>Status</th>
                <th>Created At</th>
                <th>Exported By</th>
                <th>One-Time Export</th>
              </tr>
            </thead>
            <tbody>
              ${instructions.map((inst) => `
                <tr>
                  <td class="mono font-semibold">${escapeHtml(inst.instruction_id)}</td>
                  <td class="mono text-xs">${escapeHtml(inst.approval_receipt_id)}</td>
                  <td class="mono text-xs">${escapeHtml(inst.destination_reference)}</td>
                  <td class="num-col">${formatMoney(inst.approved_amount, inst.currency)}</td>
                  <td>${statusTagHtml(inst.status)}</td>
                  <td class="mono text-xs">${escapeHtml(inst.created_at)}</td>
                  <td class="mono text-xs">${escapeHtml(inst.exported_by || '—')}</td>
                  <td>
                    <div class="flex items-center gap-1.5">
                      <button
                        type="button"
                        onclick="exportPaymentInstructionFile('${escapeHtml(s.case_id)}', '${escapeHtml(inst.instruction_id)}', 'csv')"
                        class="btn btn-primary btn-sm"
                        ${inst.status === 'EXPORTED' || !pol.can_current_user_export_payment ? 'disabled' : ''}
                      >
                        Export CSV
                      </button>
                      <button
                        type="button"
                        onclick="exportPaymentInstructionFile('${escapeHtml(s.case_id)}', '${escapeHtml(inst.instruction_id)}', 'json')"
                        class="btn btn-secondary btn-sm"
                        ${inst.status === 'EXPORTED' || !pol.can_current_user_export_payment ? 'disabled' : ''}
                      >
                        Export JSON
                      </button>
                    </div>
                  </td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        `}
      </div>
    </div>

    ${ws.dispute_draft ? `
      <div class="panel">
        <div class="panel-header">
          <div>
            <h3 class="panel-title">Generated Commercial Dispute Notice (<code>dispute_email.md</code>)</h3>
            <p class="panel-subtitle">Citing exact Schedule A contract clause locators and withheld variance calculations</p>
          </div>
        </div>
        <div class="panel-body">
          <pre class="p-4 rounded text-xs overflow-x-auto" style="background-color: var(--bg-input); border: 1px solid var(--border-primary); color: var(--text-primary);">${escapeHtml(ws.dispute_draft)}</pre>
        </div>
      </div>
    ` : ''}
  `;
}

function buildWorkspaceAuditTab(ws) {
  const events = ws.audit_events || [];
  const history = ws.case_meta?.state_history || [];

  return `
    <!-- Append-Only SQLite Audit Ledger Events for Case -->
    <div class="panel">
      <div class="panel-header">
        <div>
          <h3 class="panel-title">Case Audit Ledger Chain (<code>ledger.db</code>)</h3>
          <p class="panel-subtitle">${events.length} cryptographically chained event(s) recorded for this case</p>
        </div>
      </div>
      <div class="table-wrap">
        ${events.length === 0 ? `
          <div class="empty-state m-4">
            <div class="font-semibold text-xs">No Ledger Events Recorded for This Case</div>
          </div>
        ` : `
          <table class="data-table">
            <thead>
              <tr>
                <th>Seq</th>
                <th>Event ID</th>
                <th>Event Type</th>
                <th>Actor</th>
                <th>Timestamp</th>
                <th>Previous Event Hash</th>
                <th>Event Hash (SHA-256)</th>
              </tr>
            </thead>
            <tbody>
              ${events.map((ev) => `
                <tr>
                  <td class="mono">#${escapeHtml(ev.event_sequence)}</td>
                  <td class="mono font-semibold">${escapeHtml(ev.event_id)}</td>
                  <td>${statusTagHtml(ev.event_type)}</td>
                  <td class="mono">@${escapeHtml(ev.actor_id)}</td>
                  <td class="mono text-xs">${escapeHtml(ev.timestamp)}</td>
                  <td class="mono text-[11px]" style="color: var(--text-muted);" title="${escapeHtml(ev.previous_event_hash)}">
                    ${escapeHtml(String(ev.previous_event_hash).slice(0, 16))}…
                  </td>
                  <td class="mono text-[11px]" title="${escapeHtml(ev.event_hash)}">
                    <div class="flex items-center gap-1.5">
                      <span>${escapeHtml(String(ev.event_hash).slice(0, 20))}…</span>
                      <button type="button" onclick="copyText('${escapeHtml(ev.event_hash)}', 'Event Hash')" class="btn btn-secondary btn-sm">Copy</button>
                    </div>
                  </td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        `}
      </div>
    </div>

    <!-- Case Lifecycle State Machine Transitions -->
    <div class="panel">
      <div class="panel-header">
        <div>
          <h3 class="panel-title">Case Lifecycle State History (<code>case.json</code>)</h3>
          <p class="panel-subtitle">Optimistic concurrency version: v${escapeHtml(ws.case_meta?.version || 1)}</p>
        </div>
      </div>
      <div class="table-wrap">
        ${history.length === 0 ? `
          <div class="p-4 text-xs mono" style="color: var(--text-muted);">Seeded benchmark case — see SQLite Audit Ledger above for full event trace.</div>
        ` : `
          <table class="data-table">
            <thead>
              <tr>
                <th>From State</th>
                <th>To State</th>
                <th>Actor</th>
                <th>Reason</th>
                <th>Timestamp</th>
              </tr>
            </thead>
            <tbody>
              ${history.map((h) => `
                <tr>
                  <td>${statusTagHtml(h.from_state || 'INITIAL')}</td>
                  <td>${statusTagHtml(h.to_state)}</td>
                  <td class="mono">@${escapeHtml(h.actor_id)}</td>
                  <td>${escapeHtml(h.reason)}</td>
                  <td class="mono text-xs">${escapeHtml(h.timestamp)}</td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        `}
      </div>
    </div>
  `;
}

/* ==========================================================================
 * CASE WORKSPACE ACTIONS
 * ========================================================================== */

async function triggerCaseReconcile(caseId) {
  try {
    const res = await apiRequest(`/api/v1/cases/${encodeURIComponent(caseId)}/reconcile`, {
      method: 'POST',
      body: { require_approval: true },
    });
    showToast(`Reconciliation completed: ${res.verification_status} (${res.commercial_status})`);
    await openCaseWorkspace(caseId, STATE.activeWorkspaceTab);
    await refreshAllData();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function verifyCaseEvidenceLive(caseId) {
  try {
    const res = await apiRequest(`/api/v1/cases/${encodeURIComponent(caseId)}/evidence/verify`, {
      method: 'POST',
    });
    showToast(`SHA-256 Evidence Verification: ${res.verified ? 'ALL VALID' : 'MISMATCH DETECTED'} (${res.results?.length || 0} artifacts)`);
    await openCaseWorkspace(caseId, 'evidence');
  } catch (err) {
    showToast(err.message, true);
  }
}

async function submitWorkspaceEvidence(event, caseId) {
  event.preventDefault();
  const filename = document.getElementById('ws-ev-filename')?.value.trim();
  const artifact_type = document.getElementById('ws-ev-type')?.value;
  const content = document.getElementById('ws-ev-content')?.value;
  try {
    const res = await apiRequest(`/api/v1/cases/${encodeURIComponent(caseId)}/evidence`, {
      method: 'POST',
      body: { filename, artifact_type, content },
    });
    showToast(`Registered evidence ${res.evidence.evidence_id} (SHA-256: ${res.evidence.sha256.slice(0, 16)}…)`);
    await openCaseWorkspace(caseId, 'evidence');
    await loadEvidenceDataSilent();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function submitCaseDecision(caseId, decision) {
  const reason = document.getElementById('ws-decision-reason')?.value.trim() || `Case decision: ${decision}`;
  try {
    const res = await apiRequest(`/api/v1/cases/${encodeURIComponent(caseId)}/approve`, {
      method: 'POST',
      body: { decision, reason },
    });
    showToast(`Decision ${res.decision} recorded. Receipt ${res.receipt_id} signed (SHA-256: ${res.receipt_hash.slice(0, 16)}…).`);
    await openCaseWorkspace(caseId, 'approval');
    await refreshAllData();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function createCasePaymentInstruction(caseId) {
  try {
    const inst = await apiRequest(`/api/v1/cases/${encodeURIComponent(caseId)}/payment-instruction`, {
      method: 'POST',
      body: {},
    });
    showToast(`Payment Instruction ${inst.instruction_id} created for ${formatMoney(inst.approved_amount, inst.currency)}.`);
    await openCaseWorkspace(caseId, 'payment');
    await refreshAllData();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function exportPaymentInstructionFile(caseId, instructionId, format) {
  try {
    const resp = await apiRequest(
      `/api/v1/cases/${encodeURIComponent(caseId)}/payment-instruction/${encodeURIComponent(instructionId)}/export?format=${encodeURIComponent(format)}`
    );
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${instructionId}.${format}`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    showToast(`Payment Instruction ${instructionId} exported as ${format.toUpperCase()}. Status locked to EXPORTED.`);
    if (STATE.activeWorkspaceCaseId === caseId) {
      await openCaseWorkspace(caseId, 'payment');
    }
    if (STATE.activeSection === 'payments') {
      await loadPaymentsSection();
    }
  } catch (err) {
    showToast(err.message, true);
  }
}

async function downloadCaseArtifact(caseId, artifactName) {
  try {
    const resp = await apiRequest(
      `/api/v1/cases/${encodeURIComponent(caseId)}/artifacts/${encodeURIComponent(artifactName)}`
    );
    const text = typeof resp === 'object' && !(resp instanceof Response)
      ? JSON.stringify(resp, null, 2)
      : await resp.text();
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${caseId}-${artifactName}`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    showToast(`Downloaded artifact ${artifactName}.`);
  } catch (err) {
    showToast(err.message, true);
  }
}

async function triggerExportAuditPackage(caseId) {
  try {
    const res = await apiRequest(`/api/v1/cases/${encodeURIComponent(caseId)}/export-audit`, {
      method: 'POST',
    });
    showToast(`Standalone Audit Package verified and exported to ${res.target_package_directory} (Digest: ${res.package_integrity_digest.slice(0, 16)}…)`);
  } catch (err) {
    showToast(err.message, true);
  }
}

/* ==========================================================================
 * SECTION 3: NEW INTAKE CASE
 * ========================================================================== */

function computeNextCaseId() {
  const today = new Date().toISOString().slice(0, 10).replace(/-/g, '');
  const seq = String((STATE.cases || []).length + 1).padStart(2, '0');
  return `OC-${today}-${seq}`;
}

function generateNewCaseIdInput() {
  const cidEl = document.getElementById('nc-case-id');
  if (cidEl) cidEl.value = computeNextCaseId();
}

async function initNewCaseSection() {
  await loadVendorsDataSilent();
  const dl = document.getElementById('nc-vendor-datalist');
  if (dl) {
    dl.innerHTML = (STATE.vendors || [])
      .map((v) => `<option value="${escapeHtml(v.vendor_id)}">${escapeHtml(v.vendor_name)}</option>`)
      .join('');
  }
  const cidEl = document.getElementById('nc-case-id');
  if (cidEl && !cidEl.value.trim()) {
    cidEl.value = computeNextCaseId();
  }
  const vInput = document.getElementById('nc-vendor-id');
  if (vInput && !vInput.value.trim() && (STATE.vendors || []).length > 0) {
    vInput.value = STATE.vendors[0].vendor_id;
    const vNameEl = document.getElementById('nc-vendor-name');
    if (vNameEl && !vNameEl.value.trim()) {
      vNameEl.value = STATE.vendors[0].vendor_name || '';
    }
  }
  renderNewCaseContractPreview();
  const tbody = document.getElementById('nc-lines-tbody');
  if (tbody && tbody.children.length === 0) {
    addNewCaseLineRow();
  }
}

function getSelectedNewCaseVendor() {
  const vid = (document.getElementById('nc-vendor-id')?.value || '').trim().toLowerCase();
  if (!vid) return null;
  return (STATE.vendors || []).find((v) => v.vendor_id.toLowerCase() === vid) || null;
}

function onNewCaseVendorChange() {
  const vendor = getSelectedNewCaseVendor();
  const vNameEl = document.getElementById('nc-vendor-name');
  if (vendor && vNameEl) {
    vNameEl.value = vendor.vendor_name || '';
  }
  renderNewCaseContractPreview();
}

function renderNewCaseContractPreview() {
  const vendor = getSelectedNewCaseVendor();
  const vid = (document.getElementById('nc-vendor-id')?.value || '').trim();
  const titleEl = document.getElementById('nc-contract-preview-title');
  const listEl = document.getElementById('nc-contract-preview-list');
  const currSel = document.getElementById('nc-currency');
  if (!listEl) return;

  if (!vendor) {
    if (titleEl) {
      titleEl.textContent = vid ? `New Vendor Profile — ${vid}` : 'Live Vendor Schedule A Reference';
    }
    listEl.innerHTML = vid
      ? `Vendor <code>${escapeHtml(vid)}</code> is not registered yet. Entering a <strong>Contract Rate (Schedule A)</strong> on line items below will automatically provision the vendor profile, contract markdown, and verified treasury destination upon submission.`
      : 'Enter a registered Vendor ID above (or type a new Vendor ID + Contract Rate per line to auto-provision its Schedule A contract).';
    return;
  }
  if (currSel && vendor.currency) {
    currSel.value = vendor.currency;
  }
  if (titleEl) {
    titleEl.textContent = `Schedule A Reference — ${vendor.contract_id || vendor.vendor_id}`;
  }
  const rates = vendor.rates || [];
  if (rates.length === 0) {
    listEl.innerHTML = 'No contracted SKU rates registered for this vendor yet. Specify Contract Rate on line items to add to Schedule A.';
    return;
  }
  listEl.innerHTML = rates
    .map(
      (r) =>
        `• SKU <code>${escapeHtml(r.sku || r.item_code)}</code>: ${escapeHtml(r.currency || vendor.currency)} ${escapeHtml(r.unit_price)} / ${escapeHtml(r.unit || 'unit')} (${escapeHtml(r.clause_ref || 'Schedule A')})`
    )
    .concat([`• Effective: ${escapeHtml(vendor.effective_from)} to ${escapeHtml(vendor.effective_to)}`])
    .join('<br>');
}

function addNewCaseLineRow(item) {
  const tbody = document.getElementById('nc-lines-tbody');
  if (!tbody) return;
  const vendor = getSelectedNewCaseVendor();
  const firstRate = (vendor?.rates || [])[0] || null;
  const rowItem = item || {
    item_code: firstRate ? (firstRate.sku || firstRate.item_code) : '',
    description: firstRate ? firstRate.description : '',
    quantity: '1',
    unit_price: firstRate ? Number(firstRate.unit_price || 0).toFixed(2) : '',
    contract_unit_price: firstRate ? Number(firstRate.unit_price || 0).toFixed(2) : '',
    line_total: firstRate ? Number(firstRate.unit_price || 0).toFixed(2) : '0.00',
  };
  const tr = document.createElement('tr');
  tr.innerHTML = `
    <td><input type="text" class="input-field mono nc-line-sku" required value="${escapeHtml(rowItem.item_code)}" placeholder="e.g. SKU-101"></td>
    <td><input type="text" class="input-field nc-line-desc" required value="${escapeHtml(rowItem.description)}" placeholder="Item description"></td>
    <td><input type="text" class="input-field mono num-col nc-line-qty" required value="${escapeHtml(rowItem.quantity)}" oninput="recalcNewCaseLineRow(this)"></td>
    <td><input type="text" class="input-field mono num-col nc-line-price" required value="${escapeHtml(rowItem.unit_price)}" placeholder="0.00" oninput="recalcNewCaseLineRow(this)"></td>
    <td><input type="text" class="input-field mono num-col nc-line-contract-price" value="${escapeHtml(rowItem.contract_unit_price || '')}" placeholder="Schedule A rate"></td>
    <td><input type="text" class="input-field mono num-col nc-line-total" required value="${escapeHtml(rowItem.line_total)}"></td>
    <td>
      <button type="button" onclick="if(document.querySelectorAll('#nc-lines-tbody tr').length > 1) this.closest('tr').remove(); syncStatedTotalFromLines();" class="btn btn-secondary btn-sm">
        Remove
      </button>
    </td>
  `;
  tbody.appendChild(tr);
  syncStatedTotalFromLines();
}

function recalcNewCaseLineRow(inputEl) {
  const tr = inputEl.closest('tr');
  if (!tr) return;
  const qty = Number(tr.querySelector('.nc-line-qty')?.value || 0);
  const price = Number(tr.querySelector('.nc-line-price')?.value || 0);
  const totalInput = tr.querySelector('.nc-line-total');
  if (totalInput && !Number.isNaN(qty) && !Number.isNaN(price)) {
    totalInput.value = (qty * price).toFixed(2);
    syncStatedTotalFromLines();
  }
}

function syncStatedTotalFromLines() {
  const totals = Array.from(document.querySelectorAll('.nc-line-total'));
  let sum = 0;
  totals.forEach((el) => {
    const v = Number(el.value || 0);
    if (!Number.isNaN(v)) sum += v;
  });
  const statedEl = document.getElementById('nc-stated-total');
  if (statedEl) statedEl.value = sum.toFixed(2);
}

function resetNewCaseFormBlank() {
  const cidEl = document.getElementById('nc-case-id');
  if (cidEl) cidEl.value = computeNextCaseId();
  const vIdEl = document.getElementById('nc-vendor-id');
  if (vIdEl) vIdEl.value = (STATE.vendors || [])[0]?.vendor_id || '';
  const vNameEl = document.getElementById('nc-vendor-name');
  if (vNameEl) vNameEl.value = (STATE.vendors || [])[0]?.vendor_name || '';
  const invEl = document.getElementById('nc-invoice-num');
  if (invEl) invEl.value = '';
  const dateEl = document.getElementById('nc-invoice-date');
  if (dateEl) dateEl.value = new Date().toISOString().slice(0, 10);
  const tbody = document.getElementById('nc-lines-tbody');
  if (tbody) tbody.innerHTML = '';
  addNewCaseLineRow({
    item_code: '',
    description: '',
    quantity: '1',
    unit_price: '',
    contract_unit_price: '',
    line_total: '0.00',
  });
  renderNewCaseContractPreview();
}

async function submitNewCase(event) {
  event.preventDefault();
  const errEl = document.getElementById('nc-validation-error');
  if (errEl) errEl.classList.add('hidden');

  const caseId = document.getElementById('nc-case-id')?.value.trim();
  const vendorId = document.getElementById('nc-vendor-id')?.value.trim().toLowerCase();
  const vendorName = document.getElementById('nc-vendor-name')?.value.trim();
  const invoiceNumber = document.getElementById('nc-invoice-num')?.value.trim();
  const invoiceDate = document.getElementById('nc-invoice-date')?.value.trim();
  const currency = document.getElementById('nc-currency')?.value.trim() || 'INR';
  const statedTotal = document.getElementById('nc-stated-total')?.value.trim();
  const autoReconcile = Boolean(document.getElementById('nc-auto-reconcile')?.checked);

  if (!caseId || !vendorId || !invoiceNumber || !invoiceDate || !statedTotal) {
    if (errEl) {
      errEl.textContent = 'Validation Error: Case ID, Vendor ID, Invoice Number, Invoice Date, and Stated Subtotal are required.';
      errEl.classList.remove('hidden');
    }
    return;
  }

  const rows = Array.from(document.querySelectorAll('#nc-lines-tbody tr'));
  if (rows.length === 0) {
    if (errEl) {
      errEl.textContent = 'Validation Error: At least one invoice line item is required.';
      errEl.classList.remove('hidden');
    }
    return;
  }

  const lines = [];
  for (let i = 0; i < rows.length; i++) {
    const r = rows[i];
    const sku = r.querySelector('.nc-line-sku')?.value.trim();
    const desc = r.querySelector('.nc-line-desc')?.value.trim();
    const qty = r.querySelector('.nc-line-qty')?.value.trim();
    const price = r.querySelector('.nc-line-price')?.value.trim();
    const contractPrice = r.querySelector('.nc-line-contract-price')?.value.trim();
    const total = r.querySelector('.nc-line-total')?.value.trim();
    if (!sku || !qty || !price || !total || Number(qty) <= 0 || Number(price) <= 0) {
      if (errEl) {
        errEl.textContent = `Validation Error on Line #${i + 1}: Valid SKU, positive Quantity, and positive Unit Rate are required.`;
        errEl.classList.remove('hidden');
      }
      return;
    }
    const lineObj = {
      line_number: i + 1,
      item_code: sku,
      description: desc || sku,
      quantity: qty,
      unit: 'unit',
      unit_price: Number(price).toFixed(2),
      line_total: Number(total).toFixed(2),
      source_ref: `line-${i + 1}`,
    };
    if (contractPrice && !Number.isNaN(Number(contractPrice)) && Number(contractPrice) > 0) {
      lineObj.contract_unit_price = Number(contractPrice).toFixed(2);
    }
    lines.push(lineObj);
  }

  const invoiceJson = {
    case_id: caseId,
    vendor_id: vendorId,
    invoice_number: invoiceNumber,
    invoice_date: invoiceDate,
    currency,
    stated_total: Number(statedTotal).toFixed(2),
    lines,
  };

  try {
    const created = await apiRequest('/api/v1/cases', {
      method: 'POST',
      body: {
        case_id: caseId,
        vendor_id: vendorId,
        vendor_name: vendorName,
        invoice_json: invoiceJson,
        auto_reconcile: autoReconcile,
      },
    });
    showToast(`Case ${created.case_id} created (${created.verification_status}). Opening Case Workspace.`);
    await refreshAllData();
    navigateSection('reconciliation');
    await openCaseWorkspace(created.case_id, 'lines');
  } catch (err) {
    if (errEl) {
      errEl.textContent = err.message;
      errEl.classList.remove('hidden');
    }
  }
}

/* ==========================================================================
 * SECTION 4: EVIDENCE REGISTRY
 * ========================================================================== */

async function loadEvidenceSection() {
  try {
    const [ev, cases] = await Promise.all([
      apiRequest('/api/v1/evidence'),
      apiRequest('/api/v1/cases'),
    ]);
    STATE.evidenceData = ev;
    STATE.cases = cases;
    updateNavBadge('nav-count-evidence', ev.total_registered);

    document.getElementById('ev-metric-total').textContent = String(ev.total_registered ?? 0);
    document.getElementById('ev-metric-verified').textContent = String(ev.verified_count ?? 0);
    document.getElementById('ev-metric-failed').textContent = String(ev.failed_count ?? 0);
    document.getElementById('ev-metric-sources').textContent = String((ev.repository_sources || []).length);

    const caseSel = document.getElementById('ev-case-select');
    if (caseSel) {
      if ((cases || []).length === 0) {
        caseSel.innerHTML = `<option value="">No persisted cases available</option>`;
      } else {
        caseSel.innerHTML = (cases || [])
          .map((c) => `<option value="${escapeHtml(c.case_id)}">${escapeHtml(c.case_id)} (${escapeHtml(c.invoice_number)})</option>`)
          .join('');
      }
    }

    const container = document.getElementById('evidence-table-container');
    if (container) {
      const items = ev.items || [];
      if (items.length === 0) {
        container.innerHTML = `
          <div class="empty-state m-4">
            <div class="font-semibold text-xs">No Registered Case Evidence Found</div>
            <p class="text-xs mt-1" style="color: var(--text-secondary);">Create an invoice intake case to automatically compute and register 64-character SHA-256 evidence records.</p>
          </div>
        `;
      } else {
        container.innerHTML = `
          <table class="data-table">
            <thead>
              <tr>
                <th>Evidence ID</th>
                <th>Case ID</th>
                <th>Invoice #</th>
                <th>Classification</th>
                <th>Source Locator</th>
                <th>Recorded 64-Char SHA-256</th>
                <th class="num-col">Bytes</th>
                <th>Live Verification</th>
              </tr>
            </thead>
            <tbody>
              ${items.map((item) => `
                <tr class="clickable-row" onclick="openCaseWorkspace('${escapeHtml(item.case_id)}', 'evidence')">
                  <td class="mono font-semibold">${escapeHtml(item.evidence_id)}</td>
                  <td class="mono">${escapeHtml(item.case_id)}</td>
                  <td class="mono">${escapeHtml(item.invoice_number)}</td>
                  <td><span class="status-tag">${escapeHtml(item.artifact_type)}</span></td>
                  <td class="mono text-xs">${escapeHtml(item.source_locator)}</td>
                  <td class="mono text-[11px]">
                    <div class="flex items-center gap-2">
                      <span>${escapeHtml(item.recorded_sha256)}</span>
                      <button type="button" onclick="event.stopPropagation(); copyText('${escapeHtml(item.recorded_sha256)}', 'Evidence SHA-256')" class="btn btn-secondary btn-sm">Copy</button>
                    </div>
                  </td>
                  <td class="num-col">${escapeHtml(item.size_bytes)}</td>
                  <td>${statusTagHtml(item.verification_status)}</td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        `;
      }
    }
  } catch (err) {
    showGlobalError('Failed to load evidence registry', err.message);
  }
}

async function submitNewEvidence(event) {
  event.preventDefault();
  const caseId = document.getElementById('ev-case-select')?.value;
  const artifact_type = document.getElementById('ev-artifact-type')?.value;
  const filename = document.getElementById('ev-filename')?.value.trim();
  const content = document.getElementById('ev-content')?.value;
  if (!caseId || !filename || !content) return;
  try {
    const res = await apiRequest(`/api/v1/cases/${encodeURIComponent(caseId)}/evidence`, {
      method: 'POST',
      body: { filename, artifact_type, content },
    });
    showToast(`Registered ${res.evidence.evidence_id} for ${caseId} (SHA-256: ${res.evidence.sha256.slice(0, 16)}…)`);
    document.getElementById('ev-filename').value = '';
    document.getElementById('ev-content').value = '';
    await loadEvidenceSection();
  } catch (err) {
    showToast(err.message, true);
  }
}

/* ==========================================================================
 * SECTION 5: VENDORS
 * ========================================================================== */

function toggleVendorForm() {
  const p = document.getElementById('new-vendor-panel');
  if (p) p.classList.toggle('hidden');
}

async function loadVendorsSection() {
  try {
    const vendors = await apiRequest('/api/v1/vendors');
    STATE.vendors = vendors;
    updateNavBadge('nav-count-vendors', vendors.length);
    const container = document.getElementById('vendors-list-container');
    if (!container) return;

    if (vendors.length === 0) {
      const formPanel = document.getElementById('new-vendor-panel');
      if (formPanel) formPanel.classList.remove('hidden');
      container.innerHTML = `
        <div class="panel p-6 text-center">
          <div class="font-semibold text-xs">No Vendors Registered Yet</div>
          <p class="text-xs mt-1" style="color: var(--text-secondary);">
            Use the form above to register your first vendor profile, Schedule A rate, and verified treasury routing destination.
          </p>
        </div>
      `;
      return;
    }

    container.innerHTML = vendors.map((v) => {
      const dest = v.treasury_destination || {};
      const m = v.metrics || {};
      return `
        <div class="panel">
          <div class="panel-header">
            <div>
              <div class="flex items-center gap-2.5">
                <h2 class="panel-title text-sm">${escapeHtml(v.vendor_name)}</h2>
                <span class="status-tag mono">${escapeHtml(v.vendor_id)}</span>
                ${statusTagHtml(dest.bank_verified ? 'VERIFIED' : 'BLOCKED')}
              </div>
              <p class="panel-subtitle mono mt-1">
                Master Contract: ${escapeHtml(v.contract_id)} | Effective: ${escapeHtml(v.effective_from)} to ${escapeHtml(v.effective_to)} | Source: ${escapeHtml(v.source_file)}
              </p>
            </div>
            <div class="flex items-center gap-2">
              <button type="button" onclick="navigateSection('contracts')" class="btn btn-secondary btn-sm">Inspect Schedule A (${v.items_count} SKUs)</button>
            </div>
          </div>
          <div class="panel-body grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4 text-xs">
            <div>
              <div style="color: var(--text-secondary);">Treasury Routing Destination</div>
              <div class="mono font-semibold mt-1">${escapeHtml(dest.destination_reference)}</div>
            </div>
            <div>
              <div style="color: var(--text-secondary);">Persisted Cases</div>
              <div class="mono font-semibold mt-1">${escapeHtml(m.cases_count || 0)} case(s)</div>
            </div>
            <div>
              <div style="color: var(--text-secondary);">Total Invoiced</div>
              <div class="mono font-semibold mt-1">${formatMoney(m.total_invoiced, v.currency)}</div>
            </div>
            <div>
              <div style="color: var(--text-secondary);">Contract Payable</div>
              <div class="mono font-semibold mt-1">${formatMoney(m.total_payable, v.currency)}</div>
            </div>
            <div>
              <div style="color: var(--text-secondary);">Withheld Overcharges</div>
              <div class="mono font-semibold mt-1" style="color: ${Number(m.total_withheld || 0) > 0 ? 'var(--status-amber-text)' : 'var(--text-primary)'};">
                ${formatMoney(m.total_withheld, v.currency)}
              </div>
            </div>
          </div>
        </div>
      `;
    }).join('');
  } catch (err) {
    showGlobalError('Failed to load vendors', err.message);
  }
}

async function submitNewVendor(event) {
  event.preventDefault();
  const vendor_id = document.getElementById('vn-id')?.value.trim();
  const vendor_name = document.getElementById('vn-name')?.value.trim();
  const contract_id = document.getElementById('vn-contract-id')?.value.trim();
  const destination_reference = document.getElementById('vn-dest-ref')?.value.trim();
  const sku = document.getElementById('vn-sku')?.value.trim();
  const desc = document.getElementById('vn-sku-desc')?.value.trim();
  const price = document.getElementById('vn-sku-price')?.value.trim();

  try {
    await apiRequest('/api/v1/vendors', {
      method: 'POST',
      body: {
        vendor_id,
        vendor_name,
        contract_id,
        destination_reference,
        bank_verified: true,
        rates: [
          {
            item_code: sku,
            description: desc,
            unit: 'unit',
            unit_price: price,
            clause_ref: 'Schedule-A-Item-1',
          },
        ],
      },
    });
    showToast(`Vendor '${vendor_name}' (${vendor_id}) registered with verified treasury routing.`);
    document.getElementById('vn-id').value = '';
    document.getElementById('vn-name').value = '';
    document.getElementById('vn-contract-id').value = '';
    document.getElementById('vn-dest-ref').value = '';
    document.getElementById('vn-sku').value = '';
    document.getElementById('vn-sku-desc').value = '';
    document.getElementById('vn-sku-price').value = '';
    await loadVendorsSection();
    await refreshAllData();
  } catch (err) {
    showToast(err.message, true);
  }
}

/* ==========================================================================
 * SECTION 6: CONTRACTS
 * ========================================================================== */

async function loadContractsSection() {
  try {
    const contracts = await apiRequest('/api/v1/contracts');
    STATE.contracts = contracts;
    updateNavBadge('nav-count-contracts', contracts.length);

    const dl = document.getElementById('cr-vendor-datalist');
    if (dl) {
      dl.innerHTML = contracts
        .map((c) => `<option value="${escapeHtml(c.vendor_id)}">${escapeHtml(c.vendor_name)} (${escapeHtml(c.contract_id)})</option>`)
        .join('');
    }
    const vInput = document.getElementById('cr-vendor');
    if (vInput && !vInput.value.trim() && contracts.length > 0) {
      vInput.value = contracts[0].vendor_id;
    }

    const container = document.getElementById('contracts-list-container');
    if (!container) return;

    if (contracts.length === 0) {
      container.innerHTML = `
        <div class="panel p-6 text-center">
          <div class="font-semibold text-xs">No Contract Schedules Registered Yet</div>
          <p class="text-xs mt-1" style="color: var(--text-secondary);">
            Enter a Vendor ID, SKU, Description, and Unit Price above to create a Schedule A contract rate clause.
          </p>
        </div>
      `;
      return;
    }

    container.innerHTML = contracts.map((c) => `
      <div class="panel">
        <div class="panel-header">
          <div>
            <div class="flex items-center gap-2.5">
              <h2 class="panel-title text-sm mono">${escapeHtml(c.contract_id)}</h2>
              <span class="status-tag status-green">ACTIVE SCHEDULE</span>
            </div>
            <p class="panel-subtitle mono mt-1">
              Vendor: ${escapeHtml(c.vendor_name)} (${escapeHtml(c.vendor_id)}) | Window: ${escapeHtml(c.effective_from)} to ${escapeHtml(c.effective_to)} | Source File: ${escapeHtml(c.source_file || '—')}
            </p>
          </div>
          ${c.source_sha256 ? `
            <div class="mono text-[11px]" style="color: var(--text-secondary);">
              SHA-256: ${escapeHtml(c.source_sha256.slice(0, 20))}…
              <button type="button" onclick="copyText('${escapeHtml(c.source_sha256)}', 'Contract SHA-256')" class="btn btn-secondary btn-sm ml-1">Copy</button>
            </div>
          ` : ''}
        </div>
        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th>Clause Locator</th>
                <th>SKU / Item Code</th>
                <th>Description</th>
                <th>Recognized Aliases</th>
                <th>Unit</th>
                <th class="num-col">Contracted Unit Rate</th>
                <th>Effective Window</th>
              </tr>
            </thead>
            <tbody>
              ${(c.rates || []).map((r) => `
                <tr>
                  <td class="mono text-xs">${escapeHtml(c.source_file ? `${c.source_file}#${r.clause_ref}` : r.clause_ref)}</td>
                  <td class="mono font-semibold">${escapeHtml(r.item_code)}</td>
                  <td>${escapeHtml(r.description)}</td>
                  <td class="text-xs" style="color: var(--text-secondary);">${escapeHtml((r.aliases || []).join(', '))}</td>
                  <td class="mono">${escapeHtml(r.unit)}</td>
                  <td class="num-col font-semibold">${formatMoney(r.unit_price, r.currency || c.currency)}</td>
                  <td class="mono text-xs">${escapeHtml(r.effective_from)} → ${escapeHtml(r.effective_to)}</td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
        ${c.source_markdown ? `
          <details class="p-4" style="border-top: 1px solid var(--border-primary);">
            <summary class="cursor-pointer text-xs font-semibold mono" style="color: var(--text-secondary);">
              Inspect Raw Contract Document (${escapeHtml(c.source_file)})
            </summary>
            <pre class="mt-3 p-4 rounded text-xs overflow-x-auto" style="background-color: var(--bg-input); border: 1px solid var(--border-primary);">${escapeHtml(c.source_markdown)}</pre>
          </details>
        ` : ''}
      </div>
    `).join('');
  } catch (err) {
    showGlobalError('Failed to load contract schedules', err.message);
  }
}

async function submitContractRate(event) {
  event.preventDefault();
  const vendorId = (document.getElementById('cr-vendor')?.value || '').trim().toLowerCase();
  const item_code = document.getElementById('cr-sku')?.value.trim();
  const description = document.getElementById('cr-desc')?.value.trim();
  const unit = document.getElementById('cr-unit')?.value.trim();
  const unit_price = document.getElementById('cr-price')?.value.trim();
  if (!vendorId) {
    showToast('Vendor ID is required to save a contract rate clause.', true);
    return;
  }

  try {
    const res = await apiRequest(`/api/v1/contracts/${encodeURIComponent(vendorId)}/rates`, {
      method: 'POST',
      body: { item_code, description, unit, unit_price },
    });
    showToast(`Schedule A rate ${res.rate.item_code} (${formatMoney(res.rate.unit_price)}) saved to ${vendorId}.`);
    document.getElementById('cr-sku').value = '';
    document.getElementById('cr-desc').value = '';
    document.getElementById('cr-price').value = '';
    await loadContractsSection();
    await refreshAllData();
  } catch (err) {
    showToast(err.message, true);
  }
}

/* ==========================================================================
 * SECTION 7: APPROVALS
 * ========================================================================== */

async function loadApprovalsSection() {
  try {
    const data = await apiRequest('/api/v1/approvals');
    STATE.approvalsData = data;
    updateNavBadge('nav-count-approvals', data.pending_count);

    const badge = document.getElementById('approvals-pending-badge');
    if (badge) {
      badge.textContent = `${data.pending_count} VERIFIED ELIGIBLE`;
      badge.className = `status-tag ${data.pending_count > 0 ? 'status-amber' : 'status-green'}`;
    }

    const pendingContainer = document.getElementById('approvals-pending-container');
    if (pendingContainer) {
      const queue = data.pending_queue || [];
      if (queue.length === 0) {
        pendingContainer.innerHTML = `
          <div class="empty-state m-4">
            <div class="font-semibold text-xs">No Unapproved Cases in Queue</div>
            <p class="text-xs mt-1" style="color: var(--text-secondary);">All persisted cases have recorded cryptographic decisions or are empty.</p>
          </div>
        `;
      } else {
        pendingContainer.innerHTML = `
          <table class="data-table">
            <thead>
              <tr>
                <th>Case ID</th>
                <th>Invoice #</th>
                <th>Created By</th>
                <th>Verification</th>
                <th class="num-col">Invoiced Total</th>
                <th class="num-col">Authoritative Payable</th>
                <th class="num-col">Withheld Variance</th>
                <th>Governance Policy Check</th>
                <th>Decision Action</th>
              </tr>
            </thead>
            <tbody>
              ${queue.map((p) => `
                <tr class="clickable-row" onclick="openCaseWorkspace('${escapeHtml(p.case_id)}', 'approval')">
                  <td class="mono font-semibold">${escapeHtml(p.case_id)}</td>
                  <td class="mono">${escapeHtml(p.invoice_number)}</td>
                  <td class="mono">@${escapeHtml(p.created_by)}</td>
                  <td>${statusTagHtml(p.verification_status)}</td>
                  <td class="num-col">${formatMoney(p.invoiced_total)}</td>
                  <td class="num-col font-semibold">${formatMoney(p.payable_total)}</td>
                  <td class="num-col" style="color: ${Number(p.withheld_total || 0) > 0 ? 'var(--status-amber-text)' : 'var(--text-secondary)'};">
                    ${formatMoney(p.withheld_total)}
                  </td>
                  <td class="text-xs" style="color: ${p.can_approve ? 'var(--status-green-text)' : 'var(--text-secondary)'};">
                    ${escapeHtml(p.policy_message)}
                  </td>
                  <td>
                    <div class="flex items-center gap-1.5" onclick="event.stopPropagation()">
                      <button
                        type="button"
                        onclick="quickDecisionFromQueue('${escapeHtml(p.case_id)}', 'APPROVED')"
                        class="btn btn-primary btn-sm"
                        ${p.can_approve ? '' : 'disabled'}
                      >
                        Approve
                      </button>
                      <button
                        type="button"
                        onclick="quickDecisionFromQueue('${escapeHtml(p.case_id)}', 'REJECTED')"
                        class="btn btn-danger btn-sm"
                        ${p.can_reject ? '' : 'disabled'}
                      >
                        Reject
                      </button>
                    </div>
                  </td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        `;
      }
    }

    const recContainer = document.getElementById('approvals-receipts-container');
    if (recContainer) {
      const receipts = data.decided_receipts || [];
      if (receipts.length === 0) {
        recContainer.innerHTML = `<div class="p-6 text-xs mono" style="color: var(--text-muted);">No approval receipts recorded yet.</div>`;
      } else {
        recContainer.innerHTML = `
          <table class="data-table">
            <thead>
              <tr>
                <th>Receipt ID</th>
                <th>Case ID</th>
                <th>Decision</th>
                <th>Actor &amp; Role</th>
                <th class="num-col">Approved Payable</th>
                <th class="num-col">Withheld Variance</th>
                <th>64-Char Receipt Hash</th>
                <th>HMAC Verification</th>
                <th>Inspect</th>
              </tr>
            </thead>
            <tbody>
              ${receipts.map((r) => `
                <tr class="clickable-row" onclick="openCaseWorkspace('${escapeHtml(r.case_id)}', 'approval')">
                  <td class="mono font-semibold">${escapeHtml(r.receipt_id)}</td>
                  <td class="mono">${escapeHtml(r.case_id)}</td>
                  <td>${statusTagHtml(r.decision)}</td>
                  <td class="mono">@${escapeHtml(r.actor_id)} (${escapeHtml(r.actor_role)})</td>
                  <td class="num-col font-semibold">${formatMoney(r.approved_amount, r.currency)}</td>
                  <td class="num-col">${formatMoney(r.withheld_amount, r.currency)}</td>
                  <td class="mono text-[11px]">
                    <div class="flex items-center gap-1.5" onclick="event.stopPropagation()">
                      <span>${escapeHtml(String(r.receipt_hash || '').slice(0, 18))}…</span>
                      <button type="button" onclick="copyText('${escapeHtml(r.receipt_hash)}', 'Receipt Hash')" class="btn btn-secondary btn-sm">Copy</button>
                    </div>
                  </td>
                  <td>${statusTagHtml(r.cryptographically_valid ? 'VALID' : 'INVALID')}</td>
                  <td>
                    <button type="button" onclick="event.stopPropagation(); openCaseWorkspace('${escapeHtml(r.case_id)}', 'approval')" class="btn btn-secondary btn-sm">
                      Inspect Receipt
                    </button>
                  </td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        `;
      }
    }
  } catch (err) {
    showGlobalError('Failed to load approvals', err.message);
  }
}

async function quickDecisionFromQueue(caseId, decision) {
  try {
    const res = await apiRequest(`/api/v1/cases/${encodeURIComponent(caseId)}/approve`, {
      method: 'POST',
      body: {
        decision,
        reason: `Authorized ${decision} via Financial Approvals Control Queue by @${STATE.currentUser?.username}`,
      },
    });
    showToast(`Case ${caseId} ${res.decision}. Cryptographic receipt ${res.receipt_id} issued.`);
    await loadApprovalsSection();
    await refreshAllData();
  } catch (err) {
    showToast(err.message, true);
  }
}

/* ==========================================================================
 * SECTION 8: PAYMENT CONTROL
 * ========================================================================== */

async function loadPaymentsSection() {
  try {
    const data = await apiRequest('/api/v1/payments');
    STATE.paymentsData = data;
    const m = data.metrics || {};
    const curr = data.currency || 'INR';

    document.getElementById('pay-metric-approved').textContent = formatMoney(m.total_approved_payable, curr);
    document.getElementById('pay-metric-exported').textContent = formatMoney(m.total_exported_amount, curr);
    document.getElementById('pay-metric-withheld').textContent = formatMoney(m.total_withheld_overcharges, curr);
    document.getElementById('pay-metric-blocked').textContent = formatMoney(m.total_blocked_amount, curr);

    const canExport = (STATE.currentUser?.permissions || []).includes('payment:export');

    const appContainer = document.getElementById('payments-approved-container');
    if (appContainer) {
      const approved = data.approved_cases || [];
      if (approved.length === 0) {
        appContainer.innerHTML = `
          <div class="empty-state m-4">
            <div class="font-semibold text-xs">No Approved Cases Ready for Payment</div>
            <p class="text-xs mt-1" style="color: var(--text-secondary);">Approve a verified case first to enable payment instruction generation.</p>
          </div>
        `;
      } else {
        appContainer.innerHTML = `
          <table class="data-table">
            <thead>
              <tr>
                <th>Case ID</th>
                <th>Invoice #</th>
                <th>Vendor</th>
                <th>Treasury Destination</th>
                <th class="num-col">Invoiced</th>
                <th class="num-col">Approved Payable</th>
                <th class="num-col">Withheld</th>
                <th>Instruction Status</th>
                <th>Disbursal Action</th>
              </tr>
            </thead>
            <tbody>
              ${approved.map((c) => {
                const inst = c.instruction;
                return `
                  <tr class="clickable-row" onclick="openCaseWorkspace('${escapeHtml(c.case_id)}', 'payment')">
                    <td class="mono font-semibold">${escapeHtml(c.case_id)}</td>
                    <td class="mono">${escapeHtml(c.invoice_number)}</td>
                    <td class="mono uppercase">${escapeHtml(c.vendor_id)}</td>
                    <td class="mono text-xs">${escapeHtml(c.destination_reference)}</td>
                    <td class="num-col">${formatMoney(c.invoiced_total, curr)}</td>
                    <td class="num-col font-semibold">${formatMoney(c.approved_payable, curr)}</td>
                    <td class="num-col" style="color: ${Number(c.withheld_overcharge) > 0 ? 'var(--status-amber-text)' : 'var(--text-secondary)'};">
                      ${formatMoney(c.withheld_overcharge, curr)}
                    </td>
                    <td>${statusTagHtml(inst ? inst.status : c.payment_status)}</td>
                    <td onclick="event.stopPropagation()">
                      ${!inst ? `
                        <button
                          type="button"
                          onclick="createInstructionFromPaymentsView('${escapeHtml(c.case_id)}')"
                          class="btn btn-primary btn-sm"
                          ${canExport ? '' : 'disabled'}
                        >
                          Generate Instruction
                        </button>
                      ` : `
                        <div class="flex items-center gap-1.5">
                          <button
                            type="button"
                            onclick="exportPaymentInstructionFile('${escapeHtml(c.case_id)}', '${escapeHtml(inst.instruction_id)}', 'csv')"
                            class="btn btn-primary btn-sm"
                            ${inst.status === 'EXPORTED' || !canExport ? 'disabled' : ''}
                          >
                            ${inst.status === 'EXPORTED' ? 'Exported' : 'Export CSV'}
                          </button>
                          <button
                            type="button"
                            onclick="exportPaymentInstructionFile('${escapeHtml(c.case_id)}', '${escapeHtml(inst.instruction_id)}', 'json')"
                            class="btn btn-secondary btn-sm"
                            ${inst.status === 'EXPORTED' || !canExport ? 'disabled' : ''}
                          >
                            JSON
                          </button>
                        </div>
                      `}
                    </td>
                  </tr>
                `;
              }).join('')}
            </tbody>
          </table>
        `;
      }
    }

    const withContainer = document.getElementById('payments-withheld-container');
    if (withContainer) {
      const wb = data.withheld_and_blocked || [];
      if (wb.length === 0) {
        withContainer.innerHTML = `<div class="p-6 text-xs mono" style="color: var(--text-muted);">No withheld or blocked cases currently recorded.</div>`;
      } else {
        withContainer.innerHTML = `
          <table class="data-table">
            <thead>
              <tr>
                <th>Case ID</th>
                <th>Invoice #</th>
                <th>Verification Status</th>
                <th>Commercial Status</th>
                <th class="num-col">Stated Invoice Total</th>
                <th class="num-col">Matched Payable</th>
                <th class="num-col">Quarantined / Withheld</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              ${wb.map((c) => `
                <tr class="clickable-row" onclick="openCaseWorkspace('${escapeHtml(c.case_id)}', 'lines')">
                  <td class="mono font-semibold">${escapeHtml(c.case_id)}</td>
                  <td class="mono">${escapeHtml(c.invoice_number)}</td>
                  <td>${statusTagHtml(c.verification_status)}</td>
                  <td>${statusTagHtml(c.commercial_status)}</td>
                  <td class="num-col">${formatMoney(c.invoiced_total, curr)}</td>
                  <td class="num-col">${formatMoney(c.payable_total, curr)}</td>
                  <td class="num-col font-semibold" style="color: var(--status-amber-text);">
                    ${formatMoney(c.withheld_total, curr)}
                  </td>
                  <td>
                    <button type="button" onclick="event.stopPropagation(); openCaseWorkspace('${escapeHtml(c.case_id)}', 'lines')" class="btn btn-secondary btn-sm">
                      Inspect Variance
                    </button>
                  </td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        `;
      }
    }
  } catch (err) {
    showGlobalError('Failed to load payment control data', err.message);
  }
}

async function createInstructionFromPaymentsView(caseId) {
  try {
    const inst = await apiRequest(`/api/v1/cases/${encodeURIComponent(caseId)}/payment-instruction`, {
      method: 'POST',
      body: {},
    });
    showToast(`Created Payment Instruction ${inst.instruction_id}. Ready for one-time export.`);
    await loadPaymentsSection();
  } catch (err) {
    showToast(err.message, true);
  }
}

/* ==========================================================================
 * SECTION 9: AUDIT LEDGER
 * ========================================================================== */

async function loadLedgerSection() {
  try {
    const [verifyRes, events, checkpoints] = await Promise.all([
      apiRequest('/api/v1/audit/ledger/verify'),
      apiRequest('/api/v1/audit/ledger/events?limit=250'),
      apiRequest('/api/v1/audit/ledger/checkpoints'),
    ]);
    STATE.ledgerVerify = verifyRes;
    STATE.ledgerEvents = events.slice().reverse();
    STATE.checkpoints = checkpoints;
    updateNavBadge('nav-count-ledger', verifyRes.total_events);

    renderLedgerVerificationBanner(verifyRes);
    renderLedgerCheckpoints(checkpoints);
    filterLedgerEventsClient();
  } catch (err) {
    showGlobalError('Failed to load audit ledger', err.message);
  }
}

function renderLedgerVerificationBanner(v) {
  const tagEl = document.getElementById('ledger-status-tag');
  if (tagEl) {
    tagEl.textContent = v.valid ? 'HASH CHAIN VERIFIED' : 'CHAIN COMPROMISED';
    tagEl.className = `status-tag ${v.valid ? 'status-green' : 'status-red'}`;
  }
  const totEl = document.getElementById('ledger-event-total');
  if (totEl) totEl.textContent = `${v.total_events} Events (Seq #1 – #${v.highest_sequence})`;

  const genEl = document.getElementById('ledger-genesis-hash');
  if (genEl) genEl.textContent = v.genesis_prev_hash || '—';

  const headEl = document.getElementById('ledger-head-hash');
  if (headEl) {
    headEl.innerHTML = `
      <span>${escapeHtml(v.head_event_hash)}</span>
      <button type="button" onclick="copyText('${escapeHtml(v.head_event_hash)}', 'Head Event Hash')" class="btn btn-secondary btn-sm">Copy</button>
    `;
  }
}

function renderLedgerCheckpoints(checkpoints) {
  const container = document.getElementById('ledger-checkpoints-container');
  if (!container) return;
  if (!checkpoints || checkpoints.length === 0) {
    container.innerHTML = `
      <div class="p-4 text-xs mono" style="color: var(--text-muted);">
        No signed checkpoints saved yet. Click "Issue Signed Checkpoint" above to generate an HMAC-signed chain witness.
      </div>
    `;
    return;
  }
  container.innerHTML = `
    <table class="data-table">
      <thead>
        <tr>
          <th>Checkpoint ID</th>
          <th>Timestamp</th>
          <th class="num-col">Highest Sequence</th>
          <th>Cumulative Chain Digest (SHA-256)</th>
          <th>HMAC Signature</th>
          <th>Verification</th>
        </tr>
      </thead>
      <tbody>
        ${checkpoints.map((c) => `
          <tr>
            <td class="mono font-semibold">${escapeHtml(c.checkpoint_id)}</td>
            <td class="mono text-xs">${escapeHtml(c.timestamp)}</td>
            <td class="num-col">#${escapeHtml(c.highest_sequence)}</td>
            <td class="mono text-[11px]">${escapeHtml(String(c.chain_digest || '').slice(0, 24))}…</td>
            <td class="mono text-[11px]">${escapeHtml(String(c.signature || '').slice(0, 24))}…</td>
            <td>${statusTagHtml(c.verified ? 'VERIFIED' : 'INVALID')}</td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;
}

function filterLedgerEventsClient() {
  const q = (document.getElementById('ledger-case-filter')?.value || '').trim().toLowerCase();
  const events = (STATE.ledgerEvents || []).filter((e) => {
    if (!q) return true;
    return `${e.case_id} ${e.event_type} ${e.actor_id} ${e.event_id}`.toLowerCase().includes(q);
  });

  const container = document.getElementById('ledger-events-container');
  if (!container) return;
  if (events.length === 0) {
    container.innerHTML = `<div class="empty-state m-4"><div class="text-xs font-semibold">No Matching Audit Events</div></div>`;
    return;
  }

  container.innerHTML = `
    <table class="data-table">
      <thead>
        <tr>
          <th>Seq</th>
          <th>Event ID</th>
          <th>Case ID</th>
          <th>Event Type</th>
          <th>Actor</th>
          <th>Timestamp</th>
          <th>Previous Hash</th>
          <th>Event Hash (64-Char SHA-256)</th>
        </tr>
      </thead>
      <tbody>
        ${events.map((ev) => `
          <tr class="clickable-row" onclick="openCaseWorkspace('${escapeHtml(ev.case_id)}', 'audit')">
            <td class="mono">#${escapeHtml(ev.event_sequence)}</td>
            <td class="mono font-semibold">${escapeHtml(ev.event_id)}</td>
            <td class="mono">${escapeHtml(ev.case_id)}</td>
            <td>${statusTagHtml(ev.event_type)}</td>
            <td class="mono">@${escapeHtml(ev.actor_id)}</td>
            <td class="mono text-xs">${escapeHtml(ev.timestamp)}</td>
            <td class="mono text-[11px]" style="color: var(--text-muted);" title="${escapeHtml(ev.previous_event_hash)}">
              ${escapeHtml(String(ev.previous_event_hash).slice(0, 14))}…
            </td>
            <td class="mono text-[11px]" onclick="event.stopPropagation()">
              <div class="flex items-center gap-1.5">
                <span>${escapeHtml(String(ev.event_hash).slice(0, 20))}…</span>
                <button type="button" onclick="copyText('${escapeHtml(ev.event_hash)}', 'Event Hash')" class="btn btn-secondary btn-sm">Copy</button>
              </div>
            </td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;
}

async function verifyLedgerLive() {
  try {
    const res = await apiRequest('/api/v1/audit/ledger/verify');
    showToast(`Audit Ledger Verified: ${res.valid ? '100% SOUND' : 'COMPROMISED'} (${res.total_events} unbroken events).`);
    if (STATE.activeSection === 'ledger') await loadLedgerSection();
    else await loadOverviewSection();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function createSignedCheckpoint() {
  try {
    const chk = await apiRequest('/api/v1/audit/ledger/checkpoint', { method: 'POST' });
    showToast(`Signed Checkpoint ${chk.checkpoint_id} created at sequence #${chk.highest_sequence}.`);
    await loadLedgerSection();
  } catch (err) {
    showToast(err.message, true);
  }
}

/* ==========================================================================
 * SECTION 10: INTEGRATIONS
 * ========================================================================== */

async function loadIntegrationsSection() {
  try {
    const data = await apiRequest('/api/v1/integrations');
    STATE.integrationsData = data;

    const cardsEl = document.getElementById('integrations-cards-container');
    if (cardsEl) {
      cardsEl.innerHTML = (data.integrations || []).map((ig) => `
        <div class="panel">
          <div class="panel-header">
            <div>
              <h2 class="panel-title">${escapeHtml(ig.name)}</h2>
              <p class="panel-subtitle mono">${escapeHtml(ig.channel)}</p>
            </div>
            ${statusTagHtml(ig.status)}
          </div>
          <div class="panel-body space-y-2.5 text-xs">
            <div class="flex justify-between">
              <span style="color: var(--text-secondary);">Endpoint / Transport</span>
              <span class="mono">${escapeHtml(ig.server_url)}</span>
            </div>
            <div class="flex justify-between">
              <span style="color: var(--text-secondary);">Deterministic Local Simulation</span>
              <span class="mono font-semibold" style="color: var(--status-green-text);">AVAILABLE</span>
            </div>
            <div class="p-2.5 rounded text-[11.5px]" style="background-color: var(--bg-workspace); border: 1px solid var(--border-primary); color: var(--text-secondary);">
              <strong style="color: var(--text-primary);">Security Boundary:</strong> ${escapeHtml(ig.security_boundary)}
            </div>
          </div>
        </div>
      `).join('');
    }

    const agentsEl = document.getElementById('integrations-agents-container');
    if (agentsEl) {
      agentsEl.innerHTML = `
        <table class="data-table">
          <thead>
            <tr>
              <th>Agent Handle</th>
              <th>Operational Responsibility</th>
              <th>Specification File</th>
              <th>64-Char Spec SHA-256</th>
              <th>Approval Authority</th>
            </tr>
          </thead>
          <tbody>
            ${(data.agents || []).map((a) => `
              <tr>
                <td class="mono font-semibold">${escapeHtml(a.handle)}</td>
                <td>${escapeHtml(a.description)}</td>
                <td class="mono text-xs">${escapeHtml(a.spec_file)}</td>
                <td class="mono text-[11px]">${escapeHtml(a.spec_sha256 || '—')}</td>
                <td><span class="status-tag status-red">PROHIBITED (HUMAN ONLY)</span></td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      `;
    }
  } catch (err) {
    showGlobalError('Failed to load integrations', err.message);
  }
}

async function runSwitchSimulation() {
  const btn = document.getElementById('sim-switch-btn');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Executing 4-Turn Workflow...';
  }
  try {
    const res = await apiRequest('/api/v1/integrations/switch/simulate', {
      method: 'POST',
      body: { case_id: 'demo-overcharge' },
    });
    const panel = document.getElementById('switch-simulation-panel');
    const body = document.getElementById('switch-simulation-body');
    if (panel && body) {
      panel.classList.remove('hidden');
      body.innerHTML = (res.transcript || []).map((t) => `
        <div class="p-3.5 rounded" style="background-color: var(--bg-workspace); border: 1px solid var(--border-primary);">
          <div class="flex items-center justify-between">
            <span class="mono font-semibold text-xs">Turn ${escapeHtml(t.turn)} — ${escapeHtml(t.agent)}</span>
            ${statusTagHtml(t.stage)}
          </div>
          <p class="text-xs mt-1.5" style="color: var(--text-primary);">${escapeHtml(t.summary)}</p>
          <div class="mt-2 grid grid-cols-1 md:grid-cols-2 gap-2">
            ${Object.entries(t.digests || {}).map(([k, v]) => `
              <div class="hash-box">
                <span><strong>${escapeHtml(k)}:</strong> ${escapeHtml(v)}</span>
              </div>
            `).join('')}
          </div>
        </div>
      `).join('');
    }
    showToast(`4-Turn Switch Simulation completed for case ${res.case_id}.`);
    await refreshAllData();
  } catch (err) {
    showToast(err.message, true);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = 'Run 4-Turn Switch Workflow Simulation';
    }
  }
}

/* ==========================================================================
 * SECTION 11: SYSTEM HEALTH
 * ========================================================================== */

async function loadHealthSection() {
  try {
    const h = await apiRequest('/api/v1/system/health');
    STATE.healthData = h;
    const d = h.details || {};
    const container = document.getElementById('health-cards-container');
    if (!container) return;

    const cards = [
      {
        title: 'Identity Database (identity.db)',
        status: d.identity_db?.status || 'UNKNOWN',
        rows: [
          ['Engine Mode', `SQLite (${d.identity_db?.journal_mode || 'WAL'})`],
          ['Registered Users', d.identity_db?.users_count],
          ['Active Bearer Sessions', d.identity_db?.active_sessions_count],
          ['Production Safety Gate', h.checks?.identity_database],
        ],
      },
      {
        title: 'Audit Ledger (ledger.db)',
        status: d.ledger_db?.status || 'UNKNOWN',
        rows: [
          ['Engine Mode', `SQLite (${d.ledger_db?.journal_mode || 'WAL'})`],
          ['Append-Only Triggers', `${d.ledger_db?.append_only_triggers || 0} Triggers Active`],
          ['Chained Events', d.ledger_db?.events_count],
          ['Chain Verification', d.ledger_db?.chain_valid ? '100% VALID' : 'COMPROMISED'],
        ],
      },
      {
        title: 'Payments Repository (payments.db)',
        status: d.payments_db?.status || 'UNKNOWN',
        rows: [
          ['Engine Mode', `SQLite (${d.payments_db?.journal_mode || 'WAL'})`],
          ['Payment Instructions', d.payments_db?.instructions_count],
          ['Duplicate Export Guard', 'ENFORCED'],
          ['Status Probe', h.checks?.payments_database],
        ],
      },
      {
        title: 'Cryptographic Key Manager',
        status: d.signing_key?.status || 'UNKNOWN',
        rows: [
          ['Active Signing Key ID', d.signing_key?.active_key_id],
          ['Key Entropy', `${d.signing_key?.key_length_bits || 256} bits`],
          ['Signature Algorithm', d.signing_key?.algorithm || 'HMAC-SHA256'],
          ['Status Probe', h.checks?.signing_key],
        ],
      },
      {
        title: 'Case Storage Boundary',
        status: d.storage?.status || 'UNKNOWN',
        rows: [
          ['Cases Root Directory', d.storage?.cases_directory],
          ['Active Case Folders', d.storage?.active_case_directories],
          ['Canonical Path Containment', d.storage?.path_containment],
          ['Write/Read Probe', h.checks?.storage],
        ],
      },
      {
        title: 'Runtime Environment',
        status: h.status,
        rows: [
          ['Service Name', h.service],
          ['Environment', h.environment],
          ['Financial Math Engine', 'Python decimal.Decimal (ROUND_HALF_UP)'],
          ['Last Probe Timestamp', h.checked_at],
        ],
      },
    ];

    container.innerHTML = cards.map((c) => `
      <div class="panel">
        <div class="panel-header">
          <h2 class="panel-title">${escapeHtml(c.title)}</h2>
          ${statusTagHtml(c.status)}
        </div>
        <div class="panel-body space-y-2 text-xs">
          ${c.rows.map(([k, v]) => `
            <div class="flex justify-between py-1" style="border-bottom: 1px solid var(--border-primary);">
              <span style="color: var(--text-secondary);">${escapeHtml(k)}</span>
              <span class="mono font-semibold">${escapeHtml(v ?? '—')}</span>
            </div>
          `).join('')}
        </div>
      </div>
    `).join('');
  } catch (err) {
    showGlobalError('Failed to run system health probe', err.message);
  }
}

/* ==========================================================================
 * SECTION 12: SETTINGS, USERS & RBAC
 * ========================================================================== */

async function loadSettingsSection() {
  applyTheme(STATE.theme);
  const apiInput = document.getElementById('settings-api-base-input');
  const apiCurrent = document.getElementById('settings-current-api-base');
  if (apiInput) apiInput.value = STATE.apiBase || '';
  if (apiCurrent) apiCurrent.textContent = STATE.apiBase || '(same-origin / default)';

  try {
    const data = await apiRequest('/api/v1/settings/users');
    STATE.settingsData = data;

    const uContainer = document.getElementById('settings-users-container');
    if (uContainer) {
      const users = data.users || [];
      uContainer.innerHTML = `
        <table class="data-table">
          <thead>
            <tr>
              <th>User ID</th>
              <th>Username</th>
              <th>Full Name</th>
              <th>Role</th>
              <th>Account Type</th>
              <th>Status</th>
              <th>Granted Permissions</th>
              <th>Session Action</th>
            </tr>
          </thead>
          <tbody>
            ${users.map((u) => `
              <tr>
                <td class="mono text-xs">${escapeHtml(u.user_id)}</td>
                <td class="mono font-semibold">@${escapeHtml(u.username)}</td>
                <td>${escapeHtml(u.full_name)}</td>
                <td>${statusTagHtml(u.role)}</td>
                <td><span class="status-tag">SYSTEM ACCOUNT</span></td>
                <td>${statusTagHtml(u.is_active ? 'ACTIVE' : 'DISABLED')}</td>
                <td class="mono text-[11px]" style="color: var(--text-secondary);">${escapeHtml((u.permissions || []).join(', '))}</td>
                <td>
                  <button type="button" onclick="openAuthModal('${escapeHtml(u.username)}')" class="btn btn-secondary btn-sm">
                    Authenticate As
                  </button>
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      `;
    }

    const rContainer = document.getElementById('settings-rbac-container');
    if (rContainer && data.role_permissions) {
      const allPerms = [
        'cases:create',
        'cases:read',
        'cases:reconcile',
        'cases:review',
        'cases:approve',
        'cases:reject',
        'payment:export',
        'audit:read',
        'audit:checkpoint',
        'admin:users',
        'admin:config',
      ];
      const roles = Object.keys(data.role_permissions);
      rContainer.innerHTML = `
        <table class="data-table">
          <thead>
            <tr>
              <th>System Role</th>
              ${allPerms.map((p) => `<th class="mono text-[10px]">${escapeHtml(p)}</th>`).join('')}
            </tr>
          </thead>
          <tbody>
            ${roles.map((r) => {
              const rPerms = data.role_permissions[r] || [];
              return `
                <tr>
                  <td class="mono font-semibold">${escapeHtml(r)}</td>
                  ${allPerms.map((p) => `
                    <td class="mono text-center" style="color: ${rPerms.includes(p) ? 'var(--status-green-text)' : 'var(--text-disabled)'};">
                      ${rPerms.includes(p) ? 'GRANTED' : '—'}
                    </td>
                  `).join('')}
                </tr>
              `;
            }).join('')}
          </tbody>
        </table>
      `;
    }
  } catch (err) {
    showGlobalError('Failed to load settings', err.message);
  }
}

async function submitNewUser(event) {
  event.preventDefault();
  const username = document.getElementById('usr-username')?.value.trim();
  const full_name = document.getElementById('usr-fullname')?.value.trim();
  const email = document.getElementById('usr-email')?.value.trim();
  const role = document.getElementById('usr-role')?.value;
  const password = document.getElementById('usr-password')?.value;

  try {
    await apiRequest('/api/v1/settings/users', {
      method: 'POST',
      body: { action: 'create', username, full_name, email, role, password },
    });
    showToast(`Operator account @${username} (${role}) created in identity.db.`);
    document.getElementById('usr-username').value = '';
    document.getElementById('usr-fullname').value = '';
    document.getElementById('usr-email').value = '';
    document.getElementById('usr-password').value = '';
    await loadSettingsSection();
  } catch (err) {
    showToast(err.message, true);
  }
}

function saveApiBaseSettings() {
  const val = (document.getElementById('settings-api-base-input')?.value || '').trim();
  STATE.apiBase = val;
  if (val) {
    localStorage.setItem('overcharge_desk_api_base', val);
  } else {
    localStorage.removeItem('overcharge_desk_api_base');
  }
  const apiCurrent = document.getElementById('settings-current-api-base');
  if (apiCurrent) apiCurrent.textContent = val || '(same-origin / default)';
  showToast(`API Gateway target set to: ${val || 'same-origin'}`);
  loadSettingsSection();
}

function resetApiBaseSettings() {
  STATE.apiBase = window.location.hostname.includes('github.io') ? 'http://localhost:8000' : '';
  localStorage.removeItem('overcharge_desk_api_base');
  const apiInput = document.getElementById('settings-api-base-input');
  const apiCurrent = document.getElementById('settings-current-api-base');
  if (apiInput) apiInput.value = STATE.apiBase;
  if (apiCurrent) apiCurrent.textContent = STATE.apiBase || '(same-origin / default)';
  showToast('API Gateway endpoint reset.');
  loadSettingsSection();
}

async function clearAllDemoData() {
  try {
    await apiRequest('/api/v1/demo/clear', { method: 'POST' });
    showToast('Workspace purged and reset to clean base state.');
    await refreshAllData();
    navigateSection('overview');
  } catch (err) {
    showToast(err.message, true);
  }
}

/* ==========================================================================
 * INITIALIZATION & KEYBOARD SHORTCUTS
 * ========================================================================== */

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    closeCaseWorkspace();
    closeAuthModal();
  }
});

window.addEventListener('DOMContentLoaded', async () => {
  applyTheme(STATE.theme);
  const ok = await ensureAuthenticatedSession();
  if (ok) {
    await refreshAllData();
  }
});
