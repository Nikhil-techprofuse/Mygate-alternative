// ── MyGate Shared JS API Client ────────────────────────────────────────────
// Dynamically resolve API base so it works on any IP/host
const API_BASE = window.location.origin + '/api';
// Each portal sets window.MG_PORTAL before loading this file so their tokens
// never overwrite each other in localStorage (all portals share the same origin).
const _pfx = (window.MG_PORTAL || 'mg') + '_';
const Auth = {
  get token()    { return localStorage.getItem(_pfx + 'token'); },
  get role()     { return localStorage.getItem(_pfx + 'role'); },
  get userId()   { return localStorage.getItem(_pfx + 'user_id'); },
  get societyId(){ return localStorage.getItem(_pfx + 'society_id'); },
  get flatId()   { return localStorage.getItem(_pfx + 'flat_id'); },
  save(data) {
    localStorage.setItem(_pfx + 'token',      data.access_token);
    localStorage.setItem(_pfx + 'refresh',    data.refresh_token);
    localStorage.setItem(_pfx + 'role',       data.role || '');
    localStorage.setItem(_pfx + 'user_id',    data.user_id || '');
    localStorage.setItem(_pfx + 'society_id', data.society_id || '');
    localStorage.setItem(_pfx + 'flat_id',    data.flat_id || '');
  },
  clear() {
    ['token','refresh','role','user_id','society_id','flat_id']
      .forEach(k => localStorage.removeItem(_pfx + k));
  },
  isLoggedIn() { return !!this.token; }
};
async function apiFetch(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
  if (Auth.token) headers['Authorization'] = `Bearer ${Auth.token}`;
  const res = await fetch(API_BASE + path, { ...options, headers });
  if (res.status === 401) {
    // Try refresh
    const refresh = localStorage.getItem(_pfx + 'refresh');
    if (refresh) {
      const rr = await fetch(API_BASE + '/auth/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refresh }),
      });
      if (rr.ok) {
        const nd = await rr.json();
        localStorage.setItem(_pfx + 'token', nd.access_token);
        headers['Authorization'] = `Bearer ${nd.access_token}`;
        return fetch(API_BASE + path, { ...options, headers });
      }
    }
    Auth.clear();
    window.location.href = '/';
  }
  return res;
}
// ── Toast ─────────────────────────────────────────────────────────────────
function toast(msg, type = '') {
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    document.body.appendChild(container);
  }
  const t = document.createElement('div');
  t.className = `toast ${type}`;
  t.textContent = msg;
  container.appendChild(t);
  setTimeout(() => t.remove(), 3000);
}
// ── Supabase Realtime subscription helper ─────────────────────────────────
function subscribeRealtime(supabaseClient, table, filter, callback) {
  return supabaseClient
    .channel(`rt-${table}-${Date.now()}`)
    .on('postgres_changes', { event: '*', schema: 'public', table, filter }, callback)
    .subscribe();
}
// ── Date helpers ──────────────────────────────────────────────────────────
function fmtDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' });
}
function timeAgo(iso) {
  const diff = Math.floor((Date.now() - new Date(iso)) / 1000);
  if (diff < 60)   return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff/60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff/3600)}h ago`;
  return `${Math.floor(diff/86400)}d ago`;
}
// ── Page router (SPA) ─────────────────────────────────────────────────────
function showPage(id) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.bottom-nav a, .sidebar a').forEach(a => a.classList.remove('active'));
  const page = document.getElementById(id);
  if (page) page.classList.add('active');
  const navLink = document.querySelector(`[data-page="${id}"]`);
  if (navLink) navLink.classList.add('active');
}
// ── Modal helpers ─────────────────────────────────────────────────────────
function openModal(id)  { document.getElementById(id).classList.add('open'); }
function closeModal(id) { document.getElementById(id).classList.remove('open'); }
// Badge helper
function statusBadge(status) {
  const map = {
    approved: 'success', pre_approved: 'success', allowed_in: 'success',
    collected: 'success', resolved: 'success', confirmed: 'success',
    pending: 'warning', pending_payment: 'warning', in_progress: 'warning',
    denied: 'danger', rejected: 'danger', overstay: 'danger', cancelled: 'danger',
    sent: 'info', acknowledged: 'info',
    arrived: 'warning', left_at_gate: 'info'
  };
  const labels = {
    arrived: 'Pending',
    left_at_gate: 'Received at Gate',
    collected: 'Collected'
  };
  const label = labels[status] || status?.replace(/_/g,' ');
  return `<span class="badge badge-${map[status] || 'muted'}">${label}</span>`;
}
