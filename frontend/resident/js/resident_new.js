
// ── Resident Portal JS ────────────────────────────────────────────────────

// ── Boot ──────────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', async () => {
  try {
    if (Auth.isLoggedIn()) {
      await showApp();
    }
  } catch (err) {
    console.error('Boot error:', err);
    // Display error message and reset button
    const errDiv = document.createElement('div');
    errDiv.style.position = 'fixed';
    errDiv.style.inset = '0';
    errDiv.style.background = 'rgba(10, 15, 30, 0.95)';
    errDiv.style.color = '#ff6b6b';
    errDiv.style.padding = '40px';
    errDiv.style.zIndex = '99999';
    errDiv.style.display = 'flex';
    errDiv.style.flexDirection = 'column';
    errDiv.style.alignItems = 'center';
    errDiv.style.justifyContent = 'center';
    errDiv.style.textAlign = 'center';
    errDiv.style.fontFamily = 'sans-serif';
    errDiv.innerHTML = `
      <div style="font-size:3rem;margin-bottom:20px">⚠️</div>
      <h2 style="margin-bottom:10px;color:white">Portal Loading Error</h2>
      <p style="max-width:500px;margin-bottom:30px;color:#ccc">${err.message || err}</p>
      <button class="btn btn-primary" onclick="Auth.clear(); location.reload();" style="padding:12px 24px;border-radius:8px">Reset Session & Login</button>
    `;
    document.body.appendChild(errDiv);
  }
});

async function showApp() {
  document.getElementById('login-screen').style.display = 'none';
  document.getElementById('app-shell').style.display = 'block';
  await loadDashboard();
  subscribeVisitorApprovals();
  subscribeDeliveries();
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
    showApp();
  } else {
    const e = await res.json();
    toast(e.error || 'Invalid OTP', 'error');
  }
}

// ── Dashboard ─────────────────────────────────────────────────────────────
let _myProfile = {};

async function loadDashboard() {
  const [profRes, visRes, delRes] = await Promise.all([
    apiFetch('/auth/me'),
    apiFetch('/visitors/?limit=5'),
    apiFetch('/delivery/?status=arrived'),
  ]);
  _myProfile   = profRes.ok  ? await profRes.json()  : {};
  
  // Self-heal/sync local storage keys if they changed in the database
  if (_myProfile.flat_id && _myProfile.flat_id !== Auth.flatId) {
    localStorage.setItem('res_flat_id', _myProfile.flat_id);
  }
  if (_myProfile.society_id && _myProfile.society_id !== Auth.societyId) {
    localStorage.setItem('res_society_id', _myProfile.society_id);
  }

  const visitors   = visRes.ok   ? await visRes.json()   : [];
  const deliveries = delRes.ok ? await delRes.json()   : [];

  const flatLabel = _myProfile.flats?.flat_number
    ? (_myProfile.flats.buildings?.name ? `${_myProfile.flats.buildings.name} – ${_myProfile.flats.flat_number}` : _myProfile.flats.flat_number)
    : '—';

  document.getElementById('user-name-display').textContent = _myProfile.full_name || 'Profile';
  if (_myProfile.kids_checkout_enabled !== undefined) {
    document.getElementById('kids-checkout-toggle').checked = _myProfile.kids_checkout_enabled;
  }

  document.getElementById('dashboard-stats').innerHTML = `
    <div class="stat-card" onclick="showPage('page-visitors');loadVisitors()" style="cursor:pointer"><div class="stat-val">${visitors.filter(v=>v.approval_status==='pending').length}</div><div class="stat-lbl">Pending</div></div>
    <div class="stat-card" onclick="showPage('page-delivery');loadDeliveries()" style="cursor:pointer"><div class="stat-val">${deliveries.length}</div><div class="stat-lbl">Deliveries</div></div>
  `;

  const pending = visitors.filter(v => v.approval_status === 'pending');
  document.getElementById('pending-visitors').innerHTML = pending.length
    ? pending.map(v => visitorCard(v, true)).join('')
    : '<p style="color:var(--muted);font-size:.9rem;text-align:center;padding:12px">No pending approvals</p>';
}

function openInviteModal() {
  const flat = _myProfile.flats;
  const label = flat?.flat_number
    ? (flat.buildings?.name ? `${flat.buildings.name} – ${flat.flat_number}` : flat.flat_number)
    : 'Your flat';
  document.getElementById('inv-flat-display').value = label;
  openModal('modal-invite');
}

// ── Visitor approval (realtime) ───────────────────────────────────────────
function subscribeVisitorApprovals() {
  const flatId = Auth.flatId;
  if (!flatId) {
    console.warn('Realtime subscription skipped: No flat ID found in session');
    return;
  }
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

// ── Deliveries realtime sync ──────────────────────────────────────────────
function subscribeDeliveries() {
  const flatId = Auth.flatId;
  if (!flatId) return;
  sb.channel('deliveries-changes')
    .on('postgres_changes', {
      event: '*',
      schema: 'public',
      table: 'deliveries',
      filter: `flat_id=eq.${flatId}`,
    }, payload => {
      const d = payload.new;
      toast(`Delivery updated: ${d.status}`, 'info');
      loadDashboard();
      // If we are currently on the deliveries page, reload the list
      const delPage = document.getElementById('page-delivery');
      if (delPage && delPage.classList.contains('active')) {
        loadDeliveries();
      }
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

// ── Deliveries ────────────────────────────────────────────────────────────
async function loadDeliveries() {
  const res = await apiFetch('/delivery/');
  if (!res.ok) return;
  const data = await res.json();
  document.getElementById('delivery-list').innerHTML = data.length
    ? `<div class="table-wrap"><table>
        <thead><tr><th>Company</th><th>Type</th><th>Details / OTP</th><th>Status</th><th>Time</th><th>Action</th></tr></thead>
        <tbody>${data.map(d => `<tr>
          <td><strong>${d.delivery_platforms?.name || '—'}</strong></td>
          <td>${d.delivery_type}</td>
          <td>
            ${d.tracking_id ? `<div>Tracking: <code>${d.tracking_id}</code></div>` : ''}
            ${d.parcel_otp && !d.parcel_otp_used ? `
              <div style="margin-top:4px;color:var(--warning);font-weight:700">🔑 OTP: ${d.parcel_otp}</div>
              <div style="font-size:0.75rem;color:var(--muted)">Delivery ID: <code style="user-select:all">${d.id}</code></div>
            ` : ''}
          </td>
          <td>${statusBadge(d.status)}</td>
          <td>${fmtDate(d.entry_time)}</td>
          <td>
            ${d.status === 'arrived' ? `<button class="btn btn-success" style="padding:4px 10px" onclick="allowDelivery('${d.id}')">Allow</button>` : ''}
          </td>
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
