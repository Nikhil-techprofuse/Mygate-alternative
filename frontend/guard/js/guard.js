let loginMode = 'phone';

window.addEventListener('DOMContentLoaded', () => {
  if (Auth.isLoggedIn()) {
    showApp();
  }

  // Handle Supabase OAuth / Magic Link redirects
  if (typeof sb !== 'undefined') {
    sb.auth.onAuthStateChange(async (event, session) => {
      if (session && !Auth.isLoggedIn()) {
        const res = await fetch(API_BASE + '/auth/verify-session', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            access_token: session.access_token,
            refresh_token: session.refresh_token
          })
        });
        const data = await res.ok ? await res.json() : null;
        if (res.ok && data) {
          if (!['guard', 'super_admin'].includes(data.role)) {
            toast('Access denied — this portal is for Security Guards only', 'error');
            await sb.auth.signOut();
            return;
          }
          Auth.save(data);
          showApp();
          toast('Logged in successfully!', 'success');
        } else {
          const err = res ? (res.ok ? { error: 'Verification failed' } : await res.json().catch(() => ({ error: 'Verification failed' }))) : { error: 'Verification failed' };
          toast(err.error || 'Authentication failed', 'error');
          await sb.auth.signOut();
        }
      }
    });
  }
});

function showApp() {
  document.getElementById('login-screen').style.display = 'none';
  document.getElementById('app-shell').style.display    = 'block';
  loadGuardDashboard();
  loadGuardProfile();
  subscribeAlerts();
  subscribeVisitorQueue();
}

function toggleUserMenu() {
  const menu = document.getElementById('user-dropdown-menu');
  if (menu) menu.classList.toggle('show');
}

// Close dropdown when clicking outside
window.addEventListener('click', (e) => {
  const trigger = document.getElementById('topbar-user-trigger');
  const menu = document.getElementById('user-dropdown-menu');
  if (menu && menu.classList.contains('show')) {
    if (!menu.contains(e.target) && (!trigger || !trigger.contains(e.target))) {
      menu.classList.remove('show');
    }
  }
});

async function loadGuardProfile() {
  try {
    const res = await apiFetch('/auth/me');
    if (!res.ok) return;
    const profile = await res.json();
    
    const name = profile.full_name || 'Guard';
    const gate = profile.gate_id || 'GATE-A';
    
    const nameEl = document.getElementById('guard-name-display');
    if (nameEl) nameEl.textContent = name;
    
    const gateEl = document.getElementById('gate-name-display');
    if (gateEl) gateEl.textContent = gate;
    
    const avatarEl = document.getElementById('guard-profile-avatar');
    if (avatarEl && name) {
      avatarEl.textContent = name.charAt(0).toUpperCase();
    }
    
    const dropdownNameEl = document.getElementById('dropdown-guard-name');
    if (dropdownNameEl) dropdownNameEl.textContent = name;
    
    const dropdownGateEl = document.getElementById('dropdown-guard-gate');
    if (dropdownGateEl) dropdownGateEl.textContent = `Security Guard · ${gate}`;
  } catch (err) {
    console.error('Failed to load guard profile:', err);
  }
}

function resetLogin() {
  document.getElementById('step-phone').style.display = 'block';
  document.getElementById('step-email').style.display = 'none';
  document.getElementById('step-otp').style.display   = 'none';
  switchLoginTab('phone');
}

function switchLoginTab(tab) {
  const phoneBtn = document.getElementById('btn-phone-tab');
  const emailBtn = document.getElementById('btn-email-tab');
  const phoneForm = document.getElementById('step-phone');
  const emailForm = document.getElementById('step-email');
  const otpForm = document.getElementById('step-otp');

  otpForm.style.display = 'none';

  if (tab === 'phone') {
    phoneForm.style.display = 'block';
    emailForm.style.display = 'none';
    phoneBtn.className = 'btn btn-primary';
    emailBtn.className = 'btn btn-ghost';
  } else {
    phoneForm.style.display = 'none';
    emailForm.style.display = 'block';
    emailBtn.className = 'btn btn-primary';
    phoneBtn.className = 'btn btn-ghost';
  }
}

// ── Auth ──────────────────────────────────────────────────────────────────
async function sendOtp() {
  loginMode = 'phone';
  const phone = document.getElementById('inp-phone').value.trim();
  if (!phone) return toast('Enter phone', 'error');
  const res = await fetch(API_BASE + '/auth/send-otp', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ phone }),
  });
  const data = await res.json().catch(() => ({}));
  if (res.ok) {
    document.getElementById('step-phone').style.display = 'none';
    document.getElementById('step-otp').style.display   = 'block';
    document.getElementById('otp-phone-display').textContent = phone;
    toast(data.message || 'OTP sent!', 'success');
  } else {
    const errorMsg = data.detail ? `${data.error || 'Failed to send OTP'}: ${data.detail}` : (data.error || 'Failed to send OTP');
    toast(errorMsg, 'error');
  }
}

async function verifyOtp() {
  if (loginMode === 'email') {
    return verifyEmailOtp();
  }
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

async function sendEmailOtp() {
  loginMode = 'email';
  const email = document.getElementById('inp-email').value.trim();
  if (!email) return toast('Enter email address', 'error');
  toast('Sending OTP to email...', 'info');
  const res = await fetch(API_BASE + '/auth/magic-link', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email })
  });
  const data = await res.json();
  if (res.ok) {
    document.getElementById('step-email').style.display = 'none';
    document.getElementById('step-otp').style.display   = 'block';
    document.getElementById('otp-phone-display').textContent = email;
    toast(data.message || 'Check your email for the OTP code!', 'success');
  } else {
    const errorMsg = data.detail ? `${data.error || 'Failed to send email OTP'}: ${data.detail}` : (data.error || 'Failed to send email OTP');
    toast(errorMsg, 'error');
  }
}

async function verifyEmailOtp() {
  const email = document.getElementById('inp-email').value.trim();
  const token = document.getElementById('inp-otp').value.trim();
  const res = await fetch(API_BASE + '/auth/verify-email-otp', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, token }),
  });
  const data = await res.json();
  if (res.ok) {
    if (!['guard', 'super_admin'].includes(data.role)) {
      return toast('Access denied — this portal is for Security Guards only', 'error');
    }
    Auth.save(data);
    showApp();
  } else {
    toast(data.error || 'Invalid OTP', 'error');
  }
}

async function loginWithGoogle() {
  if (typeof sb === 'undefined') return toast('Supabase client not loaded', 'error');
  try {
    toast('Redirecting to Google...', 'info');
    const { error } = await sb.auth.signInWithOAuth({
      provider: 'google',
      options: {
        redirectTo: window.location.origin + '/guard/'
      }
    });
    if (error) throw error;
  } catch (err) {
    toast(err.message || 'Google OAuth failed', 'error');
  }
}

async function logout() {
  Auth.clear();
  if (typeof sb !== 'undefined') {
    await sb.auth.signOut();
  }
  window.location.reload();
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

  // Stats cards removed per user request

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
          <div style="font-size:.8rem;color:var(--muted)">${v.visitor_type} · Flat ${v.flats?.flat_number || '?'}${v.flats?.buildings?.name ? ` (${v.flats.buildings.name})` : ''} · ${timeAgo(v.entry_time)}</div>
        </div>
        <span style="padding:5px 12px;font-size:.8rem;background:var(--card-bg);color:var(--warning);border:1px solid var(--warning);border-radius:4px">⏳ Pending</span>
      </div>`).join('')
    : '<p style="color:var(--muted);text-align:center;padding:12px">No pending approvals</p>';

  // Recent visitor entries (pre-approved OTP + walk-in approved)
  const recentVisitors = visitors.filter(v => ['approved', 'pre_approved'].includes(v.approval_status));
  document.getElementById('recent-visitors').innerHTML = recentVisitors.length
    ? recentVisitors.slice(0, 10).map(v => `
      <div style="display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid var(--border)">
        <div style="flex:1">
          <div style="font-weight:600;color:var(--text)">${v.visitor_name}</div>
          <div style="font-size:.85rem;color:var(--muted);margin-top:4px">
            📍 Flat ${v.flats?.flat_number || '?'} ${v.visitor_phone ? `· 📱 ${v.visitor_phone}` : ''}
          </div>
          <div style="font-size:.8rem;color:var(--muted);margin-top:2px">
            ⏱ Entry: ${formatDateTime(v.entry_time)}${v.exit_time ? ` · Exit: ${formatDateTime(v.exit_time)}` : ' · <span style="color:var(--warning)">Still inside</span>'}
          </div>
        </div>
        ${!v.exit_time ? `<button class="btn btn-success" style="padding:5px 12px;font-size:.8rem" onclick="logExitGuard('${v.id}')">Exit</button>` : ''}
      </div>`).join('')
    : '<p style="color:var(--muted);text-align:center;padding:12px">No visitor entries today</p>';

  // Recent vehicle entries
  loadVehicleEntries();
  
  // Gate deliveries
  loadGateDeliveriesHome();
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

// ── Unified code verify (visitor OTP + helper passcode) ─────────────────────
let currentHelper = null;
let currentHelperPasscode = '';

async function verifyUnifiedCode() {
  const code = document.getElementById('unified-code-input').value.trim();
  const resultDiv = document.getElementById('unified-code-result');
  const actionsDiv = document.getElementById('unified-code-actions');

  if (!code || code.length < 4 || !/^\d+$/.test(code)) {
    return toast('Enter a 4–6 digit code', 'error');
  }

  resultDiv.innerHTML = '';
  actionsDiv.style.display = 'none';
  actionsDiv.innerHTML = '';
  currentHelper = null;
  currentHelperPasscode = '';

  const res = await apiFetch('/guards/verify-code', {
    method: 'POST',
    body: JSON.stringify({ code }),
  });
  const data = await res.json();

  if (res.ok) {
    document.getElementById('unified-code-input').value = '';
    if (data.type === 'visitor') {
      displayVisitorDetails(data.data);
      loadGuardDashboard();
    } else if (data.type === 'helper') {
      currentHelperPasscode = code;
      displayHelperDetails(data.data);
    }
    return;
  }

  resultDiv.innerHTML = `
    <div class="verify-result-card error">
      ❌ ${data.error || 'Code not found'}
    </div>`;
}

function displayVisitorDetails(visitor) {
  const resultDiv = document.getElementById('unified-code-result');
  const validUntil = visitor.valid_until
    ? `Valid until ${formatDateTime(visitor.valid_until)}`
    : '';
  resultDiv.innerHTML = `
    <div class="verify-result-card">
      <div class="verify-result-title">✅ ${visitor.visitor_name}</div>
      <div class="verify-result-meta">
        Visitor · Flat ${visitor.flat?.flat_number || '?'}
        ${visitor.visitor_phone ? ` · ${visitor.visitor_phone}` : ''}
      </div>
      ${validUntil ? `<div class="verify-result-meta">${validUntil}</div>` : ''}
      <div class="verify-result-meta" style="color:var(--success);margin-top:6px">Entry approved and logged</div>
    </div>`;
  toast(`Entry approved: ${visitor.visitor_name}`, 'success');
}

function displayHelperDetails(helper) {
  currentHelper = helper;
  const flatInfo = (helper.helper_flat_links || []).map(l => l.flats?.flat_number).filter(Boolean).join(', ');
  const resultDiv = document.getElementById('unified-code-result');
  const actionsDiv = document.getElementById('unified-code-actions');

  resultDiv.innerHTML = `
    <div class="verify-result-card" style="display:flex;gap:12px;align-items:center">
      <img class="verify-result-avatar" src="${helper.photo_url || 'https://ui-avatars.com/api/?name=' + encodeURIComponent(helper.name)}" alt="">
      <div>
        <div class="verify-result-title">${helper.name}</div>
        <div class="verify-result-meta">${helper.helper_type}${flatInfo ? ' · Flat ' + flatInfo : ''}</div>
        <div class="verify-result-meta">${helper.active_entry ? 'Currently inside' : 'Not checked in today'}</div>
      </div>
    </div>`;

  if (helper.active_entry) {
    actionsDiv.innerHTML = '<button class="btn btn-warning btn-full" onclick="logHelperExit()">Log Exit</button>';
  } else {
    actionsDiv.innerHTML = '<button class="btn btn-success btn-full" onclick="logHelperEntry()">✓ Log Entry</button>';
  }
  actionsDiv.style.display = 'block';
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
    const data = await res.json();
    const flatNo = data.log?.flats?.flat_number || '?';
    toast(`Approval request sent to Flat ${flatNo}`, 'success');
    document.getElementById('walkin-name').value = '';
    document.getElementById('walkin-phone').value = '';
    document.getElementById('walkin-flat').value = '';
    loadGuardDashboard();
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
          <th style="color:var(--muted);text-align:left;padding:6px">Plate</th>
          <th style="color:var(--muted);text-align:left;padding:6px">Flat</th>
          <th style="color:var(--muted);text-align:left;padding:6px">In</th>
          <th style="color:var(--muted);text-align:left;padding:6px">Out</th>
        </tr></thead>
        <tbody>${data.map(e => `
          <tr>
            <td style="padding:6px;font-weight:600;letter-spacing:1px">${e.number_plate}</td>
            <td style="padding:6px;color:var(--muted)">${e.vehicles?.flats?.flat_number || (e.is_visitor_vehicle ? '🚶Visitor' : '—')}</td>
            <td style="padding:6px;color:var(--muted)">${timeAgo(e.entry_time)}</td>
            <td style="padding:6px">${e.exit_time ? '<span style="color:var(--success)">'+timeAgo(e.exit_time)+'</span>' : '<span style="color:var(--warning)">Still inside</span>'}</td>
          </tr>`).join('')}
        </tbody>
      </table></div>`
    : '<p style="color:var(--muted);text-align:center;padding:12px">No vehicles today</p>';

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
}

async function logDelivery() {
  const body = {
    flat_id:       document.getElementById('del-flat').value,
    platform_name: document.getElementById('del-platform').value.trim() || null,
    tracking_id:   document.getElementById('del-tracking').value.trim(),
  };
  if (!body.flat_id) return toast('Select flat', 'error');
  const res  = await apiFetch('/delivery/', { method: 'POST', body: JSON.stringify(body) });
  const data = await res.json();
  if (res.ok) {
    toast('Delivery logged — resident notified', 'success');
    // Clear form
    document.getElementById('del-platform').value = '';
    document.getElementById('del-tracking').value = '';
  } else toast('Failed', 'error');
}

async function loadGateDeliveriesHome() {
  const res = await apiFetch('/delivery/?status=arrived,left_at_gate');
  if (!res.ok) return;
  const data = await res.json();
  
  console.log('Gate deliveries:', data); // Debug log
  
  // Show all arrived and left_at_gate deliveries
  const waiting = data.filter(d => ['arrived', 'left_at_gate'].includes(d.status));
  
  const html = waiting.length
    ? waiting.map(d => {
        const codeHtml = d.parcel_otp 
          ? `<div style="background:var(--code-badge-bg);border-radius:6px;padding:8px;margin-top:8px;display:inline-block">
              <div style="font-size:.65rem;color:var(--code-badge-text);opacity:0.8;margin-bottom:2px">COLLECTION CODE</div>
              <div style="font-size:1.3rem;font-weight:900;letter-spacing:2px;color:var(--code-badge-text);word-break:break-all">${d.parcel_otp}</div>
            </div>`
          : '<div style="font-size:.8rem;color:var(--warning);margin-top:4px">⚠ No collection code yet</div>';
        
        return `
          <div style="padding:12px 0;border-bottom:1px solid var(--border)">
            <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:12px">
              <div style="flex:1">
                <div style="font-weight:700;font-size:1rem;display:flex;align-items:center;gap:8px">
                  ${d.delivery_platforms?.name || 'Delivery'}
                  ${statusBadge(d.status)}
                </div>
                <div style="font-size:.85rem;color:var(--text);margin-top:2px">
                  📍 Flat ${d.flats?.flat_number || '?'}
                </div>
                <div style="font-size:.8rem;color:var(--muted);margin-top:2px">
                  ${d.tracking_id ? '🔖 Tracking: ' + d.tracking_id : 'No tracking ID'}
                </div>
                <div style="font-size:.75rem;color:var(--muted);margin-top:2px">
                  ⏱ ${d.status === 'left_at_gate' ? 'Received at gate: ' + timeAgo(d.exit_time || d.entry_time) : 'Logged: ' + timeAgo(d.entry_time)}
                </div>
                ${codeHtml}
              </div>
            </div>
            <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:12px">
              <button class="btn ${d.status === 'arrived' ? 'btn-warning' : 'btn-ghost'}" style="padding:5px 10px;font-size:.75rem;flex:1;min-width:110px" onclick="updateDeliveryStatus('${d.id}', 'arrived')">⏳ Pending</button>
              <button class="btn ${d.status === 'left_at_gate' ? 'btn-primary' : 'btn-ghost'}" style="padding:5px 10px;font-size:.75rem;flex:1;min-width:150px" onclick="updateDeliveryStatus('${d.id}', 'left_at_gate')">📦 Received at Gate</button>
              <button class="btn btn-ghost" style="padding:5px 10px;font-size:.75rem;flex:1;min-width:150px;color:var(--success);border-color:var(--success)" onclick="updateDeliveryStatus('${d.id}', 'collected')">✅ Collected</button>
            </div>
          </div>
        `;
      }).join('')
    : '<p style="text-align:center;padding:12px;color:var(--muted)">No deliveries waiting for pickup</p>';
  
  document.getElementById('gate-deliveries-home').innerHTML = html;
}

async function updateDeliveryStatus(deliveryId, newStatus) {
  const res = await apiFetch(`/delivery/${deliveryId}/status`, {
    method: 'PATCH',
    body: JSON.stringify({ status: newStatus })
  });
  if (res.ok) {
    const labels = {
      arrived: 'pending',
      left_at_gate: 'received at gate',
      collected: 'collected'
    };
    const statusLabel = labels[newStatus] || newStatus;
    toast(`Delivery status updated to: ${statusLabel} ✓`, 'success');
    loadGateDeliveriesHome();
  } else {
    const err = await res.json();
    toast(err.error || 'Failed to update status', 'error');
  }
}

// ── Domestic Help entry/exit (after unified verify) ───────────────────────
function clearUnifiedHelperResult() {
  document.getElementById('unified-code-result').innerHTML = '';
  document.getElementById('unified-code-actions').style.display = 'none';
  document.getElementById('unified-code-actions').innerHTML = '';
  currentHelper = null;
  currentHelperPasscode = '';
}

async function logHelperEntry() {
  if (!currentHelper || !currentHelperPasscode) return;
  const flatLinks = currentHelper.helper_flat_links || [];
  const flatId    = flatLinks[0]?.flat_id;
  const res = await apiFetch('/domestic-help/entry', {
    method: 'POST',
    body: JSON.stringify({ passcode: currentHelperPasscode, flat_id: flatId }),
  });
  if (res.ok) {
    toast(`Entry logged for ${currentHelper.name}`, 'success');
    clearUnifiedHelperResult();
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
    clearUnifiedHelperResult();
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
