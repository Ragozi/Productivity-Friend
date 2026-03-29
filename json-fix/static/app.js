/**
 * JSON_FIX — Frontend Application
 * Handles drag/drop, file analysis, issue display, and output generation.
 */

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
const state = {
  files: {},          // file_id → analysis object
  fileOrder: [],      // ordered list of file_ids
  activeFileId: null,
};

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
  initDropZone();
  document.getElementById('fileInput').addEventListener('change', onFileInputChange);
});

// ---------------------------------------------------------------------------
// Drag & Drop
// ---------------------------------------------------------------------------
function initDropZone() {
  const zone = document.getElementById('dropZone');

  zone.addEventListener('dragover', (e) => {
    e.preventDefault();
    zone.classList.add('drag-over');
  });
  zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
  zone.addEventListener('drop', (e) => {
    e.preventDefault();
    zone.classList.remove('drag-over');
    const files = Array.from(e.dataTransfer.files).filter(f => f.name.endsWith('.json'));
    if (files.length) uploadFiles(files);
  });

  zone.addEventListener('click', (e) => {
    if (e.target.classList.contains('drop-link')) return;
    document.getElementById('fileInput').click();
  });
}

function onFileInputChange(e) {
  const files = Array.from(e.target.files);
  if (files.length) uploadFiles(files);
  e.target.value = ''; // Reset so same file can be re-uploaded
}

// ---------------------------------------------------------------------------
// Upload & Analyze
// ---------------------------------------------------------------------------
async function uploadFiles(files) {
  // Add placeholder cards immediately
  const tempIds = files.map(f => {
    const tempId = 'temp_' + Math.random().toString(36).slice(2);
    addFileCard(tempId, f.name, 'loading');
    return { tempId, file: f };
  });

  const formData = new FormData();
  files.forEach(f => formData.append('files', f));

  try {
    const resp = await fetch('/upload', { method: 'POST', body: formData });
    const data = await resp.json();

    if (data.error) {
      tempIds.forEach(({ tempId }) => updateFileCard(tempId, tempId, f.name, 'error'));
      return;
    }

    // Match results to temp cards by filename order
    data.results.forEach((result, i) => {
      const tempId = tempIds[i]?.tempId;
      state.files[result.file_id] = result;
      if (!state.fileOrder.includes(result.file_id)) {
        state.fileOrder.push(result.file_id);
      }
      if (tempId) {
        replaceFileCard(tempId, result);
      } else {
        addAnalyzedFileCard(result);
      }
    });

    updateBulkBar();

    // Auto-select first file if nothing selected
    if (!state.activeFileId && data.results.length > 0) {
      selectFile(data.results[0].file_id);
    }

  } catch (err) {
    console.error('Upload failed:', err);
    tempIds.forEach(({ tempId, file }) => updateFileCard(tempId, tempId, file.name, 'error'));
  }
}

// ---------------------------------------------------------------------------
// File Card Management
// ---------------------------------------------------------------------------
function addFileCard(id, filename, status) {
  const list = document.getElementById('fileList');
  const card = document.createElement('div');
  card.className = 'file-card';
  card.id = `card-${id}`;
  card.innerHTML = fileCardHTML(id, filename, status, 0, 0);
  card.addEventListener('click', () => {
    if (!id.startsWith('temp_')) selectFile(id);
  });
  list.appendChild(card);
}

function replaceFileCard(tempId, result) {
  const old = document.getElementById(`card-${tempId}`);
  if (old) {
    const card = document.createElement('div');
    card.className = 'file-card';
    card.id = `card-${result.file_id}`;
    card.innerHTML = fileCardHTML(
      result.file_id, result.filename, result.status,
      result.critical_count, result.warning_count
    );
    card.addEventListener('click', () => selectFile(result.file_id));
    old.replaceWith(card);
  }
}

function addAnalyzedFileCard(result) {
  const list = document.getElementById('fileList');
  const card = document.createElement('div');
  card.className = 'file-card';
  card.id = `card-${result.file_id}`;
  card.innerHTML = fileCardHTML(
    result.file_id, result.filename, result.status,
    result.critical_count, result.warning_count
  );
  card.addEventListener('click', () => selectFile(result.file_id));
  list.appendChild(card);
}

function updateFileCard(tempId, fileId, filename, status) {
  const card = document.getElementById(`card-${tempId}`);
  if (card) card.innerHTML = fileCardHTML(fileId, filename, status, 0, 0);
}

function fileCardHTML(id, filename, status, critCount, warnCount) {
  const icons = { ready: '✅', needs_input: '⚠️', critical: '❌', error: '❌', loading: '⏳' };
  const labels = {
    ready: 'Ready',
    needs_input: `${warnCount} Warning${warnCount !== 1 ? 's' : ''}`,
    critical: `${critCount} Critical`,
    error: 'Error',
    loading: 'Analyzing…',
  };
  const badgeClass = {
    ready: 'badge-ready', needs_input: 'badge-needs', critical: 'badge-critical',
    error: 'badge-error', loading: 'badge-loading',
  };
  const icon = status === 'loading'
    ? '<span class="spinner"></span>'
    : `<span style="font-size:18px">${icons[status] || '📄'}</span>`;

  const shortName = filename.length > 30 ? '...' + filename.slice(-27) : filename;
  return `
    ${icon}
    <div class="file-info">
      <div class="file-name" title="${filename}">${shortName}</div>
      <div class="file-meta">${status === 'loading' ? 'Processing…' : filename}</div>
    </div>
    <span class="badge ${badgeClass[status] || ''}">${labels[status] || status}</span>
  `;
}

function updateBulkBar() {
  const count = state.fileOrder.length;
  const bar = document.getElementById('bulkBar');
  const label = document.getElementById('bulkLabel');
  bar.style.display = count >= 2 ? 'flex' : 'none';
  label.textContent = `${count} file${count !== 1 ? 's' : ''} loaded`;
}

// ---------------------------------------------------------------------------
// File Selection & Right Panel
// ---------------------------------------------------------------------------
function selectFile(fileId) {
  state.activeFileId = fileId;

  // Update active card styling
  document.querySelectorAll('.file-card').forEach(c => c.classList.remove('active'));
  const card = document.getElementById(`card-${fileId}`);
  if (card) card.classList.add('active');

  const analysis = state.files[fileId];
  if (!analysis) return;

  // Show right panel
  const rightPanel = document.getElementById('rightPanel');
  rightPanel.style.display = 'flex';

  renderRightPanel(analysis);
}

function renderRightPanel(analysis) {
  // Header
  document.getElementById('panelFilename').textContent = analysis.filename;
  document.getElementById('panelDoctype').textContent =
    `Detected: ${formatDocType(analysis.doc_type)} (${analysis.doc_type_confidence}% confidence)`;
  document.getElementById('panelStatusBadge').innerHTML =
    `<span class="badge ${statusBadgeClass(analysis.status)}">${statusLabel(analysis)}</span>`;

  // Doc type dropdown
  const select = document.getElementById('doctypeSelect');
  select.value = analysis.doc_type || 'employment_report';
  document.getElementById('doctypeReason').textContent = analysis.doc_type_reason || '';

  // Mapping table
  renderMappingTable(analysis);

  // Issues
  renderIssues(analysis);

  // Reset output area
  document.getElementById('downloadLinks').style.display = 'none';
  document.getElementById('previewSection').style.display = 'none';
  document.getElementById('generateBtn').disabled = false;
  document.getElementById('generateBtn').textContent = '⚡ Generate Fixed JSON';
}

function renderMappingTable(analysis) {
  const tbody = document.getElementById('mappingBody');
  tbody.innerHTML = '';

  const mapping = analysis.mapping || {};
  const entries = Object.entries(mapping);

  if (entries.length === 0) {
    tbody.innerHTML = '<tr><td colspan="4" style="padding:14px;color:var(--text-muted);text-align:center">No fields mapped</td></tr>';
  }

  entries.forEach(([canonical, info]) => {
    const conf = info.confidence || 0;
    const confClass = conf >= 90 ? '' : conf >= 70 ? 'medium' : 'low';
    const rowClass = info.method === 'exact' ? 'row-exact' : info.method === 'fuzzy' ? 'row-fuzzy' : 'row-none';
    const val = info.value !== null && info.value !== undefined ? String(info.value) : '—';
    const valDisplay = val.length > 30 ? val.slice(0, 28) + '…' : val;

    const tr = document.createElement('tr');
    tr.className = rowClass;
    tr.innerHTML = `
      <td style="font-family:var(--mono);font-size:11px">${escHtml(info.original_key || '')}</td>
      <td style="font-family:var(--mono);font-size:11px;color:var(--text)">${escHtml(canonical)}</td>
      <td>
        <div class="confidence-bar">
          <span class="conf-num">${conf === 100 ? 'exact' : Math.round(conf) + '%'}</span>
          <div class="conf-track"><div class="conf-fill ${confClass}" style="width:${conf}%"></div></div>
        </div>
      </td>
      <td><span class="mono-val" title="${escHtml(val)}">${escHtml(valDisplay)}</span></td>
    `;
    tbody.appendChild(tr);
  });

  // Unmapped fields
  const unmapped = analysis.unmapped || {};
  const unmappedSection = document.getElementById('unmappedSection');
  const unmappedKeys = Object.keys(unmapped);

  if (unmappedKeys.length > 0) {
    unmappedSection.innerHTML = `
      <div class="unmapped-section">
        <div class="unmapped-title">⚠ Unrecognized customer fields (${unmappedKeys.length})</div>
        <div class="unmapped-pills">
          ${unmappedKeys.map(k => `<span class="unmapped-pill" title="${escHtml(String(unmapped[k]))}">${escHtml(k)}</span>`).join('')}
        </div>
      </div>
    `;
  } else {
    unmappedSection.innerHTML = '';
  }
}

function renderIssues(analysis) {
  const container = document.getElementById('issuesBody');
  container.innerHTML = '';

  const issues = (analysis.issues || []).filter(i => i.severity !== 'INFO');
  const infoItems = (analysis.issues || []).filter(i => i.severity === 'INFO');

  if (issues.length === 0 && infoItems.length === 0) {
    container.innerHTML = '<div class="no-issues">✅ No issues found — this file looks good to go!</div>';
    return;
  }

  const wrapper = document.createElement('div');
  wrapper.className = 'issues-body';

  // CRITICAL + WARNING
  issues.forEach(issue => {
    const card = createIssueCard(issue, analysis.file_id);
    wrapper.appendChild(card);
  });

  // INFO notices (collapsed)
  if (infoItems.length > 0) {
    const infoWrap = document.createElement('div');
    infoWrap.style.marginTop = '4px';
    infoWrap.innerHTML = `<div style="font-size:12px;color:var(--text-muted);margin-bottom:6px">ℹ ${infoItems.length} auto-fix${infoItems.length !== 1 ? 'es' : ''} applied:</div>`;
    infoItems.forEach(issue => {
      const card = createIssueCard(issue, analysis.file_id);
      infoWrap.appendChild(card);
    });
    wrapper.appendChild(infoWrap);
  }

  container.appendChild(wrapper);
}

function createIssueCard(issue, fileId) {
  const sevClass = issue.severity.toLowerCase() === 'critical' ? 'critical'
    : issue.severity.toLowerCase() === 'warning' ? 'warning' : 'info';

  const card = document.createElement('div');
  card.className = `issue-card ${sevClass}`;

  const showInput = (issue.severity === 'CRITICAL' || issue.severity === 'WARNING');
  const inputId = `override-${fileId}-${issue.field}`;

  card.innerHTML = `
    <div class="issue-header">
      <span class="issue-sev">${issue.severity}</span>
      <span class="issue-field">${escHtml(issue.field)}</span>
    </div>
    <div style="padding:8px 14px 4px;font-size:12px;color:var(--text-muted)">${escHtml(issue.message)}</div>
    ${showInput ? `
      <div class="issue-input-row">
        <label for="${inputId}">Provide value:</label>
        <input
          class="issue-input"
          id="${inputId}"
          data-field="${escHtml(issue.field)}"
          placeholder="Enter ${escHtml(issue.field)}…"
          type="${issue.field === 'ssn' ? 'password' : 'text'}"
        />
      </div>
    ` : ''}
  `;
  return card;
}

// ---------------------------------------------------------------------------
// Generate Output
// ---------------------------------------------------------------------------
async function generateOutput() {
  const fileId = state.activeFileId;
  if (!fileId) return;

  const analysis = state.files[fileId];
  const btn = document.getElementById('generateBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Generating…';

  // Collect overrides from input fields
  const overrides = {};
  document.querySelectorAll('.issue-input').forEach(input => {
    const field = input.dataset.field;
    const val = input.value.trim();
    if (field && val) overrides[field] = val;
  });

  const docType = document.getElementById('doctypeSelect').value;

  try {
    const resp = await fetch('/fix', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ file_id: fileId, overrides, doc_type: docType }),
    });
    const data = await resp.json();

    if (!data.success) {
      btn.disabled = false;
      btn.textContent = '⚡ Generate Fixed JSON';
      alert(data.error || 'Generation failed');
      return;
    }

    // Show download links
    const links = document.getElementById('downloadLinks');
    links.style.display = 'flex';
    links.innerHTML = `
      <a class="download-link" href="${data.output_url}" download>
        ⬇ ${escHtml(data.output_filename)}
      </a>
      <a class="download-link" href="${data.audit_url}" download style="background:rgba(56,189,248,0.1);border-color:rgba(56,189,248,0.3);color:var(--info)">
        📋 Audit Log
      </a>
    `;

    // Update file card status
    const card = document.getElementById(`card-${fileId}`);
    if (card) {
      card.querySelector('.badge').className = 'badge badge-ready';
      card.querySelector('.badge').textContent = 'Done';
    }

    // Show preview (truncated)
    const preview = document.getElementById('codePreview');
    const previewStr = JSON.stringify(data.preview, null, 2);
    preview.textContent = previewStr.length > 3000
      ? previewStr.slice(0, 3000) + '\n\n… (truncated — download for full output)'
      : previewStr;
    document.getElementById('previewSection').style.display = 'block';

    btn.disabled = false;
    btn.textContent = '✅ Done — Regenerate';

  } catch (err) {
    console.error('Fix failed:', err);
    btn.disabled = false;
    btn.textContent = '⚡ Generate Fixed JSON';
    alert('An error occurred. Check the console.');
  }
}

// ---------------------------------------------------------------------------
// Bulk Fix
// ---------------------------------------------------------------------------
async function bulkFix() {
  const fileIds = state.fileOrder;
  if (!fileIds.length) return;

  const files = fileIds.map(fid => ({
    file_id: fid,
    overrides: {},
    doc_type: state.files[fid]?.doc_type || 'employment_report',
  }));

  try {
    const resp = await fetch('/bulk_fix', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ files }),
    });
    const data = await resp.json();

    if (data.success) {
      // Trigger ZIP download
      const a = document.createElement('a');
      a.href = data.zip_url;
      a.download = data.zip_filename;
      a.click();
    }
  } catch (err) {
    console.error('Bulk fix failed:', err);
    alert('Bulk fix failed. Check console.');
  }
}

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------
function toggleSettings() {
  document.getElementById('settingsPanel').classList.toggle('open');
}

function saveSettings() {
  alert('Settings persistence coming in Phase 2! (Truv sandbox integration)');
}

function onDoctypeChange() {
  // Just updates the local selection; applied at generation time
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------
function formatDocType(type) {
  const labels = {
    user_create: 'User Creation',
    bridge_token: 'Bridge Token',
    employment_report: 'Employment Report',
    bulk_records: 'Bulk Records',
    unknown: 'Unknown',
  };
  return labels[type] || type;
}

function statusBadgeClass(status) {
  return {
    ready: 'badge-ready',
    needs_input: 'badge-needs',
    critical: 'badge-critical',
    error: 'badge-error',
  }[status] || 'badge-info';
}

function statusLabel(analysis) {
  if (analysis.status === 'ready') return '✅ Ready';
  if (analysis.status === 'needs_input') return `⚠ ${analysis.warning_count} Warning${analysis.warning_count !== 1 ? 's' : ''}`;
  if (analysis.status === 'critical') return `❌ ${analysis.critical_count} Critical`;
  if (analysis.status === 'error') return '❌ Error';
  return analysis.status;
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
