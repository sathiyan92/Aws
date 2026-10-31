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
    navWiFi: document.getElementById('navWiFi'),
    navSecurity: document.getElementById('navSecurity'),

    tabWifiForm: document.getElementById('tabWifiForm'),
    tabWifiSsid: document.getElementById('tabWifiSsid'),
    tabWifiPassword: document.getElementById('tabWifiPassword'),
    tabWifiCurrentSsidDisplay: document.getElementById('tabWifiCurrentSsidDisplay'),
    wifiSyncStatusBadge: document.getElementById('wifiSyncStatusBadge'),
    btnSaveTabWifi: document.getElementById('btnSaveTabWifi'),

    clientWiFiModal: document.getElementById('clientWiFiModal'),
    closeClientWiFiModalBtn: document.getElementById('closeClientWiFiModalBtn'),
    cancelClientWiFiModalBtn: document.getElementById('cancelClientWiFiModalBtn'),
    clientWiFiModalForm: document.getElementById('clientWiFiModalForm'),
    modalClientWiFiDeviceId: document.getElementById('modalClientWiFiDeviceId'),
    clientModalWifiSsid: document.getElementById('clientModalWifiSsid'),
    clientModalWifiPass: document.getElementById('clientModalWifiPass'),
    btnSubmitClientWiFiModal: document.getElementById('btnSubmitClientWiFiModal'),

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
    elements.tabWifiForm?.addEventListener('submit', handleSaveTabWiFi);

    // Wi-Fi Modal
    elements.closeClientWiFiModalBtn?.addEventListener('click', closeClientWiFiModal);
    elements.cancelClientWiFiModalBtn?.addEventListener('click', closeClientWiFiModal);
    elements.clientWiFiModalForm?.addEventListener('submit', handleSaveClientWiFiModal);

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
                ${dev.has_qr_payment || dev.product_type === 'VENDING_MACHINE' ? `
                    <button class="btn btn-warning pricing-fleet-btn" data-device-id="${dev.device_id}" style="padding: 0.3rem 0.6rem; font-size: 0.72rem; margin-right: 0.35rem;" title="Configure Slot Prices & UPI QR">
                        💰 Prices & QR
                    </button>
                ` : ''}
                <button class="btn btn-outline-primary wifi-fleet-btn" data-device-id="${dev.device_id}" style="padding: 0.3rem 0.6rem; font-size: 0.72rem; margin-right: 0.35rem;" title="Change Machine Wi-Fi Password">
                    📶 Wi-Fi
                </button>
                <button class="btn btn-secondary select-fleet-btn" data-device-id="${dev.device_id}" style="padding: 0.3rem 0.6rem; font-size: 0.72rem;">
                    Manage &rarr;
                </button>
            </td>
        `;
        elements.fleetTableBody.appendChild(tr);
    });

    document.querySelectorAll('.pricing-fleet-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const devId = btn.dataset.deviceId;
            elements.deviceSelect.value = devId;
            state.selectedDeviceId = devId;
            onDeviceSelectionChanged();
            switchTab('tab-qr');
            showToast(`Opened Slot Prices & QR configuration for ${devId}`);
        });
    });

    document.querySelectorAll('.wifi-fleet-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            openClientWiFiModal(btn.dataset.deviceId);
        });
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
    } else if (state.currentTab === 'tab-wifi') {
        loadActiveDeviceWiFi(state.selectedDeviceId);
    }
}

// ==============================================================================
// MODULE DATA LOADERS & ACTIONS
// ==============================================================================

// QR MODULE
let clientActiveSlots = [];
let clientActiveTestOrderId = null;

async function loadQRData(deviceId) {
    try {
        const res = await fetchWithAuth(`${API_BASE}/vending/${deviceId}/qr/settings`);
        if (res.ok) {
            const data = await res.json();
            elements.qrVpa.value = data.upi_merchant_vpa || '';
            elements.qrTimeout.value = data.qr_timeout_seconds || 120;
            elements.qrMerchantName.value = data.merchant_name || 'Apex Vending Solutions';
            
            const qrUrlInput = document.getElementById('clientQrImageUrl');
            const quickInput = document.getElementById('clientSlotQuickQrInput');
            if (data.custom_qr_image_url) {
                if (qrUrlInput) qrUrlInput.value = data.custom_qr_image_url;
                if (quickInput) quickInput.value = data.custom_qr_image_url;
                updateClientQrImagePreview(data.custom_qr_image_url);
                updateClientSlotQuickQrPreview(data.custom_qr_image_url);
            } else {
                if (qrUrlInput) qrUrlInput.value = '';
                if (quickInput) quickInput.value = '';
                updateClientQrImagePreview('');
                updateClientSlotQuickQrPreview('');
            }
        }

        // Load Slots & Pricing
        await loadClientSlotsData(deviceId);

        const txRes = await fetchWithAuth(`${API_BASE}/vending/${deviceId}/qr/transactions`);
        if (txRes.ok) {
            const txs = await txRes.json();
            renderQRTransactions(txs);
        }
    } catch (err) {
        showToast(err.message, 'error');
    }
}

async function loadClientSlotsData(deviceId) {
    const tbody = document.getElementById('clientSlotsTableBody');
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; padding:1.5rem;">Loading slots...</td></tr>';

    try {
        const res = await fetchWithAuth(`${API_BASE}/vending/${deviceId}/slots`);
        if (res.ok) {
            clientActiveSlots = await res.json();
            renderClientSlots(clientActiveSlots);
            populateClientTestSlots(clientActiveSlots);
        }
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; color:var(--danger);">${e.message}</td></tr>`;
    }
}

function renderClientSlots(slots) {
    const tbody = document.getElementById('clientSlotsTableBody');
    if (!tbody) return;
    if (!slots || slots.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="7" style="text-align:center; padding:1.5rem;">
                    <p style="color:var(--text-muted); margin-bottom:0.75rem;">No slots configured for this machine.</p>
                    <button type="button" class="btn btn-primary btn-sm" onclick="initClientDefaultSlots()">⚡ Auto-Initialize Slots (₹10 / ₹20)</button>
                </td>
            </tr>
        `;
        return;
    }

    tbody.innerHTML = slots.map(s => `
        <tr>
            <td class="mono-text" style="font-weight:700; text-align:center;">
                <span class="badge badge-on">Slot ${s.slot_number}</span>
            </td>
            <td>
                <input type="text" class="input-field" id="cslot-name-${s.slot_number}" value="${s.product_name || `Slot ${s.slot_number} Item`}" style="font-size:0.85rem; padding:0.4rem 0.6rem;">
            </td>
            <td>
                <div style="display:flex; align-items:center; gap:0.25rem;">
                    <span style="color:var(--primary); font-weight:700;">₹</span>
                    <input type="number" step="0.5" class="input-field" id="cslot-price-${s.slot_number}" value="${s.price_rupees.toFixed(2)}" style="font-size:0.9rem; font-weight:700; color:#34d399; width:90px; padding:0.4rem 0.5rem;" required>
                </div>
            </td>
            <td>
                <input type="number" class="input-field" id="cslot-stock-${s.slot_number}" value="${s.current_stock}" style="font-size:0.85rem; width:70px; padding:0.4rem 0.5rem;">
            </td>
            <td>
                <input type="number" class="input-field" id="cslot-cap-${s.slot_number}" value="${s.capacity}" style="font-size:0.85rem; width:70px; padding:0.4rem 0.5rem;">
            </td>
            <td style="text-align:center;">
                <input type="checkbox" id="cslot-active-${s.slot_number}" ${s.is_active ? 'checked' : ''} style="cursor:pointer; transform:scale(1.2);">
            </td>
            <td style="text-align:center;">
                <button type="button" class="btn btn-primary btn-sm" onclick="saveClientSlotPrice(${s.slot_number})" style="padding:0.35rem 0.6rem; font-size:0.75rem;">💾 Save</button>
            </td>
        </tr>
    `).join("");
}

async function saveClientSlotPrice(slotNumber) {
    if (!state.selectedDeviceId) return;

    const nameInput = document.getElementById(`cslot-name-${slotNumber}`);
    const priceInput = document.getElementById(`cslot-price-${slotNumber}`);
    const stockInput = document.getElementById(`cslot-stock-${slotNumber}`);
    const capInput = document.getElementById(`cslot-cap-${slotNumber}`);
    const activeInput = document.getElementById(`cslot-active-${slotNumber}`);

    const productName = nameInput ? nameInput.value.trim() : '';
    const priceRupees = priceInput ? parseFloat(priceInput.value) : 10.0;
    const stock = stockInput ? (parseInt(stockInput.value) || 0) : 10;
    const capacity = capInput ? (parseInt(capInput.value) || 20) : 20;
    const isActive = activeInput ? activeInput.checked : true;

    if (isNaN(priceRupees) || priceRupees < 0) {
        showToast("Please enter a valid price in Rupees.", "error");
        return;
    }

    const payload = {
        product_name: productName,
        override_price: Math.round(priceRupees * 100),
        capacity: capacity,
        current_stock: stock,
        is_active: isActive
    };

    try {
        const res = await fetchWithAuth(`${API_BASE}/vending/${state.selectedDeviceId}/slots/${slotNumber}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (res.ok) {
            showToast(`✓ Slot ${slotNumber} updated ("${productName || 'Item'}", ₹${priceRupees.toFixed(2)})! Machine updating...`);
            await loadClientSlotsData(state.selectedDeviceId);
        } else {
            const err = await res.json();
            showToast(err.detail || 'Failed to update slot price', 'error');
        }
    } catch (e) {
        showToast(e.message, 'error');
    }
}

async function initClientDefaultSlots() {
    if (!state.selectedDeviceId) return;
    try {
        await fetchWithAuth(`${API_BASE}/vending/${state.selectedDeviceId}/slots/1`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ override_price: 1000, capacity: 20, current_stock: 15, is_active: true })
        });
        await fetchWithAuth(`${API_BASE}/vending/${state.selectedDeviceId}/slots/2`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ override_price: 2000, capacity: 20, current_stock: 10, is_active: true })
        });
        showToast("Default slots initialized!");
        await loadClientSlotsData(state.selectedDeviceId);
    } catch (e) {
        showToast(e.message, 'error');
    }
}

function addNewClientSlotRow() {
    const nextSlotNum = clientActiveSlots.length > 0 
        ? Math.max(...clientActiveSlots.map(s => s.slot_number)) + 1 
        : 1;
    saveClientSlotPrice(nextSlotNum);
}

function updateClientSlotQuickQrPreview(url) {
    const img = document.getElementById('clientSlotQuickQrPreview');
    const placeholder = document.getElementById('clientSlotQuickQrPlaceholder');
    if (!img || !placeholder) return;

    if (url && url.trim().length > 0) {
        const clean = url.trim();
        if (clean.startsWith('upi://') || (!clean.startsWith('http://') && !clean.startsWith('https://') && !clean.startsWith('data:image/'))) {
            img.src = `https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(clean)}`;
        } else {
            img.src = clean;
        }
        img.style.display = 'block';
        placeholder.style.display = 'none';
    } else {
        img.src = '';
        img.style.display = 'none';
        placeholder.style.display = 'block';
    }
}

function handleClientSlotQuickQr(val) {
    const clean = val.trim();
    if (clean.startsWith('upi://pay')) {
        try {
            const dummyUrl = new URL(clean.replace('upi://pay', 'http://dummy.pay'));
            const am = dummyUrl.searchParams.get('am');
            const pa = dummyUrl.searchParams.get('pa');
            if (am) {
                const s1Price = document.getElementById('client-slot-price-1');
                if (s1Price) s1Price.value = parseFloat(am).toFixed(2);
            }
            if (pa && elements.qrVpa) {
                elements.qrVpa.value = pa;
            }
        } catch (e) {}
    }
    updateClientSlotQuickQrPreview(clean);
    const qrInput = document.getElementById('clientQrImageUrl');
    if (qrInput) {
        qrInput.value = clean;
        updateClientQrImagePreview(clean);
    }
}

async function applyClientQuickQrToDevice() {
    if (!state.selectedDeviceId) return;
    const input = document.getElementById('clientSlotQuickQrInput');
    const clean = input ? input.value.trim() : '';
    if (!clean) {
        showToast("Please paste a valid UPI link or QR image URL.", "error");
        return;
    }

    try {
        const res = await fetchWithAuth(`${API_BASE}/orders/qr-config/${state.selectedDeviceId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ custom_qr_payload: clean })
        });

        if (res.ok) {
            const data = await res.json();
            showToast(`✓ QR Code & Price (₹${data.amount_rupees.toFixed(2)}) synced to machine ${state.selectedDeviceId}!`);
            await loadClientSlotsData(state.selectedDeviceId);
            await loadQRData(state.selectedDeviceId);
        } else {
            const err = await res.json();
            showToast(`Failed to sync QR: ${err.detail || res.statusText}`, "error");
        }
    } catch (e) {
        showToast(e.message, "error");
    }
}

function updateClientQrImagePreview(url) {
    const img = document.getElementById('clientQrImagePreview');
    const placeholder = document.getElementById('clientQrPlaceholder');
    if (!img || !placeholder) return;

    if (url && url.trim().length > 0) {
        const clean = url.trim();

        // Auto-extract UPI parameters if a UPI URI is pasted
        if (clean.startsWith('upi://pay')) {
            try {
                const dummyUrl = new URL(clean.replace('upi://pay', 'http://dummy.pay'));
                const pa = dummyUrl.searchParams.get('pa');
                const tn = dummyUrl.searchParams.get('tn');

                if (elements.qrVpa && pa && (!elements.qrVpa.value || elements.qrVpa.value.includes('@icici') || elements.qrVpa.value.includes('pay.vm'))) {
                    elements.qrVpa.value = pa;
                }
                if (elements.qrMerchantName && tn) {
                    const cleanName = decodeURIComponent(tn).replace(/^Payment\s+To\s+/i, '');
                    if (cleanName) elements.qrMerchantName.value = cleanName;
                }
            } catch (err) {
                console.warn('Failed parsing UPI URL params:', err);
            }
        }

        // Render live scannable QR Code image for UPI URIs or text payloads
        if (clean.startsWith('upi://') || (!clean.startsWith('http://') && !clean.startsWith('https://') && !clean.startsWith('data:image/'))) {
            img.src = `https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(clean)}`;
        } else {
            img.src = clean;
        }
        img.style.display = 'block';
        placeholder.style.display = 'none';
    } else {
        img.src = '';
        img.style.display = 'none';
        placeholder.style.display = 'block';
    }
}

function handleClientQRImageUpload(event) {
    const file = event.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = async function(e) {
        const base64Data = e.target.result;
        updateClientQrImagePreview(base64Data);
        showToast("Scanning & decoding QR code from image...", "info");

        try {
            const decodeRes = await fetchWithAuth(`${API_BASE}/vending/decode-qr`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ image_data: base64Data })
            });

            if (decodeRes.ok) {
                const dec = await decodeRes.json();
                if (dec.success && dec.qr_payload) {
                    const input = document.getElementById('clientQrImageUrl');
                    if (input) input.value = dec.qr_payload;
                    if (dec.vpa) {
                        const vpaInput = document.getElementById('clientQrVpa');
                        if (vpaInput) vpaInput.value = dec.vpa;
                    }
                    if (dec.merchant_name) {
                        const mInput = document.getElementById('clientQrMerchantName');
                        if (mInput) mInput.value = dec.merchant_name;
                    }
                    showToast(`✓ QR Code Decoded: ${dec.vpa || 'UPI payload detected'}! Ready to save.`);
                    return;
                }
            }
        } catch (err) {
            console.warn("Client QR decode error:", err);
        }

        const input = document.getElementById('clientQrImageUrl');
        if (input) input.value = base64Data;
        showToast("QR Code image loaded! Click 'Save QR Settings' to store.");
    };
    reader.readAsDataURL(file);
}

function populateClientTestSlots(slots) {
    const sel = document.getElementById('clientTestSlotSelect');
    if (!sel) return;
    sel.innerHTML = '';
    if (!slots || slots.length === 0) {
        sel.innerHTML = '<option value="1">Slot 1 (₹10.00)</option><option value="2">Slot 2 (₹20.00)</option>';
        return;
    }
    slots.forEach(s => {
        const opt = document.createElement('option');
        opt.value = s.slot_number;
        opt.textContent = `Slot ${s.slot_number}: ${s.product_name || 'Item'} (₹${s.price_rupees.toFixed(2)})`;
        sel.appendChild(opt);
    });
}

async function generateClientTestQR() {
    if (!state.selectedDeviceId) return;
    const slotNum = parseInt(document.getElementById('clientTestSlotSelect').value) || 1;

    try {
        const res = await fetchWithAuth(`${API_BASE}/orders/initiate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                device_id: state.selectedDeviceId,
                slot_number: slotNum
            })
        });

        if (res.ok) {
            const data = await res.json();
            clientActiveTestOrderId = data.order_id;

            document.getElementById('clientTestOrderNum').textContent = data.order_number;
            document.getElementById('clientTestProductName').textContent = data.product_name;
            document.getElementById('clientTestPrice').textContent = `₹${data.amount_rupees.toFixed(2)}`;
            document.getElementById('clientTestStatus').textContent = data.order_status;
            document.getElementById('clientTestStatus').className = 'badge badge-offline';
            document.getElementById('clientTestOrderCard').style.display = 'block';

            const qrImg = document.getElementById('clientDynamicQrImg');
            const qrEmpty = document.getElementById('clientDynamicQrEmpty');
            const upiUriLabel = document.getElementById('clientUpiUriLabel');

            qrImg.src = `https://api.qrserver.com/v1/create-qr-code/?size=190x190&data=${encodeURIComponent(data.qr_payload)}`;
            qrImg.style.display = 'block';
            qrEmpty.style.display = 'none';
            upiUriLabel.textContent = data.qr_payload;

            showToast(`Dynamic QR generated for Slot ${slotNum} (₹${data.amount_rupees.toFixed(2)})!`);
        } else {
            const err = await res.json();
            showToast(err.detail || 'Failed to initiate QR order', 'error');
        }
    } catch (e) {
        showToast(e.message, 'error');
    }
}

async function simulateClientTestPaymentPaid() {
    if (!clientActiveTestOrderId) {
        showToast("Generate a QR order first", "error");
        return;
    }

    try {
        const res = await fetchWithAuth(`${API_BASE}/orders/${clientActiveTestOrderId}/mark-paid`, {
            method: 'POST'
        });

        if (res.ok) {
            document.getElementById('clientTestStatus').textContent = 'PAID (DISPENSE TRIGGERED)';
            document.getElementById('clientTestStatus').className = 'badge badge-on';
            showToast("✓ Payment Confirmed! Cloud marked order as PAID. ESP32 relay triggered!");
        } else {
            const err = await res.json();
            showToast(err.detail || 'Failed to confirm payment', 'error');
        }
    } catch (e) {
        showToast(e.message, 'error');
    }
}

async function handleSaveQRSettings(e) {
    if (e && e.preventDefault) e.preventDefault();
    if (!state.selectedDeviceId) return;

    try {
        const qrUrlInput = document.getElementById('clientQrImageUrl');
        const rawQr = qrUrlInput ? qrUrlInput.value.trim() : '';
        let vpaVal = elements.qrVpa ? elements.qrVpa.value.trim() : '';
        let nameVal = elements.qrMerchantName ? elements.qrMerchantName.value.trim() : '';

        if (rawQr.startsWith('upi://pay')) {
            try {
                const dummy = new URL(rawQr.replace('upi://pay', 'http://dummy.pay'));
                const pa = dummy.searchParams.get('pa');
                const tn = dummy.searchParams.get('tn');
                if (!vpaVal && pa) {
                    vpaVal = pa;
                    if (elements.qrVpa) elements.qrVpa.value = vpaVal;
                }
                if (!nameVal && tn) {
                    nameVal = decodeURIComponent(tn).replace(/^Payment\s+To\s+/i, '');
                    if (elements.qrMerchantName) elements.qrMerchantName.value = nameVal;
                }
            } catch (err) {}
        }

        if (!vpaVal) vpaVal = `pay.${state.selectedDeviceId.toLowerCase()}@icici`;
        if (!nameVal) nameVal = "Smart Vending";

        const payload = {
            upi_merchant_vpa: vpaVal,
            merchant_name: nameVal,
            qr_timeout_seconds: parseInt(elements.qrTimeout.value) || 120,
            dynamic_pricing_enabled: true,
            custom_qr_image_url: rawQr || null
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

        showToast(`✓ QR payment parameters updated for ${state.selectedDeviceId}!`);
        await loadClientSlotsData(state.selectedDeviceId);
        await loadQRData(state.selectedDeviceId);
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

// ==============================================================================
// VENDOR / CLIENT WI-FI CREDENTIALS CONFIGURATION
// ==============================================================================

async function loadActiveDeviceWiFi(deviceId) {
    if (!deviceId) return;
    try {
        const res = await fetchWithAuth(`${API_BASE}/devices/${deviceId}/wifi`);
        if (!res.ok) {
            if (elements.tabWifiCurrentSsidDisplay) {
                elements.tabWifiCurrentSsidDisplay.textContent = 'Not Configured';
            }
            return;
        }
        const data = await res.json();
        if (elements.tabWifiCurrentSsidDisplay) {
            elements.tabWifiCurrentSsidDisplay.textContent = data.wifi_ssid || 'Not Configured';
        }
        if (elements.tabWifiSsid) {
            elements.tabWifiSsid.value = data.wifi_ssid || '';
        }
        if (elements.tabWifiPassword) {
            elements.tabWifiPassword.value = '';
            elements.tabWifiPassword.placeholder = data.has_password ? '•••••••• (Enter new password to change)' : 'Enter Wi-Fi network password';
        }
        if (elements.wifiSyncStatusBadge) {
            elements.wifiSyncStatusBadge.textContent = data.is_synced ? 'In Sync' : 'Sync Pending';
            elements.wifiSyncStatusBadge.className = data.is_synced ? 'badge badge-on' : 'badge badge-off';
        }
    } catch (e) {
        console.error('Failed to load Wi-Fi config', e);
    }
}

async function handleSaveTabWiFi(e) {
    e.preventDefault();
    if (!state.selectedDeviceId) {
        showToast('Please select a device first', 'warning');
        return;
    }

    const ssid = elements.tabWifiSsid.value.trim();
    const pass = elements.tabWifiPassword.value;
    const btn = elements.btnSaveTabWifi;

    if (!ssid) {
        showToast('SSID cannot be empty', 'warning');
        return;
    }

    btn.disabled = true;
    btn.textContent = 'Pushing to Cloud...';

    try {
        const res = await fetchWithAuth(`${API_BASE}/devices/${state.selectedDeviceId}/wifi`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                wifi_ssid: ssid,
                wifi_password: pass
            })
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Failed to update Wi-Fi');
        }

        const data = await res.json();
        showToast(`✓ Wi-Fi credentials updated for ${state.selectedDeviceId}! Config bumped to v${data.config_version}`);
        loadActiveDeviceWiFi(state.selectedDeviceId);
        await loadFleetCapabilities();
    } catch (err) {
        showToast(err.message, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = '💾 Save & Push Wi-Fi Credentials';
    }
}

let currentClientWiFiModalDeviceId = null;

async function openClientWiFiModal(deviceId) {
    currentClientWiFiModalDeviceId = deviceId;
    elements.modalClientWiFiDeviceId.textContent = deviceId;
    elements.clientModalWifiSsid.value = '';
    elements.clientModalWifiPass.value = '';
    elements.clientModalWifiPass.placeholder = 'Enter Wi-Fi password';

    try {
        const res = await fetchWithAuth(`${API_BASE}/devices/${deviceId}/wifi`);
        if (res.ok) {
            const data = await res.json();
            if (data.wifi_ssid) {
                elements.clientModalWifiSsid.value = data.wifi_ssid;
            }
            if (data.has_password) {
                elements.clientModalWifiPass.placeholder = '•••••••• (Enter new password to change)';
            }
        }
    } catch (e) {}

    elements.clientWiFiModal.classList.add('open');
}

function closeClientWiFiModal() {
    elements.clientWiFiModal.classList.remove('open');
}

async function handleSaveClientWiFiModal(e) {
    e.preventDefault();
    if (!currentClientWiFiModalDeviceId) return;

    const ssid = elements.clientModalWifiSsid.value.trim();
    const pass = elements.clientModalWifiPass.value;
    const btn = elements.btnSubmitClientWiFiModal;

    if (!ssid) {
        showToast('Wi-Fi SSID is required', 'warning');
        return;
    }

    btn.disabled = true;
    btn.textContent = 'Pushing to Cloud...';

    try {
        const res = await fetchWithAuth(`${API_BASE}/devices/${currentClientWiFiModalDeviceId}/wifi`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                wifi_ssid: ssid,
                wifi_password: pass
            })
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Failed to update Wi-Fi credentials');
        }

        const data = await res.json();
        showToast(`✓ Wi-Fi credentials updated for ${currentClientWiFiModalDeviceId}! Config bumped to v${data.config_version}`);
        closeClientWiFiModal();
        await loadFleetCapabilities();
        if (state.selectedDeviceId === currentClientWiFiModalDeviceId) {
            loadActiveDeviceWiFi(state.selectedDeviceId);
        }
    } catch (err) {
        showToast(err.message, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = '💾 Update Wi-Fi';
    }
}

function togglePasswordVisibility(inputId, btn) {
    const input = document.getElementById(inputId);
    if (!input) return;
    if (input.type === 'password') {
        input.type = 'text';
        btn.textContent = '🙈 Hide';
    } else {
        input.type = 'password';
        btn.textContent = '👁️ Show';
    }
}

// Start application
document.addEventListener('DOMContentLoaded', init);
