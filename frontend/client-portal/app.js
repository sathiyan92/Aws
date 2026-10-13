/**
 * Apex Client Tenant Portal - Frontend Application
 * Dynamic Feature Visibility & Server-Side Security Verification
 */

function getClientApiBase() {
    if (window.location.protocol === 'file:') {
        return "http://localhost:8000/api/v1";
    }
    const host = window.location.hostname || "localhost";
    const port = window.location.port;
    if (port === "8000" || window.location.pathname.startsWith("/client-portal")) {
        return "/api/v1";
    }
    return `http://${host}:8000/api/v1`;
}

const API_BASE = getClientApiBase();


// Application State
const state = {
    token: localStorage.getItem('iot_client_token') || null,
    user: JSON.parse(localStorage.getItem('iot_client_user') || 'null'),
    fleet: [],
    selectedDeviceId: null,
    currentTab: 'tab-fleet',
};

// DOM Elements
const elements = {
    loginModal: document.getElementById('loginModal'),
    loginForm: document.getElementById('loginForm'),
    loginUsername: document.getElementById('loginUsername'),
    loginPassword: document.getElementById('loginPassword'),
    demoApexBtn: document.getElementById('demoApexBtn'),
    demoMetroBtn: document.getElementById('demoMetroBtn'),
    logoutBtn: document.getElementById('logoutBtn'),

    clientBrandTitle: document.getElementById('clientBrandTitle'),
    tenantSubTitle: document.getElementById('tenantSubTitle'),
    tenantNameHeader: document.getElementById('tenantNameHeader'),
    tenantIdHeader: document.getElementById('tenantIdHeader'),
    userNameLabel: document.getElementById('userNameLabel'),
    userRoleLabel: document.getElementById('userRoleLabel'),
    userAvatar: document.getElementById('userAvatar'),

    deviceSelect: document.getElementById('deviceSelect'),
    deviceTypeBadge: document.getElementById('deviceTypeBadge'),
    refreshCapabilitiesBtn: document.getElementById('refreshCapabilitiesBtn'),
    activeModulesList: document.getElementById('activeModulesList'),

    navFleet: document.getElementById('navFleet'),
    navQR: document.getElementById('navQR'),
    navCoin: document.getElementById('navCoin'),
    navRFID: document.getElementById('navRFID'),
    navSecurity: document.getElementById('navSecurity'),

    fleetTableBody: document.getElementById('fleetTableBody'),
    fleetCountBadge: document.getElementById('fleetCountBadge'),

    qrSettingsForm: document.getElementById('qrSettingsForm'),
    qrVpa: document.getElementById('qrVpa'),
    qrMerchantName: document.getElementById('qrMerchantName'),
    qrCurrency: document.getElementById('qrCurrency'),
    qrTimeout: document.getElementById('qrTimeout'),
    qrTransactionsBody: document.getElementById('qrTransactionsBody'),

    coinSettingsForm: document.getElementById('coinSettingsForm'),
    coinPulseRatio: document.getElementById('coinPulseRatio'),
    coinCurrency: document.getElementById('coinCurrency'),
    coinMinPulse: document.getElementById('coinMinPulse'),
    coinAcceptedDenoms: document.getElementById('coinAcceptedDenoms'),
    coinTransactionsBody: document.getElementById('coinTransactionsBody'),

    rfidCardsBody: document.getElementById('rfidCardsBody'),
    rfidLogsBody: document.getElementById('rfidLogsBody'),
    addCardBtn: document.getElementById('addCardBtn'),
    addCardModal: document.getElementById('addCardModal'),
    closeAddCardModalBtn: document.getElementById('closeAddCardModalBtn'),
    addCardForm: document.getElementById('addCardForm'),
    newCardUid: document.getElementById('newCardUid'),
    newCardholderName: document.getElementById('newCardholderName'),
    newCardDept: document.getElementById('newCardDept'),

    forgedModuleSelect: document.getElementById('forgedModuleSelect'),
    forgedDeviceSelect: document.getElementById('forgedDeviceSelect'),
    simulateAttackBtn: document.getElementById('simulateAttackBtn'),
    securityTestResult: document.getElementById('securityTestResult'),
    securityResultIcon: document.getElementById('securityResultIcon'),
    securityResultTitle: document.getElementById('securityResultTitle'),
    securityResultDesc: document.getElementById('securityResultDesc'),
    securityResultJson: document.getElementById('securityResultJson'),

    toastContainer: document.getElementById('toastContainer'),
};

// ==============================================================================
// INITIALIZATION & AUTHENTICATION
// ==============================================================================

async function init() {
    setupEventListeners();

    if (!state.token) {
        showLoginModal();
    } else {
        updateUserInfo();
        await loadFleetCapabilities();
    }
}

function setupEventListeners() {
    // Navigation items
    document.querySelectorAll('.nav-item').forEach(item => {
        item.addEventListener('click', () => {
            const targetTab = item.dataset.tab;
            if (targetTab) {
                switchTab(targetTab);
            }
        });
    });

    // Device selector change
    elements.deviceSelect.addEventListener('change', (e) => {
        state.selectedDeviceId = e.target.value;
        onDeviceSelectionChanged();
    });

    // Refresh Fleet button
    elements.refreshCapabilitiesBtn.addEventListener('click', async () => {
        showToast('Refreshing fleet capabilities...');
        await loadFleetCapabilities();
    });

    // Login handling
    elements.loginForm.addEventListener('submit', handleLogin);
    elements.logoutBtn.addEventListener('click', handleLogout);

    // Quick demo buttons
    elements.demoApexBtn.addEventListener('click', () => {
        elements.loginUsername.value = 'apex_admin';
        elements.loginPassword.value = 'Apex@Admin2026!';
        elements.loginForm.dispatchEvent(new Event('submit'));
    });

    elements.demoMetroBtn.addEventListener('click', () => {
        elements.loginUsername.value = 'metro_admin';
        elements.loginPassword.value = 'Metro@Retail2026!';
        elements.loginForm.dispatchEvent(new Event('submit'));
    });

    // Form submissions
    elements.qrSettingsForm.addEventListener('submit', handleSaveQRSettings);
    elements.coinSettingsForm.addEventListener('submit', handleSaveCoinSettings);

    // RFID Modal
    elements.addCardBtn.addEventListener('click', () => {
        elements.addCardModal.classList.add('open');
    });
    elements.closeAddCardModalBtn.addEventListener('click', () => {
        elements.addCardModal.classList.remove('open');
    });
    elements.addCardForm.addEventListener('submit', handleAddRFIDCard);

    // Reset buttons
    document.getElementById('resetQrBtn')?.addEventListener('click', () => {
        if (state.selectedDeviceId) loadQRData(state.selectedDeviceId);
    });
    document.getElementById('resetCoinBtn')?.addEventListener('click', () => {
        if (state.selectedDeviceId) loadCoinData(state.selectedDeviceId);
    });

    // Security Verification Test Button
    elements.simulateAttackBtn.addEventListener('click', handleSimulateSecurityAttack);
}

function showLoginModal() {
    elements.loginModal.classList.add('open');
}

function hideLoginModal() {
    elements.loginModal.classList.remove('open');
}

async function handleLogin(e) {
    e.preventDefault();
    const username = elements.loginUsername.value.trim();
    const password = elements.loginPassword.value.trim();

    try {
        const res = await fetch(`${API_BASE}/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                username_or_email: username,
                password: password,
            }),
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Invalid login credentials.');
        }

        const data = await res.json();
        state.token = data.access_token;
        state.user = {
            id: data.user.id,
            username: data.user.username,
            role: data.user.role,
            tenant_id: data.user.client_id,
        };

        localStorage.setItem('iot_client_token', state.token);
        localStorage.setItem('iot_client_user', JSON.stringify(state.user));

        hideLoginModal();
        updateUserInfo();
        showToast(`Welcome back, ${data.user.username}!`);
        await loadFleetCapabilities();
    } catch (err) {
        showToast(err.message, 'error');
    }
}

function handleLogout() {
    state.token = null;
    state.user = null;
    state.fleet = [];
    state.selectedDeviceId = null;
    localStorage.removeItem('iot_client_token');
    localStorage.removeItem('iot_client_user');
    showLoginModal();
    showToast('Signed out successfully.');
}

function updateUserInfo() {
    if (!state.user) return;
    elements.userNameLabel.textContent = state.user.username;
    elements.userRoleLabel.textContent = state.user.role;
    elements.userAvatar.textContent = state.user.username.charAt(0).toUpperCase();
}

// ==============================================================================
// FLEET DISCOVERY & CAPABILITIES
// ==============================================================================

async function loadFleetCapabilities() {
    try {
        const res = await fetchWithAuth(`${API_BASE}/vending/fleet-capabilities`);
        if (!res.ok) throw new Error('Failed to load fleet capabilities');

        const fleet = await res.json();
        state.fleet = fleet;

        renderFleetTable(fleet);
        populateDeviceDropdown(fleet);

        if (fleet.length > 0) {
            if (!state.selectedDeviceId || !fleet.find(d => d.device_id === state.selectedDeviceId)) {
                state.selectedDeviceId = fleet[0].device_id;
            }
            elements.deviceSelect.value = state.selectedDeviceId;
            onDeviceSelectionChanged();
        } else {
            showToast('No devices assigned to this client tenant.', 'warning');
        }
    } catch (err) {
        showToast(err.message, 'error');
    }
}

function populateDeviceDropdown(fleet) {
    elements.deviceSelect.innerHTML = '';
    elements.forgedDeviceSelect.innerHTML = '';

    fleet.forEach(device => {
        // Main dropdown
        const opt = document.createElement('option');
        opt.value = device.device_id;
        opt.textContent = `${device.device_id} [${device.product_type}]`;
        elements.deviceSelect.appendChild(opt);

        // Security test dropdown
        const optTest = document.createElement('option');
        optTest.value = device.device_id;
        const modSummary = Object.keys(device.modules || {}).filter(m => device.modules[m]).join(', ') || 'No Modules';
        optTest.textContent = `${device.device_id} (${modSummary})`;
        elements.forgedDeviceSelect.appendChild(optTest);
    });
}

function renderFleetTable(fleet) {
    elements.fleetCountBadge.textContent = `${fleet.length} Assigned Devices`;
    elements.fleetTableBody.innerHTML = '';

    if (fleet.length === 0) {
        elements.fleetTableBody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-muted);">No devices provisioned for this tenant.</td></tr>`;
        return;
    }

    fleet.forEach(dev => {
        const tr = document.createElement('tr');
        
        // Active modules badges
        let moduleBadges = '';
        if (dev.has_qr_payment) moduleBadges += `<span class="badge badge-on" style="margin-right: 4px;">QR</span>`;
        if (dev.has_coin_payment) moduleBadges += `<span class="badge badge-on" style="margin-right: 4px;">COIN</span>`;
        if (dev.has_rfid_access) moduleBadges += `<span class="badge badge-on" style="margin-right: 4px;">RFID</span>`;
        if (!moduleBadges) moduleBadges = `<span class="badge badge-off">None</span>`;

        tr.innerHTML = `
            <td><strong class="mono-text" style="color: var(--primary);">${dev.device_id}</strong></td>
            <td>Hardware Unit ${dev.device_id.replace(/^[A-Z]+-0*/, '#')}</td>
            <td><span class="badge ${dev.product_type === 'VENDING_MACHINE' ? 'badge-on' : 'badge-off'}">${dev.product_type}</span></td>
            <td><span class="badge ${dev.is_online ? 'badge-on' : 'badge-off'}">${dev.is_online ? 'ONLINE' : 'OFFLINE'}</span></td>
            <td>${moduleBadges}</td>
            <td><span class="mono-text">v${dev.config_version}</span></td>
            <td>
                <button class="btn btn-secondary select-fleet-btn" data-device-id="${dev.device_id}" style="padding: 0.3rem 0.6rem; font-size: 0.72rem;">
                    Manage &rarr;
                </button>
            </td>
        `;
        elements.fleetTableBody.appendChild(tr);
    });

    document.querySelectorAll('.select-fleet-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const devId = btn.dataset.deviceId;
            elements.deviceSelect.value = devId;
            state.selectedDeviceId = devId;
            onDeviceSelectionChanged();
            showToast(`Switched active context to ${devId}`);
        });
    });
}

// ==============================================================================
// DYNAMIC FEATURE VISIBILITY ENGINE
// ==============================================================================

function onDeviceSelectionChanged() {
    const currentDevice = state.fleet.find(d => d.device_id === state.selectedDeviceId);
    if (!currentDevice) return;

    // Update labels in panels
    document.querySelectorAll('.selected-device-label').forEach(el => {
        el.textContent = currentDevice.device_id;
    });

    elements.deviceTypeBadge.style.display = 'inline-flex';
    elements.deviceTypeBadge.textContent = currentDevice.product_type;

    // 1. DYNAMIC TOGGLING OF QR MODULE
    if (currentDevice.has_qr_payment) {
        elements.navQR.classList.remove('dynamic-hidden');
    } else {
        elements.navQR.classList.add('dynamic-hidden');
    }

    // 2. DYNAMIC TOGGLING OF COIN MODULE
    if (currentDevice.has_coin_payment) {
        elements.navCoin.classList.remove('dynamic-hidden');
    } else {
        elements.navCoin.classList.add('dynamic-hidden');
    }

    // 3. DYNAMIC TOGGLING OF RFID MODULE
    if (currentDevice.has_rfid_access) {
        elements.navRFID.classList.remove('dynamic-hidden');
    } else {
        elements.navRFID.classList.add('dynamic-hidden');
    }

    // Update capability banner
    updateCapabilityBanner(currentDevice);

    // 4. GUARD ACTIVE TAB: If the active tab was just hidden, redirect gracefully to tab-fleet
    if (state.currentTab === 'tab-qr' && !currentDevice.has_qr_payment) {
        switchTab('tab-fleet');
        showToast(`QR module is not enabled for ${currentDevice.device_id}. Switched to Overview.`, 'warning');
    } else if (state.currentTab === 'tab-coin' && !currentDevice.has_coin_payment) {
        switchTab('tab-fleet');
        showToast(`Coin Acceptor is not enabled for ${currentDevice.device_id}. Switched to Overview.`, 'warning');
    } else if (state.currentTab === 'tab-rfid' && !currentDevice.has_rfid_access) {
        switchTab('tab-fleet');
        showToast(`RFID module is not enabled for ${currentDevice.device_id}. Switched to Overview.`, 'warning');
    } else {
        // Reload current active tab's data
        loadActiveTabData();
    }
}

function updateCapabilityBanner(device) {
    elements.activeModulesList.innerHTML = '';

    const modules = [
        { code: 'QR_PAYMENT', name: 'QR UPI Gateway', enabled: device.has_qr_payment },
        { code: 'COIN_PAYMENT', name: 'Coin Acceptor', enabled: device.has_coin_payment },
        { code: 'RFID_ACCESS', name: 'RFID Attendance', enabled: device.has_rfid_access },
    ];

    modules.forEach(m => {
        const span = document.createElement('span');
        span.className = `badge ${m.enabled ? 'badge-on' : 'badge-off'}`;
        span.textContent = `${m.name}: ${m.enabled ? 'ACTIVE' : 'DISABLED'}`;
        elements.activeModulesList.appendChild(span);
    });
}

function switchTab(tabId) {
    state.currentTab = tabId;

    // Toggle active nav item
    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.toggle('active', item.dataset.tab === tabId);
    });

    // Toggle tab panes
    document.querySelectorAll('.tab-pane').forEach(pane => {
        pane.classList.toggle('active', pane.id === tabId);
    });

    loadActiveTabData();
}

function loadActiveTabData() {
    if (!state.selectedDeviceId) return;

    if (state.currentTab === 'tab-qr') {
        loadQRData(state.selectedDeviceId);
    } else if (state.currentTab === 'tab-coin') {
        loadCoinData(state.selectedDeviceId);
    } else if (state.currentTab === 'tab-rfid') {
        loadRFIDData(state.selectedDeviceId);
    }
}

// ==============================================================================
// MODULE DATA LOADERS & ACTIONS
// ==============================================================================

// QR MODULE
async function loadQRData(deviceId) {
    try {
        const res = await fetchWithAuth(`${API_BASE}/vending/${deviceId}/qr/settings`);
        if (res.ok) {
            const data = await res.json();
            elements.qrVpa.value = data.upi_merchant_vpa || '';
            elements.qrTimeout.value = data.qr_timeout_seconds || 120;
            elements.qrMerchantName.value = 'Apex Vending Solutions';
        }

        const txRes = await fetchWithAuth(`${API_BASE}/vending/${deviceId}/qr/transactions`);
        if (txRes.ok) {
            const txs = await txRes.json();
            renderQRTransactions(txs);
        }
    } catch (err) {
        showToast(err.message, 'error');
    }
}

function renderQRTransactions(txs) {
    elements.qrTransactionsBody.innerHTML = '';
    if (!txs || txs.length === 0) {
        elements.qrTransactionsBody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--text-muted);">No recent digital QR transactions recorded.</td></tr>`;
        return;
    }

    txs.forEach(t => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><span class="mono-text">${t.transaction_number || t.id.slice(0, 8)}</span></td>
            <td>${new Date(t.transacted_at).toLocaleTimeString()}</td>
            <td>Slot #3</td>
            <td><strong style="color: var(--primary);">₹${t.amount_in_rupees.toFixed(2)}</strong></td>
            <td><span class="badge badge-on">UPI</span></td>
            <td><span class="badge badge-on">${t.dispense_status}</span></td>
        `;
        elements.qrTransactionsBody.appendChild(tr);
    });
}

async function handleSaveQRSettings(e) {
    e.preventDefault();
    if (!state.selectedDeviceId) return;

    try {
        const payload = {
            upi_merchant_vpa: elements.qrVpa.value.trim(),
            qr_timeout_seconds: parseInt(elements.qrTimeout.value),
            dynamic_pricing_enabled: true,
        };

        const res = await fetchWithAuth(`${API_BASE}/vending/${state.selectedDeviceId}/qr/settings`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Failed to update QR settings');
        }

        showToast(`QR payment parameters updated for ${state.selectedDeviceId}!`);
        await loadFleetCapabilities();
    } catch (err) {
        showToast(err.message, 'error');
    }
}

// COIN MODULE
async function loadCoinData(deviceId) {
    try {
        const res = await fetchWithAuth(`${API_BASE}/vending/${deviceId}/coins/settings`);
        if (res.ok) {
            const data = await res.json();
            elements.coinMinPulse.value = data.debounce_ms || 50;
        }

        const txRes = await fetchWithAuth(`${API_BASE}/vending/${deviceId}/coins/transactions`);
        if (txRes.ok) {
            const txs = await txRes.json();
            renderCoinTransactions(txs);
        }
    } catch (err) {
        showToast(err.message, 'error');
    }
}

function renderCoinTransactions(txs) {
    elements.coinTransactionsBody.innerHTML = '';
    if (!txs || txs.length === 0) {
        elements.coinTransactionsBody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--text-muted);">No mechanical coin events logged.</td></tr>`;
        return;
    }

    txs.forEach(t => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><span class="mono-text">${t.transaction_number || t.id.slice(0, 8)}</span></td>
            <td>${new Date(t.transacted_at).toLocaleTimeString()}</td>
            <td><strong style="color: var(--warning);">₹${t.amount_in_rupees.toFixed(2)}</strong></td>
            <td>${t.coins_inserted || 1} pulse(s)</td>
            <td>Vault OK</td>
        `;
        elements.coinTransactionsBody.appendChild(tr);
    });
}

async function handleSaveCoinSettings(e) {
    e.preventDefault();
    if (!state.selectedDeviceId) return;

    try {
        const payload = {
            debounce_ms: parseInt(elements.coinMinPulse.value),
            change_dispenser_fitted: false,
        };

        const res = await fetchWithAuth(`${API_BASE}/vending/${state.selectedDeviceId}/coins/settings`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Failed to update Coin settings');
        }

        showToast(`Coin calibration saved for ${state.selectedDeviceId}!`);
        await loadFleetCapabilities();
    } catch (err) {
        showToast(err.message, 'error');
    }
}

// RFID MODULE
async function loadRFIDData(deviceId) {
    try {
        const cardsRes = await fetchWithAuth(`${API_BASE}/rfid/${deviceId}/cards`);
        if (cardsRes.ok) {
            const cards = await cardsRes.json();
            renderRFIDCards(cards);
        }

        const eventsRes = await fetchWithAuth(`${API_BASE}/rfid/${deviceId}/attendance`);
        if (eventsRes.ok) {
            const events = await eventsRes.json();
            renderRFIDLogs(events);
        }
    } catch (err) {
        showToast(err.message, 'error');
    }
}

function renderRFIDCards(cards) {
    elements.rfidCardsBody.innerHTML = '';
    if (!cards || cards.length === 0) {
        elements.rfidCardsBody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--text-muted);">No authorized RFID cards enrolled yet.</td></tr>`;
        return;
    }

    cards.forEach(c => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><strong class="mono-text" style="color: var(--cyan);">${c.card_uid}</strong></td>
            <td>${c.employee_name || 'Unassigned'}</td>
            <td>${c.employee_code || '-'}</td>
            <td><span class="badge ${c.status === 'ACTIVE' ? 'badge-on' : 'badge-off'}">${c.status}</span></td>
            <td>Active</td>
            <td>
                <span class="badge badge-on" style="font-size: 0.65rem;">Authorized</span>
            </td>
        `;
        elements.rfidCardsBody.appendChild(tr);
    });
}

function renderRFIDLogs(events) {
    elements.rfidLogsBody.innerHTML = '';
    if (!events || events.length === 0) {
        elements.rfidLogsBody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--text-muted);">No attendance check-in swipes logged yet.</td></tr>`;
        return;
    }

    events.forEach(e => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><span class="mono-text">${e.id.slice(0, 8)}</span></td>
            <td>${new Date(e.timestamp).toLocaleTimeString()}</td>
            <td><span class="mono-text">${e.card_uid_scanned}</span></td>
            <td>${e.employee_name || 'Cardholder'}</td>
            <td><span class="badge badge-on">${e.event_type}</span></td>
            <td><strong style="color: var(--primary);">&check; GRANTED</strong></td>
        `;
        elements.rfidLogsBody.appendChild(tr);
    });
}

async function handleAddRFIDCard(e) {
    e.preventDefault();
    if (!state.selectedDeviceId) return;

    try {
        const payload = {
            card_uid: elements.newCardUid.value.trim(),
            employee_name: elements.newCardholderName.value.trim(),
            department: elements.newCardDept.value.trim(),
        };

        const res = await fetchWithAuth(`${API_BASE}/rfid/${state.selectedDeviceId}/cards`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Failed to enroll RFID card');
        }

        elements.addCardModal.classList.remove('open');
        elements.addCardForm.reset();
        showToast('RFID card successfully enrolled & synced to device cache!');
        await loadRFIDData(state.selectedDeviceId);
    } catch (err) {
        showToast(err.message, 'error');
    }
}

// ==============================================================================
// SECURITY ENFORCEMENT VERIFICATION (SIMULATE FORGED REQUEST)
// ==============================================================================

async function handleSimulateSecurityAttack() {
    const targetDevice = elements.forgedDeviceSelect.value;
    const targetModule = elements.forgedModuleSelect.value;

    elements.simulateAttackBtn.disabled = true;
    elements.simulateAttackBtn.textContent = 'Probing Backend Policy Guard...';
    elements.securityTestResult.style.display = 'none';

    try {
        const res = await fetchWithAuth(`${API_BASE}/devices/${targetDevice}/modules/${targetModule}/access`);
        const json = await res.json();

        elements.securityTestResult.style.display = 'flex';

        if (res.status === 403) {
            // EXPECTED SECURITY POLICY BLOCK
            elements.securityTestResult.className = 'security-alert-box blocked';
            elements.securityResultTitle.textContent = `403 FORBIDDEN: Policy Guard Intercepted Request`;
            elements.securityResultTitle.style.color = '#f87171';
            elements.securityResultDesc.innerHTML = `
                The backend policy guard (<code>require_device_module("${targetModule}")</code>) caught this request. 
                Even if an attacker bypasses the client UI and crafts an HTTP request, access to <strong>${targetModule}</strong> 
                on <strong>${targetDevice}</strong> is completely blocked at the server level.
            `;
            elements.securityResultJson.textContent = JSON.stringify(json, null, 2);
            elements.securityResultJson.style.color = '#f87171';
            showToast(`Backend Policy Guard: Blocked unauthorized module access (HTTP 403)`, 'warning');
        } else if (res.ok) {
            // LEGITIMATE ALLOWED REQUEST
            elements.securityTestResult.className = 'security-alert-box';
            elements.securityResultTitle.textContent = `200 OK: Module Legitimate & Enabled`;
            elements.securityResultTitle.style.color = 'var(--primary)';
            elements.securityResultDesc.innerHTML = `
                Device <strong>${targetDevice}</strong> has hardware module <strong>${targetModule}</strong> enabled in the database. 
                Access is authorized by policy rules.
            `;
            elements.securityResultJson.textContent = JSON.stringify(json, null, 2);
            elements.securityResultJson.style.color = 'var(--primary)';
            showToast(`Access granted: Module is legitimately active on ${targetDevice}`);
        } else {
            // Other error
            elements.securityTestResult.className = 'security-alert-box blocked';
            elements.securityResultTitle.textContent = `HTTP ${res.status}: Request Denied`;
            elements.securityResultDesc.textContent = json.detail || 'Request failed';
            elements.securityResultJson.textContent = JSON.stringify(json, null, 2);
        }
    } catch (err) {
        showToast(err.message, 'error');
    } finally {
        elements.simulateAttackBtn.disabled = false;
        elements.simulateAttackBtn.innerHTML = `
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>
            Execute Forged Request
        `;
    }
}

// ==============================================================================
// UTILITIES
// ==============================================================================

async function fetchWithAuth(url, options = {}) {
    const headers = {
        'Content-Type': 'application/json',
        ...(state.token ? { 'Authorization': `Bearer ${state.token}` } : {}),
        ...options.headers,
    };
    try {
        const res = await fetch(url, { ...options, headers });
        if (res.status === 401) {
            state.token = null;
            localStorage.removeItem('iot_client_token');
            showToast('Session expired. Please log in again.', 'warning');
            elements.loginModal?.classList.remove('hidden');
        }
        return res;
    } catch (err) {
        console.error(`[Client API Error] ${url}:`, err);
        showToast('Network error: Unable to connect to platform API server', 'error');
        throw err;
    }
}

function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = 'toast';
    if (type === 'error') {
        toast.style.borderLeftColor = 'var(--danger)';
    } else if (type === 'warning') {
        toast.style.borderLeftColor = 'var(--warning)';
    }
    toast.textContent = message;
    elements.toastContainer.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transition = 'opacity 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, 3500);
}

// Start application
document.addEventListener('DOMContentLoaded', init);
