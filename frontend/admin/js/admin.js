// ── Admin Portal JS ───────────────────────────────────────────────────────

window.addEventListener('DOMContentLoaded', () => {
  if (Auth.isLoggedIn()) showAdminApp();
});

function showAdminApp() {
  document.getElementById('login-screen').style.display = 'none';
  document.getElementById('app-shell').style.display    = 'block';
  loadOverview();
}

function nav(pageId) {
  showPage(pageId);
  const loaders = {
    'page-residents': loadResidents,
    'page-vehicles':  loadVehicles,
    'page-staff':     loadStaff,
    'page-billing':   loadBilling,
    'page-helpdesk':  loadTickets,
    'page-amenities': loadAmenities,
    'page-alerts':    loadAlerts,
    'page-society':   loadSocietySetup,
  };
  if (loaders[pageId]) loaders[pageId]();
}

function logout() { Auth.clear(); location.reload(); }

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
  } else toast('Failed to send OTP', 'error');
}

async function verifyOtp() {
  const phone = document.getElementById('inp-phone').value.trim();
  const token = document.getElementById('inp-otp').value.trim();
  const res = await fetch(API_BASE + '/auth/verify-otp', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ phone, token }),
  });
  if (res.ok) {
    const data = await res.json();
    if (!['super_admin', 'committee_member'].includes(data.role))
      return toast('Admin access only', 'error');
    Auth.save(data);
    showAdminApp();
  } else toast('Invalid OTP', 'error');
}

// ── Overview ──────────────────────────────────────────────────────────────
async function loadOverview() {
  const [alertsRes, ticketsRes, residentsRes] = await Promise.all([
    apiFetch('/security-alerts/'),
    apiFetch('/helpdesk/'),
    apiFetch('/admin/residents'),
  ]);
  const alerts    = alertsRes.ok    ? await alertsRes.json()    : [];
  const tickets   = ticketsRes.ok   ? await ticketsRes.json()   : [];
  const residents = residentsRes.ok ? await residentsRes.json() : [];

  const activeAlerts = alerts.filter(a => a.alert_status === 'sent').length;
  const openTickets  = tickets.filter(t => t.status === 'open').length;

  document.getElementById('overview-stats').innerHTML = `
    <div class="stat-card"><div class="stat-val">${residents.length}</div><div class="stat-lbl">Residents</div></div>
    <div class="stat-card"><div class="stat-val" style="color:var(--danger)">${activeAlerts}</div><div class="stat-lbl">Active Alerts</div></div>
    <div class="stat-card"><div class="stat-val" style="color:var(--warning)">${openTickets}</div><div class="stat-lbl">Open Tickets</div></div>
    <div class="stat-card"><div class="stat-val" style="color:var(--success)">${tickets.filter(t=>t.status==='resolved').length}</div><div class="stat-lbl">Resolved</div></div>
  `;

  // Charts
  const alertCounts = {
    sent:         alerts.filter(a=>a.alert_status==='sent').length,
    acknowledged: alerts.filter(a=>a.alert_status==='acknowledged').length,
    resolved:     alerts.filter(a=>a.alert_status==='resolved').length,
  };
  new Chart(document.getElementById('chart-alerts'), {
    type: 'doughnut',
    data: {
      labels: ['Active', 'Acknowledged', 'Resolved'],
      datasets: [{ data: Object.values(alertCounts), backgroundColor: ['#ea4335','#fbbc04','#34a853'] }],
    },
    options: { plugins: { legend: { position: 'bottom' } } },
  });

  // Recent alerts table
  document.getElementById('recent-alerts-table').innerHTML = `
    <div class="table-wrap"><table>
      <thead><tr><th>Flat</th><th>Type</th><th>Status</th><th>Time</th></tr></thead>
      <tbody>${alerts.slice(0,10).map(a => `<tr>
        <td>${a.flats?.flat_number || '—'}</td>
        <td>${a.alert_type}</td>
        <td>${statusBadge(a.alert_status)}</td>
        <td>${fmtDate(a.created_at)}</td>
      </tr>`).join('')}</tbody>
    </table></div>`;
}

// ── Society Setup ─────────────────────────────────────────────────────────
async function loadSocietySetup() {
  const hasSociety = !!Auth.societyId && Auth.societyId !== '00000000-0000-0000-0000-000000000000';
  document.getElementById('create-society-card').style.display = hasSociety ? 'none' : 'block';
  document.getElementById('society-setup-grid').style.display  = hasSociety ? 'grid' : 'none';
  if (!hasSociety) return;

  const [bldRes, gateRes, flatRes] = await Promise.all([
    apiFetch('/admin/buildings'),
    apiFetch('/admin/gates'),
    apiFetch('/admin/flats'),
  ]);
  const buildings = bldRes.ok  ? await bldRes.json()  : [];
  const gates     = gateRes.ok ? await gateRes.json() : [];
  const flats     = flatRes.ok ? await flatRes.json() : [];

  // Count flats per building
  const flatCount = {};
  flats.forEach(f => { flatCount[f.building_id] = (flatCount[f.building_id] || 0) + 1; });

  document.getElementById('buildings-list').innerHTML = buildings.length
    ? buildings.map(b => `
        <div style="display:flex;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border)">
          <div>
            <span>🏢</span> <strong>${b.name}</strong>
            <span style="font-size:.8rem;color:var(--muted);margin-left:6px">${b.floors} floor${b.floors !== 1 ? 's' : ''}</span>
          </div>
          <div style="display:flex;align-items:center;gap:8px">
            <span class="badge badge-info">${flatCount[b.id] || 0} flat${(flatCount[b.id] || 0) !== 1 ? 's' : ''}</span>
            <button class="btn btn-danger" style="padding:2px 8px;font-size:.75rem" onclick="deleteBuilding('${b.id}','${b.name.replace(/'/g,String.fromCharCode(39))}')">✕</button>
          </div>
        </div>`).join('')
    : '<p style="color:var(--muted);font-size:.875rem">No buildings yet</p>';

  document.getElementById('gates-list').innerHTML = gates.length
    ? gates.map(g => `
        <div style="display:flex;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border)">
          <div>🚪 <strong>${g.name}</strong>
            <span style="font-size:.8rem;color:var(--muted);margin-left:6px">${g.type.replace('_',' ')}</span>
          </div>
          <button class="btn btn-danger" style="padding:2px 8px;font-size:.75rem" onclick="deleteGate('${g.id}','${g.name.replace(/'/g,String.fromCharCode(39))}')">✕</button>
        </div>`).join('')
    : '<p style="color:var(--muted);font-size:.875rem">No gates yet</p>';

  // Wire up preview on the building inputs
  ['new-building-floors', 'new-building-fpf'].forEach(id => {
    const el = document.getElementById(id);
    if (el && !el._previewBound) {
      el.addEventListener('input', _updateBuildingPreview);
      el._previewBound = true;
    }
  });
  _updateBuildingPreview();
}

function _updateBuildingPreview() {
  const floors = parseInt(document.getElementById('new-building-floors')?.value) || 0;
  const fpf    = parseInt(document.getElementById('new-building-fpf')?.value)    || 0;
  const preview = document.getElementById('building-flat-preview');
  if (!preview) return;
  if (floors > 0 && fpf > 0) {
    preview.textContent = `→ Will auto-create ${floors * fpf} flats (${fpf} per floor × ${floors} floors)`;
  } else if (floors > 0) {
    preview.textContent = `→ ${floors} floor${floors !== 1 ? 's' : ''} · enter flats/floor to auto-generate flats`;
  } else {
    preview.textContent = '';
  }
}

async function createSociety() {
  const name    = document.getElementById('soc-name').value.trim();
  const address = document.getElementById('soc-address').value.trim();
  const city    = document.getElementById('soc-city').value.trim();
  const state   = document.getElementById('soc-state').value.trim();
  const pincode = document.getElementById('soc-pincode').value.trim();
  if (!name) return toast('Society name required', 'error');
  const res = await apiFetch('/admin/society', {
    method: 'POST',
    body: JSON.stringify({ name, address, city, state, pincode }),
  });
  if (!res.ok) return toast((await res.json()).error || 'Failed', 'error');
  const society = await res.json();
  // Persist the new society_id so all subsequent API calls use it
  localStorage.setItem('adm_society_id', society.id);
  toast('Society created!', 'success');
  loadSocietySetup();
}

async function addBuilding() {
  const name   = document.getElementById('new-building-name').value.trim();
  const floors = parseInt(document.getElementById('new-building-floors').value) || 1;
  const fpf    = parseInt(document.getElementById('new-building-fpf').value)    || 0;

  if (!name)   return toast('Building name is required', 'error');
  if (floors < 1 || floors > 100) return toast('Floors must be between 1 and 100', 'error');

  const res = await apiFetch('/admin/buildings', {
    method: 'POST',
    body: JSON.stringify({ name, floors, flats_per_floor: fpf }),
  });

  if (res.ok) {
    const bldg = await res.json();
    const totalFlats = bldg.flats_created || 0;
    toast(
      totalFlats > 0
        ? `Building added · ${totalFlats} flats auto-created`
        : 'Building added',
      'success'
    );
    // Reset all three fields
    document.getElementById('new-building-name').value   = '';
    document.getElementById('new-building-floors').value = '1';
    document.getElementById('new-building-fpf').value    = '0';
    document.getElementById('building-flat-preview').textContent = '';
    loadSocietySetup();
  } else {
    const err = await res.json().catch(() => ({}));
    toast(err.error || 'Failed to add building', 'error');
  }
}

async function addGate() {
  const name = document.getElementById('new-gate-name').value.trim();
  const type = document.getElementById('new-gate-type').value;
  if (!name) return toast('Gate name required', 'error');
  const res = await apiFetch('/admin/gates', { method: 'POST', body: JSON.stringify({ name, type }) });
  if (res.ok) { toast('Gate added', 'success'); document.getElementById('new-gate-name').value = ''; loadSocietySetup(); }
  else toast('Failed', 'error');
}

async function deleteBuilding(id, name) {
  if (!confirm(`Delete building "${name}"?\n\nThis will also delete all its flats and unlink any residents. This cannot be undone.`)) return;
  const res = await apiFetch(`/admin/buildings/${id}`, { method: 'DELETE' });
  if (res.ok) { toast(`${name} deleted`, 'success'); loadSocietySetup(); }
  else { const e = await res.json().catch(() => ({})); toast(e.error || 'Failed to delete', 'error'); }
}

async function deleteGate(id, name) {
  if (!confirm(`Delete gate "${name}"?`)) return;
  const res = await apiFetch(`/admin/gates/${id}`, { method: 'DELETE' });
  if (res.ok) { toast(`${name} deleted`, 'success'); loadSocietySetup(); }
  else { const e = await res.json().catch(() => ({})); toast(e.error || 'Failed to delete', 'error'); }
}

// ── Residents ─────────────────────────────────────────────────────────────
let residentsCache  = [];
let _buildingsCache = [];
let _editingResidentId = null;
let _familyModalResidentId = null;
// Pending family rows added in the modal (before resident is saved)
let _pendingFamily = [];

async function loadResidents() {
  const res = await apiFetch('/admin/residents');
  residentsCache = res.ok ? await res.json() : [];
  renderResidents(residentsCache);
}

function _flatLabel(r) {
  const flat = r.flats;
  if (!flat) return { bldg: '—', floor: '—', flatno: '—' };
  return {
    bldg:  flat.buildings?.name || '—',
    floor: flat.floor != null ? flat.floor : '—',
    flatno: flat.flat_number || '—',
  };
}

function renderResidents(data) {
  const tbody = document.getElementById('residents-table');
  if (!data.length) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center;color:var(--muted);padding:24px">No residents yet. Click "+ Add Resident" to begin.</td></tr>`;
    return;
  }
  tbody.innerHTML = data.map(r => {
    const f = _flatLabel(r);
    const nameEsc = (r.full_name || '').replace(/'/g, '&#39;');
    return `<tr>
      <td><strong>${r.full_name || '—'}</strong></td>
      <td>${r.phone || '<span style="color:var(--muted)">—</span>'}</td>
      <td>${f.bldg}</td>
      <td>${f.floor}</td>
      <td>${f.flatno}</td>
      <td>${statusBadge(r.role)}</td>
      <td>
        <button class="btn btn-ghost" style="padding:2px 8px;font-size:.8rem" onclick="openFamilyModal('${r.id}','${nameEsc}')">
          👨‍👩‍👦 ${r.family_count || 0}
        </button>
      </td>
      <td style="white-space:nowrap">
        <button class="btn btn-ghost" style="padding:2px 8px;font-size:.8rem" onclick="openEditResident('${r.id}')" title="Edit">✏️</button>
        <button class="btn btn-danger" style="padding:2px 8px;font-size:.8rem;margin-left:4px" onclick="deleteResident('${r.id}','${nameEsc}')" title="Delete">🗑️</button>
      </td>
    </tr>`;
  }).join('');
}

function filterResidents() {
  const q = document.getElementById('resident-search').value.toLowerCase();
  renderResidents(residentsCache.filter(r => {
    const f = _flatLabel(r);
    return (r.full_name || '').toLowerCase().includes(q) ||
           (r.phone     || '').toLowerCase().includes(q) ||
           String(f.floor).toLowerCase().includes(q) ||
           String(f.flatno).toLowerCase().includes(q) ||
           f.bldg.toLowerCase().includes(q);
  }));
}

// ── Add / Edit Resident Modal ──────────────────────────────────────
async function _loadBuildingsIntoSelect() {
  if (!_buildingsCache.length) {
    const res = await apiFetch('/admin/buildings');
    _buildingsCache = res.ok ? await res.json() : [];
  }
  const sel = document.getElementById('res-building');
  const cur = sel.value;
  sel.innerHTML = '<option value="">Select building...</option>' +
    _buildingsCache.map(b => `<option value="${b.id}"${b.id === cur ? ' selected' : ''}>${b.name}</option>`).join('');
}

async function onBuildingChange() {
  const buildingId = document.getElementById('res-building').value;
  const floorEl   = document.getElementById('res-floor');
  const flatnoEl  = document.getElementById('res-flatno');
  const hint      = document.getElementById('res-flat-hint');
  if (!buildingId) { hint.textContent = ''; return; }
  // Show a hint with existing flats in this building
  const res = await apiFetch(`/admin/flats?building_id=${buildingId}`);
  const flats = res.ok ? await res.json() : [];
  const bldg = _buildingsCache.find(b => b.id === buildingId);
  if (bldg) {
    hint.textContent = `${bldg.name} has ${bldg.floors} floor${bldg.floors !== 1 ? 's' : ''} · ${flats.length} flat${flats.length !== 1 ? 's' : ''} registered`;
    floorEl.max = bldg.floors;
  }
}

async function openAddResidentModal() {
  _editingResidentId = null;
  _pendingFamily     = [];
  document.getElementById('resident-modal-title').textContent = 'Add Resident';
  document.getElementById('res-name').value    = '';
  document.getElementById('res-phone').value   = '';
  document.getElementById('res-role').value    = 'resident';
  document.getElementById('res-floor').value   = '';
  document.getElementById('res-flatno').value  = '';
  document.getElementById('res-flat-hint').textContent = '';
  _buildingsCache = [];   // force refresh
  await _loadBuildingsIntoSelect();
  _renderFamilyRows();
  document.getElementById('resident-modal').classList.add('open');
}

async function openEditResident(id) {
  const r = residentsCache.find(x => x.id === id);
  if (!r) return;
  _editingResidentId = id;
  _pendingFamily     = [];
  document.getElementById('resident-modal-title').textContent = 'Edit Resident';
  document.getElementById('res-name').value  = r.full_name || '';
  document.getElementById('res-phone').value = r.phone || '';
  document.getElementById('res-role').value  = r.role || 'resident';

  const flat = r.flats;
  document.getElementById('res-floor').value  = flat?.floor  || '';
  document.getElementById('res-flatno').value = flat?.flat_number || '';
  document.getElementById('res-flat-hint').textContent = '';

  _buildingsCache = [];
  await _loadBuildingsIntoSelect();
  // Pre-select building
  if (flat?.building_id) {
    document.getElementById('res-building').value = flat.building_id;
    await onBuildingChange();
  }
  // Load existing saved family members
  await _loadSavedFamilyForModal(id);
  document.getElementById('resident-modal').classList.add('open');
}

function closeResidentModal() {
  document.getElementById('resident-modal').classList.remove('open');
  _pendingFamily = [];
}

// ── Family rows inside the modal ───────────────────────────────────
async function _loadSavedFamilyForModal(residentId) {
  const res = await apiFetch(`/admin/residents/${residentId}/family`);
  const saved = res.ok ? await res.json() : [];
  // Mark saved members with an id so they can be deleted individually
  _pendingFamily = saved.map(m => ({ _saved: true, id: m.id, full_name: m.full_name, relation: m.relation || '', phone: m.phone || '' }));
  _renderFamilyRows();
}

function _renderFamilyRows() {
  const container = document.getElementById('family-rows-container');
  const emptyMsg  = document.getElementById('family-empty-msg');
  if (!_pendingFamily.length) {
    container.innerHTML = '';
    emptyMsg.style.display = 'block';
    return;
  }
  emptyMsg.style.display = 'none';
  container.innerHTML = _pendingFamily.map((m, i) => `
    <div style="display:grid;grid-template-columns:1fr 110px 1fr auto;gap:8px;align-items:center;margin-bottom:8px">
      <input class="form-control" type="text" placeholder="Name *" value="${_esc(m.full_name)}"
        oninput="_pendingFamily[${i}].full_name=this.value" style="font-size:.875rem">
      <select class="form-control" style="font-size:.875rem" onchange="_pendingFamily[${i}].relation=this.value">
        ${['spouse','child','parent','sibling','other'].map(v =>
          `<option value="${v}"${m.relation===v?' selected':''}>${v.charAt(0).toUpperCase()+v.slice(1)}</option>`
        ).join('')}
      </select>
      <input class="form-control" type="tel" placeholder="Phone" value="${_esc(m.phone)}"
        oninput="_pendingFamily[${i}].phone=this.value" style="font-size:.875rem">
      <button class="btn btn-danger" style="padding:6px 10px;font-size:.8rem" onclick="_removeFamilyRow(${i})" title="Remove">✕</button>
    </div>`).join('');
}

function _esc(s) { return (s || '').replace(/"/g, '&quot;'); }

function addFamilyRow() {
  _pendingFamily.push({ full_name: '', relation: 'spouse', phone: '' });
  _renderFamilyRows();
  // Focus the last name input
  const inputs = document.querySelectorAll('#family-rows-container input[type=text]');
  if (inputs.length) inputs[inputs.length - 1].focus();
}

async function _removeFamilyRow(i) {
  const m = _pendingFamily[i];
  if (m._saved && m.id && _editingResidentId) {
    // Delete from DB immediately
    await apiFetch(`/admin/family/${m.id}`, { method: 'DELETE' });
  }
  _pendingFamily.splice(i, 1);
  _renderFamilyRows();
}

// ── Save resident ──────────────────────────────────────────────────
async function saveResident() {
  const name       = document.getElementById('res-name').value.trim();
  const phone      = document.getElementById('res-phone').value.trim();
  const role       = document.getElementById('res-role').value;
  const buildingId = document.getElementById('res-building').value;
  const floor      = document.getElementById('res-floor').value.trim();
  const flatno     = document.getElementById('res-flatno').value.trim();

  if (!name)       { toast('Full name is required', 'error'); return; }
  if (!buildingId) { toast('Please select a building', 'error'); return; }
  if (!floor)      { toast('Floor number is required', 'error'); return; }
  if (!flatno)     { toast('Flat number is required', 'error'); return; }

  // Validate pending family rows
  for (const m of _pendingFamily) {
    if (!m.full_name.trim()) { toast('All family member names are required', 'error'); return; }
  }

  const body = {
    full_name:   name,
    phone:       phone || null,
    role,
    building_id: buildingId,
    floor:       parseInt(floor),
    flat_number: flatno,
  };

  let res, savedId;
  if (_editingResidentId) {
    res = await apiFetch(`/admin/residents/${_editingResidentId}`, { method: 'PATCH', body: JSON.stringify(body) });
    savedId = _editingResidentId;
  } else {
    res = await apiFetch('/admin/residents', { method: 'POST', body: JSON.stringify(body) });
    if (res.ok) { const d = await res.json(); savedId = d.id; }
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    toast(err.error || 'Save failed', 'error');
    return;
  }
  if (_editingResidentId) savedId = _editingResidentId;

  // Save any new (non-saved) family members
  const newMembers = _pendingFamily.filter(m => !m._saved);
  for (const m of newMembers) {
    if (m.full_name.trim()) {
      await apiFetch(`/admin/residents/${savedId}/family`, {
        method: 'POST',
        body: JSON.stringify({ full_name: m.full_name.trim(), relation: m.relation, phone: m.phone || null }),
      });
    }
  }

  toast(_editingResidentId ? 'Resident updated' : 'Resident added', 'success');
  closeResidentModal();
  loadResidents();
}

async function deleteResident(id, name) {
  if (!confirm(`Delete ${name}?\n\nThis will permanently remove their profile.`)) return;
  const res = await apiFetch(`/admin/residents/${id}`, { method: 'DELETE' });
  if (res.ok) { toast('Resident deleted', 'success'); loadResidents(); }
  else toast('Failed to delete', 'error');
}

// ── Family Modal (from table row ─ view & manage) ──────────────────
async function openFamilyModal(residentId, name) {
  _familyModalResidentId = residentId;
  document.getElementById('family-modal-title').textContent = `Family — ${name}`;
  document.getElementById('fm-name').value  = '';
  document.getElementById('fm-phone').value = '';
  await _loadFamilyModalList();
  document.getElementById('family-modal').classList.add('open');
}

async function _loadFamilyModalList() {
  const res = await apiFetch(`/admin/residents/${_familyModalResidentId}/family`);
  const members = res.ok ? await res.json() : [];
  const list = document.getElementById('family-modal-list');
  if (!members.length) {
    list.innerHTML = '<p style="color:var(--muted);font-size:.85rem;padding:8px 0">No family members yet.</p>';
    return;
  }
  list.innerHTML = members.map(m => `
    <div style="display:flex;align-items:center;gap:10px;padding:10px 0;border-bottom:1px solid var(--border)">
      <div style="flex:1">
        <strong>${m.full_name}</strong>
        <span class="badge badge-muted" style="margin-left:6px">${m.relation || 'Member'}</span>
        ${m.phone ? `<div style="font-size:.8rem;color:var(--muted)">📞 ${m.phone}</div>` : ''}
      </div>
      <button class="btn btn-danger" style="padding:3px 10px;font-size:.8rem" onclick="_removeFamilyFromModal('${m.id}')">Remove</button>
    </div>`).join('');
}

async function addFamilyFromModal() {
  const name     = document.getElementById('fm-name').value.trim();
  const relation = document.getElementById('fm-relation').value;
  const phone    = document.getElementById('fm-phone').value.trim();
  if (!name) { toast('Name is required', 'error'); return; }
  const res = await apiFetch(`/admin/residents/${_familyModalResidentId}/family`, {
    method: 'POST',
    body: JSON.stringify({ full_name: name, relation, phone: phone || null }),
  });
  if (res.ok) {
    toast('Added', 'success');
    document.getElementById('fm-name').value  = '';
    document.getElementById('fm-phone').value = '';
    await _loadFamilyModalList();
    loadResidents();
  } else {
    const err = await res.json().catch(() => ({}));
    toast(err.error || 'Failed', 'error');
  }
}

async function _removeFamilyFromModal(memberId) {
  const res = await apiFetch(`/admin/family/${memberId}`, { method: 'DELETE' });
  if (res.ok) { await _loadFamilyModalList(); loadResidents(); }
  else toast('Failed', 'error');
}

function closeFamilyModal() {
  document.getElementById('family-modal').classList.remove('open');
}

// ── Vehicles ──────────────────────────────────────────────────────────────
async function loadVehicles() {
  const [vRes, sRes] = await Promise.all([
    apiFetch('/vehicles/'),
    apiFetch('/vehicles/parking-slots'),
  ]);
  const vehicles = vRes.ok ? await vRes.json() : [];
  const slots    = sRes.ok ? await sRes.json() : [];

  document.getElementById('vehicles-table').innerHTML = vehicles.map(v => `
    <tr>
      <td><strong style="letter-spacing:1px">${v.number_plate}</strong></td>
      <td>${v.vehicle_type}</td>
      <td>${v.flats?.flat_number || '—'}</td>
      <td>${statusBadge(v.status)}</td>
    </tr>`).join('') || '<tr><td colspan="4" style="text-align:center;color:var(--muted)">No vehicles</td></tr>';

  document.getElementById('parking-slots-list').innerHTML = slots.map(s =>
    `<span class="badge badge-info" style="margin:2px">${s.slot_name} (${s.type})${s.flats ? ' → ' + s.flats.flat_number : ''}</span>`
  ).join('') || '<p style="color:var(--muted)">No slots configured</p>';

  loadVehicleEntryLogs();
}

async function loadVehicleEntryLogs() {
  const res  = await apiFetch('/vehicles/entries');
  const data = res.ok ? await res.json() : [];
  document.getElementById('vehicle-logs-table').innerHTML = data.map(e => `
    <tr>
      <td><strong style="letter-spacing:1px">${e.number_plate}</strong></td>
      <td>${e.vehicles?.flats?.flat_number || (e.is_visitor_vehicle ? '—Visitor—' : '—')}</td>
      <td>${e.is_visitor_vehicle ? '<span class="badge">Visitor</span>' : '<span class="badge badge-success">Resident</span>'}</td>
      <td>${fmtDate(e.entry_time)}</td>
      <td>${e.exit_time ? fmtDate(e.exit_time) : '<span style="color:var(--warning)">Inside</span>'}</td>
      <td>${e.exit_time ? statusBadge('exited') : statusBadge('active')}</td>
    </tr>`).join('') || '<tr><td colspan="6" style="text-align:center;color:var(--muted)">No entries today</td></tr>';
}

async function addParkingSlot() {
  const name = document.getElementById('new-slot-name').value.trim();
  const type = document.getElementById('new-slot-type').value;
  if (!name) return toast('Slot name required', 'error');
  const res = await apiFetch('/vehicles/parking-slots', { method: 'POST', body: JSON.stringify({ slot_name: name, type }) });
  if (res.ok) { toast('Slot added', 'success'); loadVehicles(); }
}

// ── Staff ─────────────────────────────────────────────────────────────────
async function loadStaff() {
  const res = await apiFetch('/staff/');
  const data = res.ok ? await res.json() : [];
  document.getElementById('staff-table').innerHTML = data.map(s => `
    <tr>
      <td>${s.name}</td><td>${s.role}</td><td>${s.shift || '—'}</td>
      <td>${s.phone || '—'}</td><td>₹${s.monthly_salary || 0}</td>
    </tr>`).join('');
}

async function addStaff() {
  const body = {
    name:           document.getElementById('s-name').value.trim(),
    phone:          document.getElementById('s-phone').value.trim(),
    role:           document.getElementById('s-role').value,
    shift:          document.getElementById('s-shift').value,
    monthly_salary: parseFloat(document.getElementById('s-salary').value) || 0,
  };
  if (!body.name) return toast('Name required', 'error');
  const res = await apiFetch('/staff/', { method: 'POST', body: JSON.stringify(body) });
  if (res.ok) { closeModal('modal-add-staff'); toast('Staff added', 'success'); loadStaff(); }
  else toast('Failed', 'error');
}

// ── Billing ───────────────────────────────────────────────────────────────
async function loadBilling() {
  const [finRes, headsRes, invRes] = await Promise.all([
    apiFetch('/reports/financial'),
    apiFetch('/billing/heads'),
    apiFetch('/billing/invoices'),
  ]);
  const fin   = finRes.ok   ? await finRes.json()   : {};
  const heads = headsRes.ok ? await headsRes.json() : [];
  const invs  = invRes.ok   ? await invRes.json()   : [];

  document.getElementById('billing-summary').innerHTML = `
    <div class="card-header">Financial Summary</div>
    <div class="stats-grid" style="grid-template-columns:1fr 1fr">
      <div class="stat-card"><div class="stat-val" style="color:var(--success)">₹${fin.total_collected || 0}</div><div class="stat-lbl">Collected</div></div>
      <div class="stat-card"><div class="stat-val" style="color:var(--danger)">₹${fin.total_dues || 0}</div><div class="stat-lbl">Dues</div></div>
      <div class="stat-card"><div class="stat-val" style="color:var(--warning)">₹${fin.total_expenses || 0}</div><div class="stat-lbl">Expenses</div></div>
      <div class="stat-card"><div class="stat-val" style="color:var(--primary)">₹${fin.net_balance || 0}</div><div class="stat-lbl">Net Balance</div></div>
    </div>`;

  document.getElementById('billing-heads-list').innerHTML = heads.map(h =>
    `<div style="padding:6px 0;border-bottom:1px solid var(--border);font-size:.9rem">
      ${h.name} — ₹${h.amount || 0} · ${h.frequency}
    </div>`).join('') || '<p style="color:var(--muted)">No billing heads</p>';

  document.getElementById('invoices-table').innerHTML = invs.map(i => `
    <tr>
      <td>${i.invoice_number || '—'}</td>
      <td>${i.flats?.flat_number || '—'}</td>
      <td>₹${i.total_amount}</td>
      <td>${i.due_date || '—'}</td>
      <td>${statusBadge(i.status)}</td>
    </tr>`).join('');
}

async function addBillingHead() {
  const body = {
    name:              document.getElementById('bh-name').value.trim(),
    amount:            parseFloat(document.getElementById('bh-amount').value) || 0,
    frequency:         document.getElementById('bh-freq').value,
    is_gst_applicable: document.getElementById('bh-gst').checked,
    gst_percent:       parseFloat(document.getElementById('bh-gst-pct').value) || 0,
  };
  if (!body.name) return toast('Name required', 'error');
  const res = await apiFetch('/billing/heads', { method: 'POST', body: JSON.stringify(body) });
  if (res.ok) { closeModal('modal-add-billing-head'); toast('Billing head saved', 'success'); loadBilling(); }
}

// ── Helpdesk ──────────────────────────────────────────────────────────────
async function loadTickets() {
  const status = document.getElementById('ticket-status-filter')?.value || '';
  const cat    = document.getElementById('ticket-cat-filter')?.value || '';
  let url = '/helpdesk/?';
  if (status) url += `status=${status}&`;
  if (cat)    url += `category=${cat}&`;
  const res = await apiFetch(url);
  const data = res.ok ? await res.json() : [];
  document.getElementById('tickets-table').innerHTML = data.map(t => `
    <tr>
      <td>${t.title}</td>
      <td>${t.flats?.flat_number || '—'}</td>
      <td>${t.category}</td>
      <td>${statusBadge(t.priority)}</td>
      <td>${statusBadge(t.status)}</td>
      <td>${fmtDate(t.created_at)}</td>
      <td>
        <select onchange="updateTicketStatus('${t.id}',this.value)" style="padding:4px 8px;border:1px solid var(--border);border-radius:6px;font-size:.8rem">
          <option value="">Update</option>
          <option value="in_progress">In Progress</option>
          <option value="resolved">Resolved</option>
          <option value="closed">Close</option>
        </select>
      </td>
    </tr>`).join('');
}

async function updateTicketStatus(id, status) {
  if (!status) return;
  await apiFetch(`/helpdesk/${id}`, { method: 'PATCH', body: JSON.stringify({ status }) });
  toast('Ticket updated', 'success');
  loadTickets();
}

// ── Amenities ─────────────────────────────────────────────────────────────
async function loadAmenities() {
  const res = await apiFetch('/amenities/');
  const data = res.ok ? await res.json() : [];
  document.getElementById('amenities-grid').innerHTML = data.map(a => `
    <div class="card">
      <div class="card-header">${a.name}</div>
      <div style="font-size:.875rem;color:var(--muted)">${a.description || ''}</div>
      <div style="margin-top:8px;font-size:.85rem">
        👥 Capacity: ${a.capacity || '—'} &nbsp; 💰 ₹${a.charge_per_slot}/slot
      </div>
    </div>`).join('') || '<p style="color:var(--muted)">No amenities configured</p>';
}

async function addAmenity() {
  const body = {
    name:                document.getElementById('am-name').value.trim(),
    capacity:            parseInt(document.getElementById('am-cap').value) || null,
    charge_per_slot:     parseFloat(document.getElementById('am-charge').value) || 0,
    advance_booking_days: parseInt(document.getElementById('am-adv').value) || 7,
  };
  if (!body.name) return toast('Name required', 'error');
  const res = await apiFetch('/amenities/', { method: 'POST', body: JSON.stringify(body) });
  if (res.ok) { closeModal('modal-add-amenity'); toast('Amenity created', 'success'); loadAmenities(); }
}

// ── Community ─────────────────────────────────────────────────────────────
async function postNotice() {
  const body = {
    title:    document.getElementById('notice-title').value.trim(),
    body:     document.getElementById('notice-body').value.trim(),
    is_pinned: document.getElementById('notice-pinned').checked,
  };
  if (!body.title) return toast('Title required', 'error');
  const res = await apiFetch('/community/notices', { method: 'POST', body: JSON.stringify(body) });
  if (res.ok) { toast('Notice posted!', 'success'); document.getElementById('notice-title').value = ''; document.getElementById('notice-body').value = ''; }
  else toast('Failed', 'error');
}

async function sendBroadcast() {
  const body = {
    title:   document.getElementById('broadcast-title').value.trim(),
    message: document.getElementById('broadcast-msg').value.trim(),
  };
  if (!body.title || !body.message) return toast('Title and message required', 'error');
  if (!confirm(`Send emergency broadcast: "${body.title}"?`)) return;
  const res = await apiFetch('/security-alerts/broadcast', { method: 'POST', body: JSON.stringify(body) });
  if (res.ok) { toast('🚨 Broadcast sent!', 'success'); document.getElementById('broadcast-title').value = ''; document.getElementById('broadcast-msg').value = ''; }
  else toast('Failed', 'error');
}

// ── Alerts ────────────────────────────────────────────────────────────────
async function loadAlerts() {
  const status = document.getElementById('alert-status-filter')?.value || '';
  const url = status ? `/security-alerts/?status=${status}` : '/security-alerts/';
  const res  = await apiFetch(url);
  const data = res.ok ? await res.json() : [];
  document.getElementById('alerts-table').innerHTML = data.map(a => `
    <tr>
      <td>${a.alert_type}</td>
      <td>${a.flats?.flat_number || '—'}</td>
      <td>${a.user_profiles?.full_name || '—'}</td>
      <td>${statusBadge(a.alert_status)}</td>
      <td>${fmtDate(a.created_at)}</td>
      <td>${a.acknowledged_at ? fmtDate(a.acknowledged_at) : '—'}</td>
    </tr>`).join('');
}

// ── Reports ───────────────────────────────────────────────────────────────
async function loadReport(type) {
  const res  = await apiFetch(`/reports/${type}`);
  const data = res.ok ? await res.json() : [];
  if (!data.length) {
    document.getElementById('report-content').innerHTML = '<p style="color:var(--muted);padding:20px;text-align:center">No data available</p>';
    return;
  }
  const keys = Object.keys(data[0]);
  document.getElementById('report-content').innerHTML = `
    <div class="card">
      <div style="margin-bottom:10px;display:flex;justify-content:space-between">
        <strong>${type.replace(/-/g,' ').replace(/\b\w/g,c=>c.toUpperCase())} Report (${data.length} records)</strong>
        <button class="btn btn-ghost" style="padding:4px 12px" onclick="exportCSV(window._reportData,'${type}')">⬇ CSV</button>
      </div>
      <div class="table-wrap"><table>
        <thead><tr>${keys.map(k=>`<th>${k}</th>`).join('')}</tr></thead>
        <tbody>${data.slice(0,100).map(row=>`<tr>${keys.map(k=>`<td>${row[k]??'—'}</td>`).join('')}</tr>`).join('')}</tbody>
      </table></div>
    </div>`;
  window._reportData = data;
}

async function loadFinancialReport() {
  const res  = await apiFetch('/reports/financial');
  const data = res.ok ? await res.json() : {};
  document.getElementById('report-content').innerHTML = `
    <div class="stats-grid" style="max-width:600px">
      <div class="stat-card"><div class="stat-val" style="color:var(--primary)">₹${data.total_invoiced||0}</div><div class="stat-lbl">Total Invoiced</div></div>
      <div class="stat-card"><div class="stat-val" style="color:var(--success)">₹${data.total_collected||0}</div><div class="stat-lbl">Collected</div></div>
      <div class="stat-card"><div class="stat-val" style="color:var(--danger)">₹${data.total_dues||0}</div><div class="stat-lbl">Dues</div></div>
      <div class="stat-card"><div class="stat-val" style="color:var(--warning)">₹${data.total_expenses||0}</div><div class="stat-lbl">Expenses</div></div>
      <div class="stat-card"><div class="stat-val">₹${data.net_balance||0}</div><div class="stat-lbl">Net Balance</div></div>
    </div>`;
}

function exportCSV(data, name) {
  if (!data?.length) return toast('No data to export', 'error');
  const keys = Object.keys(data[0]);
  const csv  = [keys.join(','), ...data.map(r => keys.map(k => JSON.stringify(r[k]??'')).join(','))].join('\n');
  const a    = document.createElement('a');
  a.href     = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
  a.download = `${name}-${new Date().toISOString().slice(0,10)}.csv`;
  a.click();
}
