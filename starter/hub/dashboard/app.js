/* SalesPulse Hub — live dashboard */
'use strict';

let _accounts = [];
let _actions  = [];
let _signals  = [];
let _selectedAction = null;
let _renderedOnce = false;
let _lastFingerprint = '';

// ── SSE ───────────────────────────────────────────────────────────────
const es = new EventSource('/stream');
es.addEventListener('state', (e) => {
  const data = JSON.parse(e.data);
  _accounts = data.accounts || [];
  _actions  = data.actions  || [];
  for (const acc of _accounts) {
    for (const sig of (acc.signals || []).slice(-3))
      _signals.unshift({ ...sig, accountName: acc.name });
  }
  if (_signals.length > 60) _signals.length = 60;

  const fp = `${_accounts.length}:${_actions.length}:${_accounts.filter(a=>a.riskFlags?.length).length}`;
  if (fp === _lastFingerprint) return;
  _lastFingerprint = fp;

  render();
  renderAgentStrip(data.agentActivity || []);
});
es.addEventListener('error', () => {
  const b = document.getElementById('status-badge');
  b.className = 'badge-live offline';
  b.innerHTML = '<span class="pulse-dot"></span>DISCONNECTED';
});
es.addEventListener('open', () => {
  const b = document.getElementById('status-badge');
  b.className = 'badge-live';
  b.innerHTML = '<span class="pulse-dot"></span>LIVE';
});

// Poll quota and safety every 15s
async function refreshExtras() {
  try {
    const q = await (await fetch('/api/quota')).json();
    document.getElementById('val-actions').textContent = String(_actions.length);
  } catch {}
  if (document.getElementById('tab-safety')?.classList.contains('tab-content--active')) {
    renderSafety();
  }
}
setInterval(refreshExtras, 15_000);

// ── Tab switching ─────────────────────────────────────────────────────
function switchTab(name, btn) {
  document.querySelectorAll('.tab-content').forEach(el => {
    el.classList.remove('tab-content--active');
    el.style.display = 'none';
  });
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('tab-btn--active'));
  const target = document.getElementById(`tab-${name}`);
  if (target) { target.classList.add('tab-content--active'); target.style.display = 'flex'; }
  btn.classList.add('tab-btn--active');
  if (name === 'safety') renderSafety();
}

// ── Render ────────────────────────────────────────────────────────────
function render() {
  renderKPIs();
  renderAccounts();
  renderActions();
  renderSignals();
}

function renderKPIs() {
  const oppsOf = a => Array.isArray(a.opportunities)
    ? a.opportunities : Object.values(a.opportunities || {});

  const pipeline  = _accounts.reduce((s, a) => s + oppsOf(a).reduce((t, o) => t + (o.value||0), 0), 0);
  const atRisk    = _accounts.filter(a => (a.riskFlags||[]).length)
                              .reduce((s, a) => s + oppsOf(a).reduce((t,o) => t + (o.value||0), 0), 0);
  const gapCount  = _accounts.filter(a => (a.riskFlags||[]).includes('rep_transition')).length;
  const csTotal   = _actions.filter(a => a.action === 'cross_sell_recommendation')
                             .reduce((s, a) => s + ((a.target||{}).value || 0), 0);

  animVal('val-pipeline',  fmtMoney(pipeline));
  animVal('val-atrisk',    fmtMoney(atRisk));
  animVal('val-gaps',      String(gapCount));
  animVal('val-crosssell', fmtMoney(csTotal));
  animVal('val-actions',   String(_actions.length));
  document.getElementById('account-count').textContent = _accounts.length;
}

function animVal(id, text) {
  const el = document.getElementById(id);
  if (el.textContent === text) return;
  el.style.opacity = '0';
  el.style.transform = 'translateY(6px)';
  requestAnimationFrame(() => {
    el.textContent = text;
    el.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
    el.style.opacity = '1';
    el.style.transform = 'translateY(0)';
  });
}

function renderAccounts() {
  const grid = document.getElementById('account-grid');
  if (!_accounts.length) return;
  const sorted = [..._accounts].sort((a, b) => (a.healthScore||80) - (b.healthScore||80));
  grid.innerHTML = sorted.map((acc, i) => cardHTML(acc, i)).join('');
  _renderedOnce = true;  // subsequent renders skip entry animation
}

function cardHTML(acc, idx) {
  const score = acc.healthScore ?? 80;
  const tier  = score < 55 ? 'high' : score < 72 ? 'medium' : 'low';
  const opps  = Array.isArray(acc.opportunities) ? acc.opportunities : Object.values(acc.opportunities||{});
  const val   = opps.reduce((s, o) => s + (o.value||0), 0);
  const flags = acc.riskFlags || [];
  const action = _actions.find(a => a.target?.accountId === acc.accountId ||
                                     a.accountId         === acc.accountId);

  // SVG ring: circumference of r=15 circle ≈ 94.25
  const circ = 94.25;
  const dash = (score / 100) * circ;

  return `
<div class="account-card account-card--${tier}"
     style="${_renderedOnce ? '' : `animation-delay:${idx * 35}ms`}"
     onclick="showAccountActions('${esc(acc.accountId)}')">
  <div class="card-header">
    <div class="card-meta">
      <div class="card-name">${esc(acc.name || acc.accountId)}</div>
      <div class="card-sub">${esc(acc.accountId)} · ${esc(acc.territory || acc.country || '')}</div>
    </div>
    <div class="health-ring-wrap">
      <svg class="health-ring" viewBox="0 0 36 36">
        <circle class="ring-bg"  cx="18" cy="18" r="15"/>
        <circle class="ring-fill ring-fill--${tier}" cx="18" cy="18" r="15"
                stroke-dasharray="${dash.toFixed(1)} ${(circ - dash).toFixed(1)}"
                stroke-dashoffset="0"/>
      </svg>
      <span class="health-num health-num--${tier}">${score}</span>
    </div>
  </div>
  ${flags.length ? `<div class="risk-flags">${flags.map(f => `<span class="flag flag--${f}">${f.replace(/_/g,' ')}</span>`).join('')}</div>` : ''}
  ${val > 0 ? `<div class="card-pipeline">Pipeline <strong>${fmtMoney(val)}</strong></div>` : ''}
  ${action ? `
  <div class="card-action">
    <span class="abadge abadge--${action.autonomy}">${action.autonomy}</span>
    <span class="card-action-text">${esc(action.action?.replace(/_/g,' ')||'')}</span>
  </div>` : ''}
</div>`;
}

function renderActions() {
  const list = document.getElementById('action-list');
  document.getElementById('action-count').textContent = _actions.length;
  if (!_actions.length) { list.innerHTML = '<p class="empty-state">No actions yet.</p>'; return; }
  list.innerHTML = _actions.slice(0, 20).map((act, i) => actionHTML(act, i)).join('');
}

function actionHTML(act, idx) {
  const conf = Math.round(((act.confidence||0)) * 100);
  const val  = fmtMoney((act.target||{}).value || act.revenueAtStake || 0);
  const auto = act.autonomy || act.autonomyLevel || 'recommend';
  const name = act.accountName || (act.target||{}).accountId || act.accountId || '?';
  return `
<div class="action-item action-item--${auto}"
     style="animation-delay:${idx*25}ms"
     onclick="openActionModal('${esc(act.eventId||'')}')">
  <div class="ai-header">
    <span class="ai-account">${esc(name)}</span>
    <span class="abadge abadge--${auto}">${auto}</span>
  </div>
  <div class="ai-action">${esc(act.action||'')}</div>
  <div class="ai-detail">${esc(act.actionDetail || act.reasoning || '')}</div>
  <div class="ai-footer">
    <div class="conf-track"><div class="conf-fill" style="width:${conf}%"></div></div>
    <span class="conf-val">${conf}% · ${val}</span>
  </div>
</div>`;
}

function renderSignals() {
  const log = document.getElementById('signal-log');
  if (!_signals.length) return;
  log.innerHTML = _signals.slice(0, 30).map((s, i) => `
<li class="signal-item signal-item--${s.severity||'low'}" style="animation-delay:${i*15}ms">
  <span class="signal-src signal-src--${(s.source||'').replace(/[^a-z_]/gi,'')}">${(s.source||'?').slice(0,7)}</span>
  <span class="signal-txt" title="${esc(s.summary||'')}">
    ${s.accountName ? `<b>${esc(s.accountName)}</b> — ` : ''}${esc(s.summary||s.type||'')}
  </span>
</li>`).join('');
}

// ── Modal ─────────────────────────────────────────────────────────────
function openActionModal(eventId) {
  const act = _actions.find(a => a.eventId === eventId);
  if (!act) return;
  _selectedAction = act;

  const t  = act.target || {};
  const br = act.blastRadius || {};
  const auto = act.autonomy || act.autonomyLevel || '?';

  document.getElementById('modal-title').textContent =
    `${(act.action||'').replace(/_/g,' ')} — ${act.accountName || t.accountId || act.accountId || ''}`;

  document.getElementById('modal-body').innerHTML = `
    <div class="row"><span class="row-label">Agent</span><span class="row-value">${esc(act.agent||'?')}</span></div>
    <div class="row"><span class="row-label">Revenue at stake</span><span class="row-value">${fmtMoney(t.value || act.revenueAtStake || 0)} ${esc(t.currency||'EUR')}</span></div>
    <div class="row"><span class="row-label">Blast class</span><span class="row-value">${esc(br.class||'?')} — reach ${br.reach||1} · ${br.reversible===false?'irreversible':'reversible'} · ${br.external?'external':'internal'}</span></div>
    <div class="row"><span class="row-label">Autonomy</span><span class="row-value">${esc(auto)}</span></div>
    <div class="row"><span class="row-label">Confidence</span><span class="row-value">${Math.round((act.confidence||0)*100)}%</span></div>
    ${act.timingHours ? `<div class="row"><span class="row-label">Act within</span><span class="row-value">${act.timingHours}h</span></div>` : ''}
    ${act.reasoning ? `<div class="reasoning-block">${esc(act.reasoning)}</div>` : ''}
    ${act.execBrief || act.revenueOutcome ? `<div class="brief-block">${esc(act.execBrief || act.revenueOutcome)}</div>` : ''}
  `;
  document.getElementById('modal-overlay').classList.remove('hidden');
}

function showAccountActions(accountId) {
  const act = _actions.find(a =>
    (a.target||{}).accountId === accountId || a.accountId === accountId
  );
  if (act) openActionModal(act.eventId || '');
}

function closeModal() {
  document.getElementById('modal-overlay').classList.add('hidden');
  _selectedAction = null;
}

document.getElementById('modal-close').onclick    = closeModal;
document.getElementById('modal-overlay').onclick  = e => { if (e.target.id === 'modal-overlay') closeModal(); };
document.getElementById('modal-approve').onclick  = () => { logDecision('approved');  closeModal(); };
document.getElementById('modal-escalate').onclick = () => { logDecision('escalated'); closeModal(); };
document.getElementById('modal-dismiss').onclick  = () => { logDecision('dismissed'); closeModal(); };

function logDecision(decision) {
  if (!_selectedAction) return;
  console.info('Decision:', decision, _selectedAction.eventId);
}

// ── Helpers ───────────────────────────────────────────────────────────
function fmtMoney(v) {
  if (v >= 1_000_000) return `€${(v/1_000_000).toFixed(1)}M`;
  if (v >= 1_000)     return `€${(v/1_000).toFixed(0)}K`;
  return v > 0 ? `€${v}` : '—';
}

function esc(str) {
  return String(str ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Agent strip ───────────────────────────────────────────────────────
const _ALL_AGENTS = [
  'account_intelligence','sales_continuity','fastflow',
  'cross_sell','buyer_movement','deal_velocity','supply_delivery',
];

function renderAgentStrip(activity) {
  const strip = document.getElementById('agent-strip');
  if (!strip) return;
  const map = {};
  for (const a of activity) map[a.agent] = a;

  strip.innerHTML = _ALL_AGENTS.map(ag => {
    const info = map[ag];
    const count = info?.count || 0;
    const active = count > 0;
    const label = ag.replace(/_/g, ' ');
    return `
<div class="agent-card ${active ? 'agent-card--active' : ''}">
  <span class="agent-dot ${active ? 'agent-dot--active' : 'agent-dot--idle'}"></span>
  <span class="agent-name">${label}</span>
  <span class="agent-count">${count > 0 ? count : '—'}</span>
</div>`;
  }).join('');
}

// ── Safety & rollout panel ────────────────────────────────────────────
async function renderSafety() {
  const panel = document.getElementById('safety-panel');
  if (!panel) return;
  let data;
  try { data = await (await fetch('/api/safety')).json(); }
  catch { panel.innerHTML = '<p class="empty-state">Unavailable.</p>'; return; }

  const { totalActions, blastCounts: bc, autonomyCounts: ac, cohortCounts: cc, agentCounts, unsafeActions } = data;
  const tot = Math.max(totalActions, 1);
  const mkBar = (val, total, col) => {
    const pct = Math.round((val/total)*100);
    return `<div class="safety-seg" style="flex:${pct || 1};background:${col};opacity:${pct?1:0.2}" title="${pct}%"></div>`;
  };

  panel.innerHTML = `
<div class="unsafe-counter">
  <div>
    <div class="unsafe-num">${unsafeActions}</div>
    <div class="unsafe-lbl">escalated to human approval</div>
  </div>
  <span class="abadge abadge--escalate">HIGH BLAST</span>
</div>

<div class="safety-section">
  <h4>Autonomy distribution (${totalActions} actions)</h4>
  <div class="safety-bar">
    ${mkBar(ac.act||0, tot, 'var(--green)')}
    ${mkBar(ac.recommend||0, tot, 'var(--yellow)')}
    ${mkBar(ac.escalate||0, tot, 'var(--red)')}
  </div>
  <div class="safety-row"><span class="safety-label">🟢 Act autonomous</span><span class="safety-val">${ac.act||0}</span></div>
  <div class="safety-row"><span class="safety-label">🟡 Recommend</span><span class="safety-val">${ac.recommend||0}</span></div>
  <div class="safety-row"><span class="safety-label">🔴 Escalate</span><span class="safety-val">${ac.escalate||0}</span></div>
</div>

<div class="safety-section">
  <h4>By blast class</h4>
  <div class="safety-row"><span class="safety-label">Low blast</span><span class="safety-val">${bc.low||0}</span></div>
  <div class="safety-row"><span class="safety-label">Medium blast</span><span class="safety-val">${bc.medium||0}</span></div>
  <div class="safety-row"><span class="safety-label">High blast</span><span class="safety-val">${bc.high||0}</span></div>
</div>

<div class="safety-section">
  <h4>By market cohort</h4>
  ${Object.entries(cc||{}).sort((a,b)=>b[1]-a[1]).map(([co,n])=>`
    <div class="safety-row"><span class="safety-label">${co}</span><span class="safety-val">${n}</span></div>
  `).join('')}
</div>`;
}

// ── Chat ──────────────────────────────────────────────────────────────
function toggleChat() {
  const panel = document.getElementById('chat-panel');
  panel.classList.toggle('hidden');
  if (!panel.classList.contains('hidden'))
    document.getElementById('chat-input').focus();
}

function askChat(q) {
  document.getElementById('chat-input').value = q;
  sendChat();
}

let _chatSeq = 0;  // unique ID per bubble — prevents duplicate-id conflicts

// ── Chat response formatter ───────────────────────────────────────────
// Apply inline highlights to an already-HTML-escaped string.
function _fmtInline(escaped) {
  return escaped
    .replace(/\b([A-Z]{2}-\d{3,})\b/g,  '<b class="hi-acct">$1</b>')
    .replace(/€([\d,]+)/g,               '<span class="hi-eur">€$1</span>')
    .replace(/health\s+(\d+)/gi,         'health <span class="hi-score">$1</span>');
}

// Convert the plain-text response from /api/chat into rich HTML.
function _toHtml(raw) {
  if (!raw) return '';
  const lines = raw.split('\n').filter(l => l.trim());
  if (!lines.length) return '';

  // Single paragraph (greeting, short answer) — conversational style, no header
  if (lines.length === 1) {
    return `<div class="chat-para">${_fmtInline(esc(lines[0]))}</div>`;
  }

  let html = '';
  let first = true;
  for (const line of lines) {
    const t = line.trim();
    if (!t) continue;
    if (first) {
      // Strip trailing colon — header is a label, not a sentence
      html += `<div class="chat-h">${esc(t.replace(/:$/, ''))}</div>`;
      first = false;
    } else if (t.startsWith('•') || t.startsWith('▸') || t.startsWith('-')) {
      const content = t.replace(/^[•▸\-]\s*/, '');
      html += `<div class="chat-item"><span class="chat-dot">▸</span><span>${_fmtInline(esc(content))}</span></div>`;
    } else {
      html += `<div class="chat-line">${_fmtInline(esc(t))}</div>`;
    }
  }
  return html;
}

function _typewrite(bubble, html, msgs) {
  // Render all HTML at once, then stagger each row in with a smooth fade+slide.
  bubble.innerHTML = html;
  const rows = Array.from(bubble.querySelectorAll('.chat-h, .chat-item, .chat-line'));
  if (rows.length) {
    rows.forEach((el, i) => {
      el.style.opacity = '0';
      el.style.transform = 'translateY(6px)';
      el.style.transition = `opacity 0.22s ease ${i * 75}ms, transform 0.22s ease ${i * 75}ms`;
      // Trigger reflow so transition fires
      requestAnimationFrame(() => requestAnimationFrame(() => {
        el.style.opacity = '1';
        el.style.transform = 'translateY(0)';
      }));
    });
    // Keep scrolling as rows appear
    const iv = setInterval(() => msgs.scrollTop = msgs.scrollHeight, 80);
    setTimeout(() => clearInterval(iv), rows.length * 75 + 300);
  } else {
    // Plain single-line fallback
    bubble.style.opacity = '0';
    bubble.style.transition = 'opacity 0.25s ease';
    requestAnimationFrame(() => requestAnimationFrame(() => { bubble.style.opacity = '1'; }));
  }
}

async function sendChat() {
  const input = document.getElementById('chat-input');
  const q = input.value.trim();
  if (!q) return;
  input.value = '';

  const msgs = document.getElementById('chat-messages');
  const loadingId = `chat-loading-${++_chatSeq}`;

  msgs.insertAdjacentHTML('beforeend', `<div class="chat-bubble chat-bubble--user">${esc(q)}</div>`);
  msgs.insertAdjacentHTML('beforeend', `<div class="chat-bubble chat-bubble--agent" id="${loadingId}"><div class="typing-indicator"><span></span><span></span><span></span></div></div>`);
  msgs.scrollTop = msgs.scrollHeight;

  try {
    const r = await fetch('/api/chat', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({query: q}) });
    const data = await r.json();
    const bubble = document.getElementById(loadingId);
    if (bubble) {
      _typewrite(bubble, _toHtml(data.response || '(no response)'), msgs);
    }
  } catch {
    const bubble = document.getElementById(loadingId);
    if (bubble) bubble.textContent = 'Error contacting hub.';
  }
}
