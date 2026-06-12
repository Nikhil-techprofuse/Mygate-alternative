// ── Guard Portal JS ───────────────────────────────────────────────────────

window.addEventListener('DOMContentLoaded', () => {
  if (Auth.isLoggedIn()) showApp();
});

function showApp() {
  document.getElementById('login-screen').style.display = 'none';
  document.getElementById('app-shell').style.display    = 'block';
  loadGuardDashboard();
  subscribeAlerts();
  subscribeVisitorQueue();
}

function resetLogin() {
  document.getElementById('step-phone').style.display = 'block';
  document.getElementById('step-otp').style.display   = 'none';
}

// ── Auth ──────────────────────────────────────────────────────────────────
async function sendOtp() {
  const phone = document.getElementById('inp-phone').value.trim();
  if (!phone) return toast('Enter phone', 'error');
  const res = await fetch(API_BASE + '/auth/send-otp', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ phone }),
  });
  if (res.ok) {
    document.getElementById('step-phone').style.display = 'none';
    document.getElementById('step-otp').style.display   = 'block';
    document.getElementById('otp-phone-display').textContent = phone;
    toast('OTP sent!', 'success');
  } else toast('Failed to send OTP', 'error');
}

async function verifyOtp() {
  const phone = document.getElementById('inp-phone').value.trim();
  const token = document.getElementById('inp-otp').value.trim();
  const res = await fetch(API_BASE + '/auth/verify-otp', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ phone, token }),
  });
  const data = await res.json();
  if (res.ok) {
    if (!['guard', 'super_admin'].includes(data.role)) {
      return toast('Access denied — this portal is for Security Guards only', 'error');
    }
    Auth.save(data);
    showApp();
  } else toast(data.error || 'Invalid OTP', 'error');
}

// ── Dashboard ─────────────────────────────────────────────────────────────
async function loadGuardDashboard() {
  const [queueRes, alertRes, visitorsRes] = await Promise.all([
    apiFetch('/visitors/queue'),
    apiFetch('/security-alerts/?status=sent'),
    apiFetch('/visitors/'),
  ]);
  const queue  = queueRes.ok  ? await queueRes.json()  : [];
  const alerts = alertRes.ok  ? await alertRes.json()  : [];
  const visitors = visitorsRes.ok ? await visitorsRes.json() : [];

  document.getElementById('guard-stats').innerHTML = `
    <div class="stat-card" style="background:var(--card-bg)"><div class="stat-val" style="color:var(--primary)">${queue.length}</div><div class="stat-lbl" style="color:var(--muted)">In Queue</div></div>
    <div class="stat-card" style="background:var(--card-bg)"><div class="stat-val" style="color:var(--danger)">${alerts.length}</div><div class="stat-lbl" style="color:var(--muted)">Alerts</div></div>
  `;

  // Active SOS alerts
  document.getElementById('active-alerts').innerHTML = alerts.map(a => `
    <div class="alert-banner" onclick="acknowledgeAlert('${a.id}')">
      🚨 SOS — ${a.flats?.flat_number || 'Unknown flat'} · Tap to acknowledge
    </div>`).join('');

  // Pending approvals
  document.getElementById('visitor-queue').innerHTML = queue.length
    ? queue.map(v => `
      <div style="display:flex;align-items:center;gap:12px;padding:12px 0;border-bottom:1px solid var(--border)">
        <div style="flex:1">
          <div style="font-weight:600">${v.visitor_name}</div>
          <div style="font-size:.8rem;color:var(--muted)">${v.visitor_type} · Flat ${v.flats?.flat_number || '?'} · ${timeAgo(v.entry_time)}</div>
        </div>
        <span style="padding:5px 12px;font-size:.8rem;background:var(--card-bg);color:var(--warning);border:1px solid var(--warning);border-radius:4px">⏳ Pending</span>
      </div>`).join('')
    : '<p style="color:var(--muted);text-align:center;padding:12px">No pending approvals</p>';

  // Active visitors (approved, not exited yet)
  const activeVisitors = visitors.filter(v => v.approval_status === 'approved' && !v.exit_time);
  document.getElementById('active-visitors').innerHTML = activeVisitors.length
    ? activeVisitors.map(v => `
      <div style="display:flex;align-items:center;gap:12px;padding:12px 0;border-bottom:1px solid var(--border)">
        <div style="flex:1">
          <div style="font-weight:600">${v.visitor_name}</div>
          <div style="font-size:.8rem;color:var(--muted)">${v.visitor_type} · Flat ${v.flats?.flat_number || '?'} · ${timeAgo(v.entry_time)}</div>
        </div>
        <button class="btn btn-success" style="padding:5px 12px;font-size:.8rem" onclick="logExitGuard('${v.id}')">Exit</button>
      </div>`).join('')
    : '<p style="color:var(--muted);text-align:center;padding:12px">No active visitors</p>';

  // Recent visitor entries (only approved ones)
  const recentApproved = visitors.filter(v => v.approval_status === 'approved');
  document.getElementById('recent-visitors').innerHTML = recentApproved.length
    ? recentApproved.slice(0, 10).map(v => `
      <div style="padding:10px 0;border-bottom:1px solid var(--border)">
        <div style="font-weight:600;color:var(--text)">${v.visitor_name}</div>
        <div style="font-size:.85rem;color:var(--muted);margin-top:4px">
          📍 Flat ${v.flats?.flat_number || '?'} ${v.visitor_phone ? `· 📱 ${v.visitor_phone}` : ''}
        </div>
        <div style="font-size:.8rem;color:var(--muted);margin-top:2px">
          ⏱ Entry: ${formatDateTime(v.entry_time)}${v.exit_time ? ` · Exit: ${formatDateTime(v.exit_time)}` : ' · <span style="color:var(--warning)">Still inside</span>'}
        </div>
      </div>`).join('')
    : '<p style="color:var(--muted);text-align:center;padding:12px">No visitor entries today</p>';

  // Recent vehicle entries
  loadVehicleEntries();
}

// ── Realtime subscriptions ────────────────────────────────────────────────
function subscribeAlerts() {
  sb.channel('guard-alerts')
    .on('postgres_changes', {
      event: 'INSERT', schema: 'public', table: 'security_alerts',
    }, payload => {
      toast(`🚨 SOS from Flat ${payload.new.flat_id}`, 'error');
      loadGuardDashboard();
    })
    .subscribe();
}

function subscribeVisitorQueue() {
  sb.channel('guard-queue')
    .on('postgres_changes', {
      event: 'INSERT', schema: 'public', table: 'visitor_logs',
    }, () => loadGuardDashboard())
    .on('postgres_changes', {
      event: 'UPDATE', schema: 'public', table: 'visitor_logs',
    }, () => loadGuardDashboard())
    .subscribe();
}

// ── Alert acknowledge ─────────────────────────────────────────────────────
async function acknowledgeAlert(id) {
  const res = await apiFetch(`/security-alerts/${id}/acknowledge`, { method: 'PATCH', body: '{}' });
  if (res.ok) { toast('Acknowledged — on my way!', 'success'); loadGuardDashboard(); }
}

// ── Visitor OTP verify ────────────────────────────────────────────────────
async function verifyVisitorOtp() {
  const otp = document.getElementById('otp-scan-input').value.trim();
  if (!otp || otp.length !== 6) return toast('Enter 6-digit OTP', 'error');
  const res = await apiFetch('/visitors/verify-otp', {
    method: 'POST', body: JSON.stringify({ otp_code: otp }),
  });
  const data = await res.json();
  if (res.ok) {
    document.getElementById('otp-result').innerHTML = `
      <div class="card" style="background:var(--card-bg);border-color:var(--primary);color:var(--text)">
        ✅ <strong>${data.visitor_name}</strong> — Pre-approved for Flat ${data.flat?.flat_number || '?'}
      </div>`;
    document.getElementById('otp-scan-input').value = '';
  } else {
    document.getElementById('otp-result').innerHTML = `<div class="card" style="background:var(--card-bg);border-color:var(--danger);color:var(--text)">❌ ${data.error}</div>`;
  }
}

// ── Walk-in ───────────────────────────────────────────────────────────────
let flatsCache = [];

async function loadFlatsList() {
  if (flatsCache.length) return;
  const res = await apiFetch('/auth/resident-flats');
  if (res.ok) {
    const buildings = await res.json();
    // Flatten occupied flats from grouped structure
    flatsCache = [];
    buildings.forEach(b => {
      b.flats.forEach(f => {
        flatsCache.push({
          id: f.id,
          flat_number: f.flat_number,
          building_name: b.name
        });
      });
    });
    
    const sel = document.getElementById('walkin-flat');
    flatsCache.forEach(f => {
      const o = document.createElement('option');
      o.value = f.id;
      o.textContent = `${f.building_name} - ${f.flat_number}`;
      sel.appendChild(o);
    });
    // Kids checkout flat list
    const kSel = document.getElementById('kids-flat');
    if (kSel) flatsCache.forEach(f => {
      const o = document.createElement('option');
      o.value = f.id;
      o.textContent = `${f.building_name} - ${f.flat_number}`;
      kSel.appendChild(o);
    });
  }
}

async function logWalkin() {
  const body = {
    visitor_name: document.getElementById('walkin-name').value.trim(),
    visitor_phone: document.getElementById('walkin-phone').value.trim(),
    flat_id: document.getElementById('walkin-flat').value,
    visitor_type: document.getElementById('walkin-type').value,
  };
  if (!body.visitor_name || !body.flat_id) return toast('Name and flat required', 'error');
  const res = await apiFetch('/visitors/walkin', { method: 'POST', body: JSON.stringify(body) });
  if (res.ok) {
    toast('Approval request sent to resident', 'success');
    document.getElementById('walkin-name').value = '';
    document.getElementById('walkin-phone').value = '';
    document.getElementById('walkin-flat').value = '';
  } else {
    const e = await res.json();
    toast(e.error || 'Failed', 'error');
  }
}

async function logExitGuard(logId) {
  await apiFetch(`/visitors/${logId}/exit`, { method: 'PATCH', body: '{}' });
  toast('Exit logged', 'success');
  loadGuardDashboard();
}

// ── Vehicle ───────────────────────────────────────────────────────────────
async function lookupPlate() {
  const plate = document.getElementById('plate-input').value.trim().toUpperCase();
  if (!plate) return toast('Enter plate number', 'error');
  const res  = await apiFetch('/vehicles/lookup', { method: 'POST', body: JSON.stringify({ number_plate: plate }) });
  const data = await res.json();
  const el   = document.getElementById('plate-result');
  if (data.found) {
    const v = data.vehicle;
    el.innerHTML = `<div class="card" style="background:var(--card-bg);border-color:var(--primary);color:var(--text)">
      ✅ <strong>${plate}</strong> — ${v.user_profiles?.full_name || 'Resident'} · Flat ${v.flats?.flat_number || '?'}
      ${v.make ? '<br><span style="font-size:.85rem;color:var(--muted)">'+v.make+' '+v.model+' · '+v.color+'</span>' : ''}
    </div>`;
  } else {
    el.innerHTML = `<div class="card" style="background:var(--card-bg);border-color:var(--warning);color:var(--text)">
      ⚠️ Non-Resident Vehicle — will be logged as visitor vehicle
    </div>`;
  }
}

async function logVehicleEntry() {
  const plate = document.getElementById('plate-input').value.trim().toUpperCase();
  if (!plate) return toast('Enter plate number', 'error');
  const res = await apiFetch('/vehicles/entry', { method: 'POST', body: JSON.stringify({ number_plate: plate }) });
  if (res.ok) {
    toast(`Entry logged: ${plate}`, 'success');
    document.getElementById('plate-input').value = '';
    document.getElementById('plate-result').innerHTML = '';
    loadVehicleEntries();
  } else toast('Failed to log entry', 'error');
}

async function logVehicleExitByPlate() {
  const plate = document.getElementById('exit-plate-input').value.trim().toUpperCase();
  if (!plate) return toast('Enter plate number', 'error');
  const el = document.getElementById('exit-result');
  // Find the open entry for this plate (no exit_time)
  const res = await apiFetch(`/vehicles/entries`);
  if (!res.ok) return toast('Failed to fetch entries', 'error');
  const entries = await res.json();
  const open = entries.find(e => e.number_plate === plate && !e.exit_time);
  if (!open) {
    el.innerHTML = `<div class="card" style="background:var(--card-bg);border-color:var(--warning);color:var(--text)">⚠️ No open entry found for ${plate}</div>`;
    return;
  }
  const exitRes = await apiFetch(`/vehicles/entry/${open.id}/exit`, { method: 'PATCH', body: '{}' });
  if (exitRes.ok) {
    toast(`Exit logged: ${plate}`, 'success');
    el.innerHTML = `<div class="card" style="background:var(--card-bg);border-color:var(--primary);color:var(--text)">✅ Exit logged for ${plate}</div>`;
    document.getElementById('exit-plate-input').value = '';
    loadVehicleEntries();
  } else toast('Failed to log exit', 'error');
}

async function loadVehicleEntries() {
  const res = await apiFetch('/vehicles/entries');
  const data = res.ok ? await res.json() : [];
  const html = data.length
    ? `<div style="overflow-x:auto"><table style="width:100%;font-size:.85rem">
        <thead><tr>
          <th style="color:#93b4d4;text-align:left;padding:6px">Plate</th>
          <th style="color:#93b4d4;text-align:left;padding:6px">Flat</th>
          <th style="color:#93b4d4;text-align:left;padding:6px">In</th>
          <th style="color:#93b4d4;text-align:left;padding:6px">Out</th>
        </tr></thead>
        <tbody>${data.map(e => `
          <tr>
            <td style="padding:6px;font-weight:600;letter-spacing:1px">${e.number_plate}</td>
            <td style="padding:6px;color:#93b4d4">${e.vehicles?.flats?.flat_number || (e.is_visitor_vehicle ? '🚶Visitor' : '—')}</td>
            <td style="padding:6px;color:#93b4d4">${timeAgo(e.entry_time)}</td>
            <td style="padding:6px">${e.exit_time ? '<span style="color:#34a853">'+timeAgo(e.exit_time)+'</span>' : '<span style="color:var(--warning)">Still inside</span>'}</td>
          </tr>`).join('')}
        </tbody>
      </table></div>`
    : '<p style="color:#93b4d4;text-align:center;padding:12px">No vehicles today</p>';

  // Update both places (page + dashboard)
  const listEl = document.getElementById('vehicle-entries-list');
  if (listEl) listEl.innerHTML = html;
  const recentEl = document.getElementById('recent-entries');
  if (recentEl) recentEl.innerHTML = html;
}

// ── Delivery ──────────────────────────────────────────────────────────────
async function loadDeliveryFlats() {
  await loadFlatsList();
  const delFlat = document.getElementById('del-flat');
  if (delFlat.options.length < 2) {
    flatsCache.forEach(f => {
      const o = document.createElement('option');
      o.value = f.id;
      o.textContent = `${f.buildings?.name || ''} - ${f.flat_number}`;
      delFlat.appendChild(o);
    });
  }
  // Load platforms
  const pRes = await apiFetch('/delivery/platforms');
  if (pRes.ok) {
    const platforms = await pRes.json();
    const pSel = document.getElementById('del-platform');
    platforms.forEach(p => {
      const o = document.createElement('option');
      o.value = p.id; o.textContent = p.name;
      pSel.appendChild(o);
    });
  }
}

async function logDelivery() {
  const body = {
    flat_id:       document.getElementById('del-flat').value,
    platform_id:   document.getElementById('del-platform').value || null,
    tracking_id:   document.getElementById('del-tracking').value.trim(),
    leave_at_gate: document.getElementById('del-lag').checked,
  };
  if (!body.flat_id) return toast('Select flat', 'error');
  const res  = await apiFetch('/delivery/', { method: 'POST', body: JSON.stringify(body) });
  const data = await res.json();
  if (res.ok) {
    let msg = 'Delivery logged — resident notified';
    if (data.parcel_otp) msg += ` · Parcel OTP: ${data.parcel_otp}`;
    toast(msg, 'success');
  } else toast('Failed', 'error');
}

async function collectParcel() {
  const id  = document.getElementById('parcel-delivery-id').value.trim();
  const otp = document.getElementById('parcel-otp-input').value.trim();
  if (!id || !otp) return toast('Delivery ID and OTP required', 'error');
  const res = await apiFetch(`/delivery/${id}/collect`, { method: 'POST', body: JSON.stringify({ otp }) });
  if (res.ok) toast('Parcel collected ✓', 'success');
  else { const e = await res.json(); toast(e.error || 'Failed', 'error'); }
}

// ── Domestic Help ─────────────────────────────────────────────────────────
let currentHelper = null;

async function lookupHelper() {
  const passcode = document.getElementById('helper-passcode').value.trim();
  if (!passcode || passcode.length !== 6) return toast('Enter 6-digit passcode', 'error');
  const res  = await apiFetch('/domestic-help/lookup', { method: 'POST', body: JSON.stringify({ passcode }) });
  const data = await res.json();
  const el   = document.getElementById('helper-result');
  if (res.ok) {
    currentHelper = data;
    const flatInfo = (data.helper_flat_links || []).map(l => l.flats?.flat_number).join(', ');
    el.innerHTML = `
      <div class="card" style="background:var(--card-bg);border:2px solid var(--primary);display:flex;gap:12px;align-items:center">
        <img src="${data.photo_url || 'https://ui-avatars.com/api/?name='+encodeURIComponent(data.name)}" style="width:52px;height:52px;border-radius:50%">
        <div>
          <div style="font-weight:700;color:var(--text)">${data.name}</div>
          <div style="font-size:.85rem;color:var(--muted)">${data.helper_type} · Flat ${flatInfo}</div>
        </div>
      </div>`;
    
    const btnContainer = document.getElementById('helper-entry-btn');
    if (data.active_entry) {
      // Already entered today, show Exit button
      btnContainer.innerHTML = '<button class="btn btn-warning btn-full" onclick="logHelperExit()">Log Exit</button>';
    } else {
      // No entry today, show Entry button
      btnContainer.innerHTML = '<button class="btn btn-success btn-full" onclick="logHelperEntry()">✓ Log Entry</button>';
    }
    btnContainer.style.display = 'block';
  } else {
    el.innerHTML = `<div class="card" style="background:var(--card-bg);border:2px solid var(--danger);color:var(--text)">❌ ${data.error || 'Unknown passcode'}</div>`;
    document.getElementById('helper-entry-btn').style.display = 'none';
  }
}

async function logHelperEntry() {
  if (!currentHelper) return;
  const flatLinks = currentHelper.helper_flat_links || [];
  const flatId    = flatLinks[0]?.flat_id;
  const res = await apiFetch('/domestic-help/entry', {
    method: 'POST',
    body: JSON.stringify({ passcode: document.getElementById('helper-passcode').value.trim(), flat_id: flatId }),
  });
  if (res.ok) {
    toast(`Entry logged for ${currentHelper.name}`, 'success');
    document.getElementById('helper-passcode').value = '';
    document.getElementById('helper-result').innerHTML = '';
    document.getElementById('helper-entry-btn').style.display = 'none';
    currentHelper = null;
  } else toast('Failed to log entry', 'error');
}

async function logHelperExit() {
  if (!currentHelper || !currentHelper.active_entry) return;
  const attendanceId = currentHelper.active_entry.id;
  const res = await apiFetch(`/domestic-help/attendance/${attendanceId}/exit`, {
    method: 'PATCH',
  });
  if (res.ok) {
    toast(`Exit logged for ${currentHelper.name}`, 'success');
    document.getElementById('helper-passcode').value = '';
    document.getElementById('helper-result').innerHTML = '';
    document.getElementById('helper-entry-btn').style.display = 'none';
    currentHelper = null;
  } else toast('Failed to log exit', 'error');
}


// ── Kids Checkout ─────────────────────────────────────────────────────────
async function initiateKidsCheckout() {
  const flatId = document.getElementById('kids-flat').value;
  if (!flatId) return toast('Select flat', 'error');
  const res  = await apiFetch('/kids-checkout/request', { method: 'POST', body: JSON.stringify({ flat_id: flatId }) });
  const data = await res.json();
  if (res.ok) {
    document.getElementById('kids-result').innerHTML = `
      <div class="card" style="background:var(--card-bg);border-color:var(--warning);color:var(--text)">
        ⏳ Waiting for parent approval (Event ID: ${data.id?.slice(0,8)}...)
      </div>`;
    toast('Request sent to parent', 'success');
    // Subscribe to response
    sb.channel(`kids-${data.id}`)
      .on('postgres_changes', { event: 'UPDATE', schema: 'public', table: 'kids_checkout_events', filter: `id=eq.${data.id}` },
        payload => {
          const status = payload.new.status;
          const border = status === 'approved' ? 'var(--primary)' : 'var(--danger)';
          document.getElementById('kids-result').innerHTML = `
            <div class="card" style="background:var(--card-bg);border-color:${border};color:var(--text)">
              ${status === 'approved' ? '✅ Parent approved — allow exit' : '❌ Parent denied — hold child'}
            </div>`;
          toast(status === 'approved' ? 'Exit approved!' : 'Exit denied!', status === 'approved' ? 'success' : 'error');
        }
      ).subscribe();
  } else {
    document.getElementById('kids-result').innerHTML = `<div class="card" style="background:var(--card-bg);border-color:var(--danger);color:var(--text)">❌ ${data.error}</div>`;
  }
}

// ── Helper functions ──────────────────────────────────────────────────────
function formatDateTime(isoString) {
  if (!isoString) return '';
  const d = new Date(isoString);
  const date = d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' });
  const time = d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: true });
  return `${date} ${time}`;
}

function timeAgo(isoString) {
  if (!isoString) return '';
  const now = new Date();
  const then = new Date(isoString);
  const diffMs = now - then;
  const diffMins = Math.floor(diffMs / 60000);
  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  return `${diffDays}d ago`;
}
