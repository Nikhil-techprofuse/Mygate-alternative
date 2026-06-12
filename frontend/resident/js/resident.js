// ── Resident Portal JS ────────────────────────────────────────────────────

// ── Boot ──────────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => {
  if (Auth.isLoggedIn()) showFlatSelection();
});

let _flatSelectionProfile = null;

function showFlatSelection() {
  // Fetch profile and populate building/flat selectors.
  apiFetch('/auth/me').then(async res => {
    if (!res.ok) {
      toast('Failed to load profile', 'error');
      Auth.clear();
      location.reload();
      return;
    }
    _flatSelectionProfile = await res.json();

    document.getElementById('login-screen').style.display = 'none';
    document.getElementById('flat-selection-screen').style.display = 'flex';
    await loadFlatSelectionOptions();
  }).catch(e => {
    toast('Error: ' + e.message, 'error');
    Auth.clear();
    location.reload();
  });
}

let _residentFlatData = []; // [{id, name, flats:[{id, flat_number}]}]

async function loadFlatSelectionOptions() {
  const bSel = document.getElementById('flat-sel-building');
  const fSel = document.getElementById('flat-sel-flatno');
  const hint = document.getElementById('flat-sel-hint');

  const [bRes, rfRes] = await Promise.all([
    apiFetch('/admin/buildings'),
    apiFetch('/auth/resident-flats'),
  ]);
  const buildings = bRes.ok ? await bRes.json() : [];
  const residentFlats = rfRes.ok ? await rfRes.json() : [];

  // Build a map: building_id -> [flats with residents]
  const flatsByBuilding = {};
  residentFlats.forEach(b => { flatsByBuilding[b.id] = b.flats; });

  // Store for later use
  _residentFlatData = buildings.map(b => ({
    id: b.id, name: b.name,
    flats: flatsByBuilding[b.id] || []
  }));

  bSel.innerHTML = '<option value="">Select building</option>';
  _residentFlatData.forEach(b => {
    bSel.insertAdjacentHTML('beforeend', `<option value="${b.id}">${b.name}</option>`);
  });

  const currentBuildingId = _flatSelectionProfile?.flats?.building_id || '';
  const currentFlatId     = _flatSelectionProfile?.flat_id || '';
  if (currentBuildingId) {
    bSel.value = currentBuildingId;
    await _loadAndRenderFlatOptions(currentBuildingId, currentFlatId);
  } else {
    fSel.innerHTML = '<option value="">Select flat number</option>';
    hint.textContent = buildings.length ? 'Choose building first.' : 'No buildings found. Contact admin.';
  }
}

async function _loadAndRenderFlatOptions(buildingId, selectedFlatId = '') {
  const fSel = document.getElementById('flat-sel-flatno');
  const hint = document.getElementById('flat-sel-hint');
  if (!buildingId) {
    fSel.innerHTML = '<option value="">Select flat number</option>';
    hint.textContent = 'Choose building first, then flat number.';
    return;
  }
  const building = _residentFlatData.find(b => b.id === buildingId);
  const flats = building ? building.flats : [];
  fSel.innerHTML = '<option value="">Select flat number</option>';
  flats.forEach(fl => {
    fSel.insertAdjacentHTML('beforeend', `<option value="${fl.id}">${fl.flat_number}</option>`);
  });
  if (selectedFlatId) fSel.value = selectedFlatId;
  hint.textContent = flats.length ? `${flats.length} flat(s) available` : 'No registered flats in this building. Contact admin.';
}

function onFlatBuildingChange() {
  const buildingId = document.getElementById('flat-sel-building').value;
  _loadAndRenderFlatOptions(buildingId);
}

async function confirmFlatSelection() {
  const flatId = document.getElementById('flat-sel-flatno').value;
  if (!flatId) return toast('Please select a flat number', 'error');

  const saveRes = await apiFetch('/auth/select-flat', {
    method: 'POST',
    body: JSON.stringify({ flat_id: flatId }),
  });
  if (!saveRes.ok) {
    const e = await saveRes.json();
    return toast(e.error || 'Failed to set selected flat', 'error');
  }

  localStorage.setItem((window.MG_PORTAL || 'mg') + '_flat_id', flatId);
  document.getElementById('flat-selection-screen').style.display = 'none';
  document.getElementById('app-shell').style.display = 'block';
  loadDashboard();
  subscribeVisitorApprovals();
  subscribeDeliveryUpdates();
}

function showApp() {
  showFlatSelection();
}

function resetLogin() {
  document.getElementById('step-phone').style.display = 'block';
  document.getElementById('step-otp').style.display   = 'none';
}

function logout() {
  Auth.clear();
  location.reload();
}

// ── Auth ──────────────────────────────────────────────────────────────────
async function sendOtp() {
  const phone = document.getElementById('inp-phone').value.trim();
  if (!phone) return toast('Enter your phone number', 'error');
  const res = await fetch(API_BASE + '/auth/send-otp', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ phone }),
  });
  if (res.ok) {
    document.getElementById('step-phone').style.display = 'none';
    document.getElementById('step-otp').style.display   = 'block';
    document.getElementById('otp-phone-display').textContent = phone;
    toast('OTP sent!', 'success');
  } else {
    const e = await res.json();
    toast(e.error || 'Failed to send OTP', 'error');
  }
}

async function verifyOtp() {
  const phone = document.getElementById('inp-phone').value.trim();
  const token = document.getElementById('inp-otp').value.trim();
  if (!token || token.length !== 6) return toast('Enter 6-digit OTP', 'error');
  const res = await fetch(API_BASE + '/auth/verify-otp', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ phone, token }),
  });
  if (res.ok) {
    const data = await res.json();
    if (!['resident', 'tenant', 'super_admin', 'committee_member'].includes(data.role)) {
      return toast('Access denied — use the correct portal for your role', 'error');
    }
    Auth.save(data);
    showFlatSelection();
  } else {
    const e = await res.json();
    toast(e.error || 'Invalid OTP', 'error');
  }
}

// ── Dashboard ─────────────────────────────────────────────────────────────
let _myProfile = {};

// ── Flat helper ───────────────────────────────────────────────────────────
function getFlatId() {
  return Auth.userId ? localStorage.getItem((window.MG_PORTAL || 'mg') + '_flat_id') : null;
}

async function loadDashboard() {
  const [profRes, visRes, delRes] = await Promise.all([
    apiFetch('/auth/me'),
    apiFetch('/visitors/?limit=5'),
    apiFetch('/delivery/?status=arrived'),
  ]);
  _myProfile   = profRes.ok  ? await profRes.json()  : {};
  const visitors   = visRes.ok   ? await visRes.json()   : [];
  const deliveries = delRes.ok ? await delRes.json()   : [];

  const flatLabel = _myProfile.flats?.flat_number
    ? (_myProfile.flats.buildings?.name ? `${_myProfile.flats.buildings.name} – ${_myProfile.flats.flat_number}` : _myProfile.flats.flat_number)
    : '—';

  document.getElementById('user-name-display').textContent = _myProfile.full_name || 'Profile';
  if (_myProfile.kids_checkout_enabled !== undefined) {
    document.getElementById('kids-checkout-toggle').checked = _myProfile.kids_checkout_enabled;
  }

  const pendingDeliveries = deliveries.filter(d => d.status === 'arrived');
  const gateDeliveries = deliveries.filter(d => d.status === 'left_at_gate' && !d.parcel_otp_used);
  
  // Stats cards removed per user request

  const pending = visitors.filter(v => v.approval_status === 'pending');
  document.getElementById('pending-visitors').innerHTML = pending.length
    ? pending.map(v => visitorCard(v, true)).join('')
    : '<p style="color:var(--muted);font-size:.9rem;text-align:center;padding:12px">No pending visitors</p>';
  
  // Pending deliveries
  document.getElementById('pending-deliveries').innerHTML = pendingDeliveries.length
    ? pendingDeliveries.map(d => deliveryCard(d, true)).join('')
    : '<p style="color:var(--muted);font-size:.9rem;text-align:center;padding:12px">No pending deliveries</p>';
  
  // Left at gate deliveries with OTP
  document.getElementById('gate-deliveries').innerHTML = gateDeliveries.length
    ? gateDeliveries.map(d => deliveryOTPCard(d)).join('')
    : '<p style="color:var(--muted);font-size:.9rem;text-align:center;padding:12px">No deliveries left at gate</p>';
}

function openInviteModal() {
  const flat = _myProfile.flats;
  const label = flat?.flat_number
    ? (flat.buildings?.name ? `${flat.buildings.name} – ${flat.flat_number}` : flat.flat_number)
    : 'Your flat';
  document.getElementById('inv-flat-display').value = label;
  
  // Pre-fill valid_from with current LOCAL time, valid_until with +24 hours LOCAL time
  const now = new Date();
  const tomorrow = new Date(now.getTime() + 24*60*60*1000);
  
  // Format for datetime-local input (YYYY-MM-DDTHH:MM in local timezone)
  const formatLocal = (date) => {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');
    return `${year}-${month}-${day}T${hours}:${minutes}`;
  };
  
  document.getElementById('inv-from').value = formatLocal(now);
  document.getElementById('inv-until').value = formatLocal(tomorrow);
  
  openModal('modal-invite');
}

// ── Visitor approval (realtime) ───────────────────────────────────────────
function subscribeVisitorApprovals() {
  const flatId = getFlatId();
  if (!flatId) return;
  sb.channel('visitor-approvals')
    .on('postgres_changes', {
      event: 'INSERT',
      schema: 'public',
      table: 'visitor_logs',
      filter: `flat_id=eq.${flatId}`,
    }, payload => {
      const v = payload.new;
      if (v.approval_status === 'pending') {
        toast(`Visitor at gate: ${v.visitor_name}`, 'info');
        loadDashboard();
      }
    })
    .subscribe();
}

// ── Delivery updates (realtime) ───────────────────────────────────────────
function subscribeDeliveryUpdates() {
  const flatId = getFlatId();
  if (!flatId) return;
  sb.channel('delivery-updates')
    .on('postgres_changes', {
      event: 'INSERT',
      schema: 'public',
      table: 'deliveries',
      filter: `flat_id=eq.${flatId}`,
    }, payload => {
      const d = payload.new;
      if (d.status === 'arrived') {
        toast(`📦 Delivery arrived at gate!`, 'info');
        loadDashboard();
      }
    })
    .on('postgres_changes', {
      event: 'UPDATE',
      schema: 'public',
      table: 'deliveries',
      filter: `flat_id=eq.${flatId}`,
    }, payload => {
      loadDashboard();
    })
    .subscribe();
}

async function approveVisitor(logId, decision) {
  const res = await apiFetch(`/visitors/${logId}/approve`, {
    method: 'PATCH',
    body: JSON.stringify({ decision }),
  });
  if (res.ok) {
    toast(decision === 'approved' ? 'Visitor approved!' : 'Visitor denied', decision === 'approved' ? 'success' : 'error');
    loadDashboard();
  }
}

function visitorCard(v, withActions = false) {
  return `
    <div class="visitor-card">
      <img src="${v.visitor_photo_url || 'https://ui-avatars.com/api/?name=' + encodeURIComponent(v.visitor_name)}" alt="">
      <div class="visitor-info">
        <div class="visitor-name">${v.visitor_name}</div>
        <div class="visitor-meta">${v.visitor_type || ''} · ${timeAgo(v.entry_time)}</div>
        <div>${statusBadge(v.approval_status)}</div>
      </div>
      ${withActions && v.approval_status === 'pending' ? `
      <div class="visitor-actions">
        <button class="btn btn-success" style="padding:6px 12px" onclick="approveVisitor('${v.id}','approved')">✓</button>
        <button class="btn btn-danger"  style="padding:6px 12px" onclick="approveVisitor('${v.id}','denied')">✗</button>
      </div>` : ''}
    </div>`;
}

// ── Visitors list ─────────────────────────────────────────────────────────
async function loadVisitors() {
  showVisitorTab('invites');
}

function showVisitorTab(tab) {
  const invPanel  = document.getElementById('visitors-invites-panel');
  const histPanel = document.getElementById('visitors-history-panel');
  const invBtn    = document.getElementById('tab-invites-btn');
  const histBtn   = document.getElementById('tab-history-btn');
  if (tab === 'invites') {
    invPanel.style.display  = 'block';
    histPanel.style.display = 'none';
    invBtn.classList.add('btn-primary');  invBtn.classList.remove('btn-ghost');
    histBtn.classList.remove('btn-primary'); histBtn.classList.add('btn-ghost');
    loadInvites();
  } else {
    invPanel.style.display  = 'none';
    histPanel.style.display = 'block';
    histBtn.classList.add('btn-primary');  histBtn.classList.remove('btn-ghost');
    invBtn.classList.remove('btn-primary'); invBtn.classList.add('btn-ghost');
    loadVisitorHistory();
  }
}

async function loadInvites() {
  const res  = await apiFetch('/visitors/invites');
  const data = res.ok ? await res.json() : [];
  const now  = new Date();
  document.getElementById('visitors-invites-panel').innerHTML = data.length
    ? data.map(inv => {
        const active = new Date(inv.valid_until) > now && !inv.is_used;
        return `
        <div class="card" style="margin-bottom:12px">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <div>
              <strong>${inv.visitor_name}</strong>
              ${inv.is_recurring ? '<span class="badge badge-info" style="margin-left:6px">Recurring</span>' : ''}
              ${active ? '<span class="badge badge-success" style="margin-left:6px">Active</span>' : '<span class="badge" style="margin-left:6px;background:var(--muted)">Expired</span>'}
            </div>
            ${active ? `<button class="btn btn-danger" style="padding:4px 10px;font-size:.8rem" onclick="cancelInvite('${inv.id}')">Cancel</button>` : ''}
          </div>
          <div style="margin-top:10px;background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:12px;text-align:center">
            <div style="font-size:.75rem;color:var(--muted);margin-bottom:4px">OTP CODE</div>
            <div style="font-size:2rem;font-weight:800;letter-spacing:8px;color:var(--primary)">${inv.otp_code}</div>
            <button class="btn btn-ghost" style="margin-top:6px;padding:4px 12px;font-size:.8rem" onclick="navigator.clipboard.writeText('${inv.otp_code}').then(()=>toast('OTP copied!','success'))">📋 Copy</button>
          </div>
          <div style="margin-top:8px;font-size:.8rem;color:var(--muted)">
            Valid: ${fmtDate(inv.valid_from)} → ${fmtDate(inv.valid_until)}
            ${inv.visitor_phone ? ' · ' + inv.visitor_phone : ''}
          </div>
        </div>`;
      }).join('')
    : '<p style="color:var(--muted);text-align:center;padding:20px">No active invites — click <strong>+ Invite Guest</strong> to create one</p>';
}

async function cancelInvite(id) {
  if (!confirm('Cancel this invite?')) return;
  const res = await apiFetch(`/visitors/invites/${id}`, { method: 'DELETE' });
  if (res.ok) { toast('Invite cancelled', 'success'); loadInvites(); }
  else toast('Failed to cancel', 'error');
}

async function loadVisitorHistory() {
  const res  = await apiFetch('/visitors/');
  const data = res.ok ? await res.json() : [];
  document.getElementById('visitors-history-panel').innerHTML = data.length
    ? data.map(v => visitorCard(v)).join('')
    : '<p style="color:var(--muted);text-align:center;padding:20px">No visitor history</p>';
}

async function createInvite() {
  const body = {
    visitor_name:  document.getElementById('inv-name').value.trim(),
    visitor_phone: document.getElementById('inv-phone').value.trim(),
    valid_from:    document.getElementById('inv-from').value,
    valid_until:   document.getElementById('inv-until').value,
    is_recurring:  document.getElementById('inv-recurring').checked,
  };
  if (!body.visitor_name || !body.valid_from || !body.valid_until)
    return toast('Fill all required fields', 'error');
  
  // Convert local datetime strings to UTC ISO format for backend
  body.valid_from = new Date(body.valid_from).toISOString();
  body.valid_until = new Date(body.valid_until).toISOString();
  
  const res = await apiFetch('/visitors/invite', { method: 'POST', body: JSON.stringify(body) });
  if (res.ok) {
    const d = await res.json();
    closeModal('modal-invite');
    // Clear form
    ['inv-name','inv-phone','inv-from','inv-until'].forEach(id => document.getElementById(id).value = '');
    document.getElementById('inv-recurring').checked = false;
    toast(`Invite created! OTP: ${d.otp_code}`, 'success');
    loadInvites();
  } else {
    const e = await res.json();
    toast(e.error || 'Failed', 'error');
  }
}

// ── Delivery approval functions ──────────────────────────────────────────
let _currentDeliveryId = null;

async function approveDelivery(deliveryId, decision) {
  if (decision === 'leave_at_gate') {
    // Show OTP input modal
    _currentDeliveryId = deliveryId;
    document.getElementById('delivery-otp-input').value = '';
    openModal('modal-delivery-otp');
    return;
  }
  
  const res = await apiFetch(`/delivery/${deliveryId}/decide`, {
    method: 'PATCH',
    body: JSON.stringify({ decision }),
  });
  
  if (res.ok) {
    if (decision === 'accept') {
      toast('Delivery approved! Guard will allow entry.', 'success');
    } else if (decision === 'reject') {
      toast('Delivery rejected and returned.', 'error');
    }
    loadDashboard();
  } else {
    const err = await res.json();
    toast(err.error || 'Failed to process', 'error');
  }
}

async function confirmLeaveAtGate() {
  const otp = document.getElementById('delivery-otp-input').value.trim();
  
  if (!otp) {
    return toast('Please enter a collection code', 'error');
  }
  
  const res = await apiFetch(`/delivery/${_currentDeliveryId}/decide`, {
    method: 'PATCH',
    body: JSON.stringify({ decision: 'leave_at_gate', otp: otp }),
  });
  
  if (res.ok) {
    closeModal('modal-delivery-otp');
    toast(`Left at gate! Code: ${otp}`, 'success');
    loadDashboard();
  } else {
    const err = await res.json();
    toast(err.error || 'Failed to process', 'error');
  }
}

function deliveryCard(d, withActions = false) {
  const company = d.delivery_platforms?.name || 'Delivery';
  const type = d.delivery_type || 'standard';
  const time = timeAgo(d.entry_time);
  
  return `
    <div class="visitor-card" style="border-left:4px solid var(--warning)">
      <div style="font-size:2rem;margin-right:12px">📦</div>
      <div class="visitor-info" style="flex:1">
        <div class="visitor-name">${company}</div>
        <div class="visitor-meta">${type}${d.tracking_id ? ' · ' + d.tracking_id : ''} · ${time}</div>
        <div>${statusBadge(d.status)}</div>
      </div>
      ${withActions && d.status === 'arrived' ? `
      <div class="visitor-actions" style="flex-direction:column;gap:4px;min-width:140px">
        <button class="btn btn-success" style="padding:6px 12px;font-size:.85rem;width:100%" onclick="approveDelivery('${d.id}','accept')">✓ Accept</button>
        <button class="btn btn-warning" style="padding:6px 12px;font-size:.85rem;width:100%" onclick="approveDelivery('${d.id}','leave_at_gate')">📍 Leave at Gate</button>
        <button class="btn btn-danger" style="padding:6px 12px;font-size:.85rem;width:100%" onclick="approveDelivery('${d.id}','reject')">✗ Reject</button>
      </div>` : ''}
    </div>`;
}

function deliveryOTPCard(d) {
  const company = d.delivery_platforms?.name || 'Delivery';
  
  return `
    <div class="card" style="margin-bottom:12px;border-left:4px solid var(--primary)">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
        <div>
          <strong style="font-size:1.05rem">${company}</strong>
          <div style="font-size:.8rem;color:var(--muted);margin-top:2px">${d.tracking_id || 'No tracking ID'}</div>
        </div>
        <span class="badge badge-warning">Left at Gate</span>
      </div>
      <div style="background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:12px;text-align:center">
        <div style="font-size:.75rem;color:var(--muted);margin-bottom:4px">COLLECTION CODE</div>
        <div style="font-size:2rem;font-weight:800;letter-spacing:6px;color:var(--primary)">${d.parcel_otp}</div>
        <button class="btn btn-ghost" style="margin-top:6px;padding:4px 12px;font-size:.8rem" onclick="navigator.clipboard.writeText('${d.parcel_otp}').then(()=>toast('Code copied!','success'))">📋 Copy Code</button>
      </div>
      <div style="margin-top:8px;font-size:.8rem;color:var(--muted)">
        Left at: ${fmtDate(d.exit_time)} · Show this code to guard for collection
      </div>
    </div>`;
}

// ── Deliveries ────────────────────────────────────────────────────────────
async function loadDeliveries() {
  const res = await apiFetch('/delivery/');
  if (!res.ok) return;
  const data = await res.json();
  document.getElementById('delivery-list').innerHTML = data.length
    ? `<div class="table-wrap"><table>
        <thead><tr><th>Company</th><th>Type</th><th>Status</th><th>Time</th><th>OTP</th></tr></thead>
        <tbody>${data.map(d => `<tr>
          <td><strong>${d.delivery_platforms?.name || '—'}</strong><br><small style="color:var(--muted)">${d.tracking_id || ''}</small></td>
          <td>${d.delivery_type}</td>
          <td>${statusBadge(d.status)}</td>
          <td>${fmtDate(d.entry_time)}</td>
          <td>${d.parcel_otp && !d.parcel_otp_used ? `<strong style="color:var(--primary);font-size:1.1rem;letter-spacing:2px">${d.parcel_otp}</strong>` : '—'}</td>
        </tr>`).join('')}</tbody>
      </table></div>`
    : '<p style="color:var(--muted);text-align:center;padding:20px">No deliveries</p>';
}

async function allowDelivery(id) {
  const res = await apiFetch(`/delivery/${id}/allow`, { method: 'PATCH', body: '{}' });
  if (res.ok) { toast('Delivery allowed!', 'success'); loadDeliveries(); }
}

// ── Helpers ───────────────────────────────────────────────────────────────
async function loadHelpers() {
  const res = await apiFetch('/domestic-help/');
  if (!res.ok) return;
  const data = await res.json();
  document.getElementById('helpers-list').innerHTML = data.length
    ? data.map(h => `
      <div class="card" style="margin-bottom:12px;display:flex;align-items:center;gap:12px">
        <img src="${h.photo_url || 'https://ui-avatars.com/api/?name='+encodeURIComponent(h.name)}" style="width:48px;height:48px;border-radius:50%;object-fit:cover">
        <div style="flex:1">
          <div style="font-weight:600">${h.name} <span style="font-size:.75rem;color:var(--muted)">${h.helper_type}</span></div>
          <div style="font-size:.8rem;color:var(--muted)">Passcode: <strong>${h.passcode}</strong> · ⭐ ${h.avg_rating || 0}</div>
          ${h.is_blacklisted ? '<span class="badge badge-danger">Blacklisted ⚠️</span>' : ''}
        </div>
      </div>`).join('')
    : '<p style="color:var(--muted);text-align:center;padding:20px">No helpers added yet</p>';
}

async function addHelper() {
  const body = {
    name:        document.getElementById('h-name').value.trim(),
    phone:       document.getElementById('h-phone').value.trim(),
    helper_type: document.getElementById('h-type').value,
  };
  if (!body.name) return toast('Name is required', 'error');
  const res = await apiFetch('/domestic-help/', { method: 'POST', body: JSON.stringify(body) });
  if (res.ok) {
    const d = await res.json();
    closeModal('modal-add-helper');
    toast(`Helper added! Passcode: ${d.passcode}`, 'success');
    loadHelpers();
  } else {
    const e = await res.json();
    toast(e.error || 'Failed', 'error');
  }
}

// ── SOS ───────────────────────────────────────────────────────────────────
function triggerSOS() { openModal('modal-sos-confirm'); }

async function confirmSOS() {
  closeModal('modal-sos-confirm');
  const res = await apiFetch('/security-alerts/sos', { method: 'POST', body: '{}' });
  if (res.ok) toast('🚨 Alert sent! Guards notified.', 'error');
  else toast('Failed to send alert', 'error');
}

// ── Community ─────────────────────────────────────────────────────────────
async function loadNotices() {
  const res = await apiFetch('/community/notices');
  const data = res.ok ? await res.json() : [];
  document.getElementById('community-content').innerHTML = data.length
    ? data.map(n => `
      <div class="card" style="margin-bottom:12px">
        <div style="display:flex;justify-content:space-between">
          <strong>${n.title}</strong>
          ${n.is_pinned ? '<span class="badge badge-info">📌 Pinned</span>' : ''}
        </div>
        <p style="margin-top:8px;color:var(--muted);font-size:.875rem">${n.body || ''}</p>
        <div style="margin-top:10px;font-size:.8rem;color:var(--muted)">${fmtDate(n.created_at)}</div>
        <button class="btn btn-ghost" style="margin-top:8px;padding:4px 12px;font-size:.8rem" onclick="ackNotice('${n.id}')">✓ Acknowledge</button>
      </div>`).join('')
    : '<p style="color:var(--muted);text-align:center;padding:20px">No notices</p>';
}

async function ackNotice(id) {
  await apiFetch(`/community/notices/${id}/acknowledge`, { method: 'POST', body: '{}' });
  toast('Acknowledged', 'success');
}

async function loadPolls() {
  const res = await apiFetch('/community/polls');
  const data = res.ok ? await res.json() : [];
  document.getElementById('community-content').innerHTML = data.length
    ? data.map(p => `
      <div class="card" style="margin-bottom:12px">
        <strong>${p.question}</strong>
        ${(p.poll_options || []).map(o => `
          <div style="margin-top:8px"><button class="btn btn-ghost btn-full" onclick="votePoll('${p.id}','${o.id}')">${o.option_text}</button></div>
        `).join('')}
      </div>`).join('')
    : '<p style="color:var(--muted);text-align:center;padding:20px">No polls</p>';
}

async function votePoll(pollId, optionId) {
  const res = await apiFetch(`/community/polls/${pollId}/vote`, { method: 'POST', body: JSON.stringify({ option_id: optionId }) });
  if (res.ok) toast('Vote recorded!', 'success');
  else { const e = await res.json(); toast(e.error || 'Failed', 'error'); }
}

async function loadEvents() {
  const res = await apiFetch('/community/events');
  const data = res.ok ? await res.json() : [];
  document.getElementById('community-content').innerHTML = data.length
    ? data.map(e => `
      <div class="card" style="margin-bottom:12px">
        <strong>${e.title}</strong>
        <div style="font-size:.85rem;color:var(--muted);margin-top:4px">${e.venue || ''} · ${fmtDate(e.event_date)}</div>
        <button class="btn btn-primary" style="margin-top:10px;padding:6px 16px;font-size:.85rem" onclick="rsvpEvent('${e.id}','going')">✓ Going</button>
      </div>`).join('')
    : '<p style="color:var(--muted);text-align:center;padding:20px">No events</p>';
}

async function rsvpEvent(id, status) {
  await apiFetch(`/community/events/${id}/rsvp`, { method: 'POST', body: JSON.stringify({ status }) });
  toast('RSVP saved!', 'success');
}

async function loadForum() {
  const res = await apiFetch('/community/forum');
  const data = res.ok ? await res.json() : [];
  document.getElementById('community-content').innerHTML = data.length
    ? data.map(t => `
      <div class="card" style="margin-bottom:12px">
        <strong>${t.title}</strong>
        <div style="font-size:.8rem;color:var(--muted);margin-top:4px">by ${t.user_profiles?.full_name || 'Resident'} · ${timeAgo(t.created_at)}</div>
        <p style="margin-top:8px;font-size:.875rem">${t.body || ''}</p>
      </div>`).join('')
    : '<p style="color:var(--muted);text-align:center;padding:20px">No forum threads</p>';
}

// ── Profile ───────────────────────────────────────────────────────────────
async function saveProfile() {
  const body = {
    full_name: document.getElementById('profile-name').value.trim(),
    email:     document.getElementById('profile-email').value.trim(),
  };
  const res = await apiFetch('/auth/me', { method: 'PATCH', body: JSON.stringify(body) });
  if (res.ok) {
    _myProfile = { ..._myProfile, ...body };
    toast('Profile saved!', 'success');
  } else toast('Failed to save', 'error');
}

// Pre-fill profile page when navigated to
document.querySelectorAll('[data-page="page-profile"]')?.forEach(el => el.addEventListener('click', () => {
  if (_myProfile.full_name) document.getElementById('profile-name').value = _myProfile.full_name || '';
  if (_myProfile.email)     document.getElementById('profile-email').value  = _myProfile.email || '';
}));

async function toggleKidsCheckout(enabled) {
  await apiFetch('/kids-checkout/toggle', { method: 'POST', body: JSON.stringify({ enabled }) });
  toast(enabled ? 'Kids Checkout enabled' : 'Kids Checkout disabled', 'success');
}

// ── Vehicles ──────────────────────────────────────────────────────────────
let _flatData = null;

async function loadMyVehicles() {
  const [vRes, profRes] = await Promise.all([
    apiFetch('/vehicles/'),
    apiFetch('/auth/me'),
  ]);
  const vehicles = vRes.ok   ? await vRes.json()   : [];
  const profile  = profRes.ok ? await profRes.json() : {};
  _flatData = profile;

  const cars   = vehicles.filter(v => v.vehicle_type === 'car'    && v.status === 'active');
  const bikes  = vehicles.filter(v => ['bike','scooter'].includes(v.vehicle_type) && v.status === 'active');
  const maxCar = profile.max_cars        || '?';
  const maxTw  = profile.max_two_wheelers || '?';

  document.getElementById('vehicle-slot-bar').innerHTML = `
    <div style="display:flex;gap:12px;flex-wrap:wrap">
      <div class="card" style="flex:1;min-width:130px;text-align:center;padding:12px">
        <div style="font-size:1.6rem;font-weight:800;color:var(--primary)">${cars.length}<span style="font-size:1rem;color:var(--muted)"> / ${maxCar}</span></div>
        <div style="font-size:.8rem;color:var(--muted);margin-top:2px">Car Slots Used</div>
      </div>
      <div class="card" style="flex:1;min-width:130px;text-align:center;padding:12px">
        <div style="font-size:1.6rem;font-weight:800;color:var(--primary)">${bikes.length}<span style="font-size:1rem;color:var(--muted)"> / ${maxTw}</span></div>
        <div style="font-size:.8rem;color:var(--muted);margin-top:2px">Two-Wheeler Slots</div>
      </div>
    </div>`;

  document.getElementById('vehicles-list').innerHTML = vehicles.length
    ? vehicles.map(v => `
      <div class="card" style="margin-bottom:12px;display:flex;align-items:center;gap:12px">
        <div style="font-size:2rem">${v.vehicle_type === 'car' ? '🚗' : '🛵'}</div>
        <div style="flex:1">
          <div style="font-weight:700;letter-spacing:2px;font-size:1.05rem">${v.number_plate}</div>
          <div style="font-size:.8rem;color:var(--muted)">${v.vehicle_type} · ${v.parking_slots?.slot_name ? '🅿️ ' + v.parking_slots.slot_name : 'No slot assigned'}</div>
        </div>
        <div style="display:flex;flex-direction:column;gap:6px">
          ${statusBadge(v.status)}
          ${v.status === 'active' ? `<button class="btn btn-ghost" style="padding:4px 10px;font-size:.75rem" onclick="markVehicleSold('${v.id}')">Mark Sold</button>` : ''}
        </div>
      </div>`).join('')
    : '<p style="color:var(--muted);text-align:center;padding:20px">No vehicles registered yet</p>';
}

async function addVehicle() {
  const plate = document.getElementById('v-plate').value.trim().toUpperCase();
  const type  = document.getElementById('v-type').value;
  if (!plate) return toast('Number plate required', 'error');
  const body = { number_plate: plate, vehicle_type: type };
  const res = await apiFetch('/vehicles/', { method: 'POST', body: JSON.stringify(body) });
  if (res.ok) {
    closeModal('modal-add-vehicle');
    document.getElementById('v-plate').value = '';
    toast('Vehicle registered!', 'success');
    loadMyVehicles();
  } else {
    const e = await res.json();
    toast(e.error || 'Failed', 'error');
  }
}

async function markVehicleSold(vehicleId) {
  if (!confirm('Mark this vehicle as sold/transferred? It will be removed from your slot count.')) return;
  const res = await apiFetch(`/vehicles/${vehicleId}`, { method: 'PATCH', body: JSON.stringify({ status: 'sold' }) });
  if (res.ok) { toast('Vehicle status updated', 'success'); loadMyVehicles(); }
  else toast('Failed', 'error');
}

// ── Billing ───────────────────────────────────────────────────────────────
async function loadBilling() {
  const res = await apiFetch('/billing/invoices');
  const data = res.ok ? await res.json() : [];
  document.getElementById('invoices-list').innerHTML = data.length
    ? `<div class="table-wrap"><table>
        <thead><tr><th>Invoice #</th><th>Amount</th><th>Due Date</th><th>Status</th></tr></thead>
        <tbody>${data.map(i => `<tr>
          <td>${i.invoice_number || '—'}</td>
          <td>₹${i.total_amount}</td>
          <td>${i.due_date || '—'}</td>
          <td>${statusBadge(i.status)}</td>
        </tr>`).join('')}</tbody>
      </table></div>`
    : '<p style="color:var(--muted);text-align:center;padding:20px">No invoices</p>';
}

// Trigger billing load when page nav is clicked
document.querySelectorAll('[data-page="page-billing"]')?.forEach(el => el.addEventListener('click', loadBilling));
