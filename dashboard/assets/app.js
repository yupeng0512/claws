/* CLAWS Command Center — Dashboard Controller */

const API = '';
let refreshTimer = null;

// ── Tab Navigation ──

document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    const panel = document.getElementById('panel-' + btn.dataset.tab);
    if (panel) panel.classList.add('active');
    onTabSwitch(btn.dataset.tab);
  });
});

function onTabSwitch(tab) {
  clearInterval(refreshTimer);
  refreshTimer = null;
  switch (tab) {
    case 'dashboard': loadStatus(); refreshTimer = setInterval(loadStatus, 15000); break;
    case 'discoveries': loadDiscoveries(); loadTodayExploration(); break;
    case 'memory': break;
    case 'scheduler': loadSchedule(); break;
    case 'logs': loadLogs(); refreshTimer = setInterval(loadLogs, 10000); break;
  }
}

// ── API Helpers ──

async function apiFetch(path) {
  try {
    const r = await fetch(API + path);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return await r.json();
  } catch (e) {
    console.error('API error:', path, e);
    return null;
  }
}

async function apiPost(path) {
  try {
    const r = await fetch(API + path, { method: 'POST' });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return await r.json();
  } catch (e) {
    console.error('API error:', path, e);
    return null;
  }
}

// ── Toast ──

function toast(msg, type = 'info') {
  const container = document.getElementById('toastContainer');
  const el = document.createElement('div');
  el.className = 'toast ' + type;
  el.textContent = msg;
  container.appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; setTimeout(() => el.remove(), 200); }, 3000);
}

// ── Clock ──

function updateClock() {
  const now = new Date();
  const pad = n => String(n).padStart(2, '0');
  document.getElementById('headerTime').textContent =
    `${now.getFullYear()}-${pad(now.getMonth()+1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
}
setInterval(updateClock, 1000);
updateClock();

// ── Dashboard Tab ──

async function loadStatus() {
  const data = await apiFetch('/api/status');
  if (!data) {
    setBeacon(false);
    return;
  }
  setBeacon(true);
  renderPipeline(data.pipeline);
  renderRecentRuns(data.recent_runs || []);
  renderMemoryStats(data.memory || {});
}

function setBeacon(online) {
  const dot = document.querySelector('.beacon-dot');
  const label = document.getElementById('beaconLabel');
  if (online) {
    dot.className = 'beacon-dot online';
    label.textContent = 'ONLINE';
  } else {
    dot.className = 'beacon-dot error';
    label.textContent = 'OFFLINE';
  }
}

function renderPipeline(pipeline) {
  const phases = ['sense', 'dive', 'reflect', 'review'];
  phases.forEach(phase => {
    const node = document.querySelector(`.pipeline-node[data-phase="${phase}"]`);
    if (!node) return;
    const info = pipeline[phase];
    if (!info) { node.dataset.status = 'pending'; return; }
    node.dataset.status = info.status || 'pending';
  });
}

function renderRecentRuns(runs) {
  const el = document.getElementById('recentRuns');
  if (!runs.length) { el.innerHTML = '<div class="empty-state">暂无执行记录</div>'; return; }
  el.innerHTML = runs.slice().reverse().map(r => {
    const errorHtml = r.error ? `<span class="run-error" title="${esc(r.error)}">${esc(r.error.substring(0, 50))}</span>` : '';
    const statusColor = r.error ? 'var(--error)' : 'var(--success)';
    return `<div class="run-item">
      <span class="run-phase" style="color:${statusColor}">${esc(r.phase)}</span>
      <span class="run-meta">${r.elapsed_s}s · ${r.chars} chars</span>
      ${errorHtml}
    </div>`;
  }).join('');
}

function renderMemoryStats(stats) {
  const el = document.getElementById('memoryStats');
  const entries = Object.entries(stats).filter(([k]) => k !== '_total');
  const total = stats._total || {};
  if (!entries.length) { el.innerHTML = '<div class="empty-state">无数据</div>'; return; }
  let html = entries.map(([name, s]) =>
    `<div class="mem-stat">
      <div class="mem-stat-name">${esc(name)}</div>
      <div class="mem-stat-value">${s.files}</div>
      <div class="mem-stat-sub">${s.size_kb} KB</div>
    </div>`
  ).join('');
  if (total.files !== undefined) {
    html += `<div class="mem-stat" style="border-color:var(--accent-amber-dim)">
      <div class="mem-stat-name">TOTAL</div>
      <div class="mem-stat-value">${total.files}</div>
      <div class="mem-stat-sub">${total.size_kb} KB</div>
    </div>`;
  }
  el.innerHTML = html;
}

// ── Discoveries Tab ──

async function loadDiscoveries() {
  const dateVal = document.getElementById('discDate').value;
  const query = dateVal ? `?date=${dateVal}` : '';
  const data = await apiFetch('/api/discoveries' + query);
  const el = document.getElementById('discoveriesList');
  if (!data || !data.items.length) { el.innerHTML = '<div class="empty-state">暂无发现</div>'; return; }
  el.innerHTML = data.items.map(d => {
    const fields = d.fields || {};
    const fieldHtml = Object.entries(fields).map(([k, v]) =>
      `<div class="disc-field"><strong>${esc(k)}:</strong> ${esc(v)}</div>`
    ).join('');
    return `<div class="disc-item">
      <div class="disc-title"><span class="disc-date">[${esc(d.date)}]</span>${esc(d.title)}</div>
      ${fieldHtml}
    </div>`;
  }).join('');
}

async function loadTodayExploration() {
  const data = await apiFetch('/api/discoveries/today');
  const el = document.getElementById('todayExploration');
  if (!data) { el.innerHTML = '<div class="empty-state">加载失败</div>'; return; }
  const allFiles = [...(data.filtered || []), ...(data.deep_dives || [])];
  if (!allFiles.length) { el.innerHTML = '<div class="empty-state">今日暂无探索数据</div>'; return; }
  el.innerHTML = allFiles.map(f =>
    `<div class="exploration-file">
      <div class="exploration-filename">${esc(f.file)}</div>
      <div class="exploration-content">${esc(f.content.substring(0, 1500))}</div>
    </div>`
  ).join('');
}

// ── Memory Search ──

async function searchMemory() {
  const q = document.getElementById('memoryQuery').value.trim();
  if (!q) return;
  const data = await apiFetch(`/api/memory/search?q=${encodeURIComponent(q)}&top_k=10`);
  const el = document.getElementById('memoryResults');
  if (!data || !data.results.length) {
    el.innerHTML = '<div class="empty-state">未找到相关记忆</div>';
    return;
  }
  el.innerHTML = data.results.map(r => {
    const path = r.path || r[0] || '';
    const snippet = r.snippet || r[1] || '';
    const score = r.score || r[2] || '';
    return `<div class="mem-result">
      <div class="mem-result-path">${esc(path)}</div>
      <div class="mem-result-snippet">${esc(snippet.substring(0, 400))}</div>
      ${score ? `<div class="mem-result-score">relevance: ${score}</div>` : ''}
    </div>`;
  }).join('');
}

// ── Schedule Tab ──

async function loadSchedule() {
  const data = await apiFetch('/api/schedule');
  const el = document.getElementById('scheduleTable');
  if (!data) { el.innerHTML = '<div class="empty-state">加载失败</div>'; return; }
  let html = '<div class="sched-row"><span>PHASE</span><span>AGENT</span><span>SCHEDULE</span><span>NEXT RUN</span></div>';
  for (const [phase, cfg] of Object.entries(data)) {
    const schedule = cfg.interval_hours ? `every ${cfg.interval_hours}h` : (cfg.cron || '—');
    const next = cfg.next_run ? formatTime(cfg.next_run) : '—';
    html += `<div class="sched-row">
      <span class="sched-phase">${esc(phase.toUpperCase())}</span>
      <span>${esc(cfg.agent || '—')}</span>
      <span class="sched-cron">${esc(schedule)}</span>
      <span class="sched-next">${esc(next)}</span>
    </div>`;
  }
  el.innerHTML = html;
}

// ── Trigger ──

async function triggerPhase(phase) {
  const data = await apiPost(`/api/trigger/${phase}`);
  if (data) {
    toast(`${phase.toUpperCase()} 已触发`, 'success');
  } else {
    toast(`触发 ${phase} 失败`, 'error');
  }
}

// ── Logs Tab ──

async function loadLogs() {
  const data = await apiFetch('/api/logs/recent?lines=200');
  const el = document.getElementById('logViewer');
  if (!data || !data.lines.length) { el.innerHTML = '<span class="empty-state">暂无日志</span>'; return; }
  el.innerHTML = data.lines.map(line => {
    let cls = 'log-line-info';
    if (line.includes('[ERROR]') || line.includes('失败')) cls = 'log-line-error';
    else if (line.includes('[WARNING]') || line.includes('⚠️')) cls = 'log-line-warning';
    return `<span class="${cls}">${esc(line)}\n</span>`;
  }).join('');
  el.scrollTop = el.scrollHeight;
}

// ── Utilities ──

function esc(str) {
  if (!str) return '';
  const d = document.createElement('div');
  d.textContent = String(str);
  return d.innerHTML;
}

function formatTime(isoStr) {
  try {
    const d = new Date(isoStr);
    const pad = n => String(n).padStart(2, '0');
    return `${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  } catch { return isoStr; }
}

// ── Init ──

loadStatus();
refreshTimer = setInterval(loadStatus, 15000);
