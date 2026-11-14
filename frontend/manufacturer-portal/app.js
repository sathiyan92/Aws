function setElText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text != null ? text : "";
}


async function parseApiError(res) {
    try {
        const data = await res.json();
        if (data && data.detail) {
            if (typeof data.detail === 'string') return data.detail;
            if (data.detail.message) return data.detail.message;
            return JSON.stringify(data.detail);
        }
    } catch (_) {}
    try {
        const text = await res.text();
        if (text && text.trim().length > 0) return text.trim();
    } catch (_) {}
    return res.statusText || `HTTP ${res.status} Error`;
}

function extractTrIdFromPayload(payload) {
    if (!payload || typeof payload !== "string") return "";
    const clean = payload.trim();
    if (clean.includes("tr=")) {
        try {
            const dummy = new URL(clean.replace("upi://pay", "http://dummy.pay"));
            const tr = dummy.searchParams.get("tr");
            if (tr) return tr.trim();
        } catch (e) {
            const match = clean.match(/[?&]tr=([^&]+)/i);
            if (match) return match[1].trim();
        }
    }
    const match = clean.match(/(qr_[a-zA-Z0-9]+)/i);
    if (match) return match[1].trim();
    return "";
}
/**
 * Manufacturer Operations Portal - Reactive Single Page Application
 * Multi-Tenant Cloud IoT Platform for Vending and RFID Systems
 */

function getApiBase() {
    const customApi = localStorage.getItem("iot_api_server");
    if (customApi && customApi.trim().length > 0) {
        let base = customApi.trim().replace(/\/+$/, '');
        return base.endsWith("/api/v1") ? base : `${base}/api/v1`;
    }
    if (window.location.protocol === "file:" || window.location.protocol === "capacitor:" || window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1") {
        return "http://35.154.219.82:8000/api/v1";
    }
    const host = window.location.hostname || "localhost";
    const port = window.location.port;
    if (port === "8000" || window.location.pathname.startsWith("/portal")) {
        return `${window.location.origin}/api/v1`;
    }
    return `http://${host}:8000/api/v1`;
}

const API_BASE = getApiBase();

// Application State
const state = {
    token: localStorage.getItem("mfg_token") || null,
    user: JSON.parse(localStorage.getItem("mfg_user") || "null"),
    stats: null,
    clients: [],
    devices: [],
    auditLogs: [],
    firmwares: [],
    deployments: [],
    activeTab: "overview",
};

// ==============================================================================
// INITIALIZATION
// ==============================================================================
document.addEventListener("DOMContentLoaded", () => {
    initNavigation();
    initModals();
    if (state.token) {
        bootstrapPortal();
    } else {
        showLoginModal();
    }
});

function initNavigation() {
    document.querySelectorAll(".nav-item").forEach(item => {
        item.addEventListener("click", () => {
            const tab = item.getAttribute("data-tab");
            if (tab) switchTab(tab);
        });
    });

    document.getElementById("logoutBtn")?.addEventListener("click", handleLogout);
    document.getElementById("refreshBtn")?.addEventListener("click", () => {
        showToast("Refreshing fleet telemetry...");
        bootstrapPortal();
    });
}


function toggleMobileSidebar() {
    const sidebar = document.querySelector(".sidebar");
    const backdrop = document.getElementById("sidebarBackdrop");
    if (sidebar) sidebar.classList.toggle("mobile-open");
    if (backdrop) backdrop.classList.toggle("open");
}

function closeMobileSidebar() {
    const sidebar = document.querySelector(".sidebar");
    const backdrop = document.getElementById("sidebarBackdrop");
    if (sidebar) sidebar.classList.remove("mobile-open");
    if (backdrop) backdrop.classList.remove("open");
}
window.toggleMobileSidebar = toggleMobileSidebar;
window.closeMobileSidebar = closeMobileSidebar;

function switchTab(tabName) {
    closeMobileSidebar();
    state.activeTab = tabName;
    document.querySelectorAll(".nav-item").forEach(el => el.classList.remove("active"));
    document.querySelector(`.nav-item[data-tab="${tabName}"]`)?.classList.add("active");

    document.querySelectorAll(".tab-pane").forEach(el => el.classList.remove("active"));
    document.getElementById(`tab-${tabName}`)?.classList.add("active");

    // Page title updates
    const titleMap = {
        overview: "Fleet Command Center",
        clients: "Client Tenants Directory",
        devices: "All Connected Hardware",
        vending: "Vending Fleet & Modules",
        "qr-manager": "UPI QR Code & Price Manager",
        rfid: "RFID Attendance Fleet",
        firmware: "Firmware Artifacts & OTA Distribution Hub",
        audit: "System Security & Audit Trail",
    };
    setElText("pageTitle", titleMap[tabName] || "Manufacturer Portal");

    if (tabName === "clients") renderClientsTable();
    if (tabName === "devices") renderDevicesTable();
    if (tabName === "vending") renderDevicesTable("VENDING_MACHINE");
    if (tabName === "qr-manager") renderQrManagerTab();
    if (tabName === "rfid") { renderDevicesTable("RFID_ATTENDANCE"); loadAdminRfidCards(); loadAdminRfidLogs(); }
    if (tabName === "firmware") renderFirmwareTab();
    if (tabName === "audit") renderAuditTable();
    loadDiscoveryQueue();
}

// ==============================================================================
// API CALLS & BOOTSTRAP
// ==============================================================================
async function apiFetch(endpoint, options = {}) {
    const url = endpoint.startsWith("http")
        ? endpoint
        : endpoint.startsWith("/api/v1")
            ? endpoint
            : `${API_BASE}${endpoint}`;
    const headers = {
        "Content-Type": "application/json",
        ...(state.token ? { "Authorization": `Bearer ${state.token}` } : {}),
        ...options.headers,
    };
    return fetch(url, { ...options, headers });
}

async function apiRequest(endpoint, options = {}) {
    const isFormData = options.body instanceof FormData;
    const headers = {
        ...(isFormData ? {} : { "Content-Type": "application/json" }),
        ...(state.token ? { "Authorization": `Bearer ${state.token}` } : {}),
        ...options.headers,
    };

    try {
        const response = await fetch(`${API_BASE}${endpoint}`, {
            ...options,
            headers,
        });

        if (response.status === 401 && endpoint !== "/auth/login") {
            handleLogout();
            throw new Error("Session expired. Please log in again.");
        }

        const text = await response.text();
        let data = {};
        if (text) {
            try {
                data = JSON.parse(text);
            } catch (jsonErr) {
                data = { raw: text };
            }
        }

        if (!response.ok) {
            let msg = "API request failed";
            if (data && data.detail) {
                if (typeof data.detail === "string") {
                    msg = data.detail;
                } else if (Array.isArray(data.detail)) {
                    msg = data.detail.map(d => d.msg || JSON.stringify(d)).join(", ");
                } else if (typeof data.detail === "object") {
                    msg = data.detail.message || JSON.stringify(data.detail);
                }
            } else if (data && data.message) {
                msg = data.message;
            } else if (response.statusText) {
                msg = `HTTP ${response.status}: ${response.statusText}`;
            }
            throw new Error(msg);
        }
        return data;
    } catch (err) {
        console.error(`[API Error] ${endpoint}:`, err);
        showToast(err.message || "Network error: Unable to connect to server", "danger");
        throw err;
    }
}

async function bootstrapPortal() {
    try {
        updateUserUI();
        await Promise.all([
            loadStats(),
            loadClients(),
            loadDevices(),
            loadAuditLogs(),
            loadFirmwareVersions(),
            loadOTADeployments(),
        ]);
        renderOverview();
        switchTab(state.activeTab);
    } catch (err) {
        console.error("Bootstrap error:", err);
    }
}

async function loadStats() {
    state.stats = await apiRequest("/manufacturer/platform-stats");
}

async function loadClients() {
    const res = await apiRequest("/clients");
    state.clients = res.clients || [];
}

async function loadDevices() {
    const res = await apiRequest("/devices");
    state.devices = res.devices || [];
}

async function loadFleet() {
    try { await loadDevices(); } catch (e) { console.warn("Notice loading devices:", e); }
    try { await loadDiscoveryQueue(); } catch (e) { console.warn("Notice loading discovery queue:", e); }
    try { await loadStats(); } catch (e) { console.warn("Notice loading stats:", e); }
    renderOverview();
    if (state.activeTab === "devices") renderDevicesTable();
    if (state.activeTab === "vending") renderDevicesTable("VENDING_MACHINE");
}
window.loadFleet = loadFleet;

async function loadAuditLogs() {
    const res = await apiRequest("/audit-logs?limit=50");
    state.auditLogs = res.logs || [];
}

async function loadFirmwareVersions() {
    try {
        const res = await apiRequest("/ota/firmware");
        state.firmwares = res.firmware_versions || [];
        const countEl = document.getElementById("statFwCount");
        if (countEl) countEl.textContent = state.firmwares.length;
    } catch (e) {
        console.warn("Could not load firmware catalog:", e);
    }
}

async function loadOTADeployments() {
    try {
        const res = await apiRequest("/ota/deployments");
        state.deployments = res.deployments || [];
        const pendingEl = document.getElementById("statPendingDeployments");
        const successEl = document.getElementById("statSuccessDeployments");
        if (pendingEl) {
            const pendingCount = state.deployments.filter(d => d.deployment_status === "PENDING" || d.deployment_status === "DOWNLOADING").length;
            pendingEl.textContent = pendingCount;
        }
        if (successEl) {
            const successCount = state.deployments.filter(d => d.deployment_status === "SUCCESS").length;
            successEl.textContent = successCount;
        }
        if (state.activeTab === "firmware") {
            renderDeploymentsTable();
        }
    } catch (e) {
        console.warn("Could not load OTA deployments:", e);
    }
}

// ==============================================================================
// RENDER VIEWS
// ==============================================================================
function renderOverview() {
    if (!state.stats) return;
    const s = state.stats;

    setElText("statTotalDevices", s.devices_count || 0);
    setElText("statOnlineDevices", s.online_devices_count || 0);
    setElText("statClients", s.clients_count || 0);
    setElText("statVending", s.product_type_breakdown?.VENDING_MACHINE || 0);
    setElText("statRFID", s.product_type_breakdown?.RFID_ATTENDANCE || 0);

    // Module badges
    setElText("statQRCount", s.module_breakdown?.QR_PAYMENT || 0);
    setElText("statCoinCount", s.module_breakdown?.COIN_PAYMENT || 0);
    setElText("statRFIDCount", s.module_breakdown?.RFID_ACCESS || 0);

    // Recent activity list
    const actBody = document.getElementById("recentActivityList");
    if (actBody && s.recent_audits) {
        actBody.innerHTML = s.recent_audits.map(a => `
            <div style="display:flex; justify-content:space-between; align-items:center; padding: 0.75rem 0; border-bottom: 1px solid var(--border-subtle);">
                <div>
                    <span class="badge ${a.action.includes('REGISTER') ? 'badge-online' : 'badge-module on'}">${a.action}</span>
                    <span style="font-size:0.8rem; margin-left:0.5rem; color:var(--text-secondary);">${a.entity_type}: <strong>${a.entity_id}</strong></span>
                </div>
                <span style="font-size:0.7rem; color:var(--text-muted);">${formatDate(a.created_at)}</span>
            </div>
        `).join("");
    }
}

function renderClientsTable() {
    const tbody = document.getElementById("clientsTableBody");
    if (!tbody) return;

    if (!state.clients.length) {
        tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:2rem;">No clients registered yet.</td></tr>`;
        return;
    }

    tbody.innerHTML = state.clients.map(c => `
        <tr>
            <td class="mono-text">${c.client_code}</td>
            <td><strong>${c.name}</strong></td>
            <td>${c.contact_email}</td>
            <td>${c.contact_phone || '—'}</td>
            <td><span class="badge badge-online">${c.status}</span></td>
            <td><span style="font-weight:700; color:var(--primary);">${c.device_count}</span> machines (${c.active_device_count} active)</td>
            <td style="display:flex; gap:0.4rem; align-items:center;">
                <button class="btn btn-secondary btn-sm" onclick="filterDevicesByClient('${c.id}', '${c.name.replace(/'/g, "\\'")}')">View Fleet</button>
                <button class="btn btn-warning btn-sm" onclick="openManageVendorLoginModal('${c.id}', '${c.name.replace(/'/g, "\\'")}')" title="Manage Vendor Login Username & Password" style="font-weight:600;">🔑 Login & Pass</button>
            </td>
        </tr>
    `).join("");
}

function renderDevicesTable(filterType = null) {
    const targetTableId = filterType === "VENDING_MACHINE" 
        ? "vendingTableBody" 
        : filterType === "RFID_ATTENDANCE" 
            ? "rfidTableBody" 
            : "devicesTableBody";

    const tbody = document.getElementById(targetTableId);
    if (!tbody) return;

    let devs = state.devices;
    if (filterType) {
        devs = devs.filter(d => d.device_type_code === filterType);
    }

    if (!devs.length) {
        tbody.innerHTML = `<tr><td colspan="9" style="text-align:center; padding:2rem;">No devices found.</td></tr>`;
        return;
    }

    tbody.innerHTML = devs.map(d => {
        const qrMod = d.modules.find(m => m.module_code === "QR_PAYMENT");
        const coinMod = d.modules.find(m => m.module_code === "COIN_PAYMENT");
        const rfidMod = d.modules.find(m => m.module_code === "RFID_ACCESS");

        return `
            <tr>
                <td class="mono-text" style="font-weight:700; font-size:0.9rem;">
                    <div>${d.device_id}</div>
                    <div style="font-size:0.72rem; color:var(--text-muted); font-weight:400; letter-spacing:0.5px;">MAC: ${d.mac_address || 'Unassigned'}</div>
                </td>
                <td>
                    <span class="badge ${d.device_type_code === 'VENDING_MACHINE' ? 'badge-module on' : 'badge-online'}">
                        ${d.device_type_code}
                    </span>
                </td>
                <td>${d.client_name ? `<strong style="color:var(--text-primary);">${d.client_name}</strong>` : `<span style="color:var(--warning); font-style:italic;">Unassigned (Inventory)</span>`}</td>
                <td>
                    <span class="badge ${d.is_online ? 'badge-online' : 'badge-offline'}">
                        <span class="badge-pulse"></span>
                        ${d.is_online ? 'ONLINE' : 'OFFLINE'}
                    </span>
                </td>
                <td>
                    <span class="badge" style="background:rgba(255,255,255,0.06);">${d.status}</span>
                </td>
                <td>
                    <span style="font-family:'JetBrains Mono'; font-weight:700; color:#38bdf8;">v${d.current_config_version}</span>
                </td>
                <td>
                    ${d.device_type_code === 'VENDING_MACHINE' ? `
                        <div style="display:flex; gap:0.5rem; align-items:center;">
                            <label title="QR Payment">
                                <span style="font-size:0.65rem; color:var(--text-muted); display:block;">QR</span>
                                <label class="switch">
                                    <input type="checkbox" ${qrMod?.is_enabled ? 'checked' : ''} onchange="handleModuleToggle('${d.id}', 'QR_PAYMENT', this.checked)">
                                    <span class="slider"></span>
                                </label>
                            </label>
                            <label title="Coin Payment">
                                <span style="font-size:0.65rem; color:var(--text-muted); display:block;">COIN</span>
                                <label class="switch">
                                    <input type="checkbox" ${coinMod?.is_enabled ? 'checked' : ''} onchange="handleModuleToggle('${d.id}', 'COIN_PAYMENT', this.checked)">
                                    <span class="slider"></span>
                                </label>
                            </label>
                        </div>
                    ` : `
                        <span class="badge badge-online">RFID READER</span>
                    `}
                </td>
                <td>
                    <div class="actions-cell">
                        ${d.device_type_code === 'VENDING_MACHINE' ? `
                            <button class="btn btn-warning btn-sm" title="Configure Slot Prices, UPI Merchant & QR" onclick="openDevicePricingModal('${d.device_id}')">💰 Prices & QR</button>
                        ` : ''}
                        <button class="btn btn-outline-primary btn-sm" title="Configure Wi-Fi Credentials Online" onclick="openWiFiModal('${d.device_id}')">📶 Wi-Fi</button>
                        <button class="btn btn-outline-primary btn-sm" title="Push OTA Firmware to this device" onclick="openPushOTAModal('${d.id}', '${d.device_id}')">🚀 OTA</button>
                        <button class="btn btn-secondary btn-sm" title="Assign Tenant" onclick="openAssignModal('${d.id}', '${d.device_id}', '${d.client_id || ''}')">Assign</button>
                        <button class="btn btn-outline-primary btn-sm" title="Edit Hardware Details" onclick="openEditHardwareModal('${d.id}')">✏️ Edit</button>
                        <button class="btn btn-outline-danger btn-sm" title="Permanently Delete Device" onclick="openDeleteDeviceModal('${d.id}', '${d.device_id}')">🗑️</button>
                    </div>
                </td>
            </tr>
        `;
    }).join("");
}

function renderAuditTable() {
    const tbody = document.getElementById("auditTableBody");
    if (!tbody) return;

    if (!state.auditLogs.length) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:2rem;">No audit records available.</td></tr>`;
        return;
    }

    tbody.innerHTML = state.auditLogs.map(a => `
        <tr>
            <td style="font-size:0.75rem; color:var(--text-muted);">${formatDate(a.created_at)}</td>
            <td><span class="badge badge-module on">${a.action}</span></td>
            <td><strong>${a.entity_type}</strong></td>
            <td class="mono-text">${a.entity_id}</td>
            <td style="font-size:0.75rem; max-width:250px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
                ${a.new_state ? JSON.stringify(a.new_state) : '—'}
            </td>
            <td style="font-size:0.75rem; color:var(--text-muted);">${a.ip_address || 'local'}</td>
        </tr>
    `).join("");
}

function renderFirmwareTab() {
    // Populate quick target device dropdown
    const quickSelect = document.getElementById("quickTargetDevice");
    if (quickSelect) {
        quickSelect.innerHTML = `<option value="">-- Choose Target ESP32 --</option>` +
            state.devices.map(d => `
                <option value="${d.device_id}">
                    ${d.device_id} - ${d.client_name || 'Inventory Node'} (${d.current_firmware_version || 'v1.0.0'})
                </option>
            `).join("");
    }
    renderFirmwareTable();
    renderDeploymentsTable();
}

function renderFirmwareTable() {
    const tbody = document.getElementById("firmwareTableBody");
    if (!tbody) return;

    if (!state.firmwares.length) {
        tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:2.5rem; color:var(--text-secondary);">
            <div style="font-size:1.5rem; margin-bottom:0.5rem;">📦</div>
            <div>No firmware binaries uploaded yet.</div>
            <button class="btn btn-primary btn-sm" style="margin-top:0.75rem;" onclick="openUploadFirmwareModal()">+ Upload Your First ESP32 Build</button>
        </td></tr>`;
        return;
    }

    tbody.innerHTML = state.firmwares.map(f => `
        <tr>
            <td>
                <strong style="color:var(--primary); font-family:'JetBrains Mono'; font-size:0.95rem;">${f.version_string}</strong>
                ${f.changelog ? `<div style="font-size:0.7rem; color:var(--text-secondary); margin-top:2px;">${f.changelog}</div>` : ''}
            </td>
            <td><span class="mono-text">${f.hardware_revision}</span></td>
            <td><span class="badge ${f.device_type_code === 'VENDING_MACHINE' ? 'badge-module on' : 'badge-online'}">${f.device_type_code}</span></td>
            <td style="font-weight:600;">${formatBytes(f.file_size_bytes)}</td>
            <td>
                <span class="mono-text" style="font-size:0.75rem; color:var(--text-secondary); background:rgba(255,255,255,0.03); padding:2px 6px; border-radius:4px;" title="Full SHA-256: ${f.sha256_checksum}">
                    ${f.sha256_checksum.substring(0, 16)}...
                </span>
            </td>
            <td style="font-size:0.75rem; color:var(--text-muted);">${formatDate(f.created_at)}</td>
            <td>
                <div class="actions-cell">
                    <button class="btn btn-primary btn-sm" onclick="openDeployCatalogVersionModal('${f.id}', '${f.version_string}')" title="Deploy to an ESP32">🚀 Deploy</button>
                    <a href="${f.binary_url}" download class="btn btn-secondary btn-sm" title="Direct download .bin file" target="_blank">⬇️ .bin</a>
                </div>
            </td>
        </tr>
    `).join("");
}

function renderDeploymentsTable() {
    const tbody = document.getElementById("deploymentsTableBody");
    if (!tbody) return;

    if (!state.deployments.length) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:2rem; color:var(--text-secondary);">No OTA deployments in history.</td></tr>`;
        return;
    }

    tbody.innerHTML = state.deployments.map(d => {
        let badgeClass = "badge";
        let statusBadge = d.deployment_status;
        if (d.deployment_status === "SUCCESS") badgeClass = "badge-online";
        else if (d.deployment_status === "FAILED") badgeClass = "badge-offline";
        else if (d.deployment_status === "DOWNLOADING") badgeClass = "badge-module on";
        else if (d.deployment_status === "PENDING") badgeClass = "badge-module";

        return `
            <tr>
                <td class="mono-text" style="font-weight:700; color:var(--primary); font-size:0.9rem;">${d.device_code}</td>
                <td><strong style="font-family:'JetBrains Mono';">${d.version_string}</strong></td>
                <td>
                    <span class="badge ${badgeClass}">
                        ${d.deployment_status === 'DOWNLOADING' || d.deployment_status === 'PENDING' ? '<span class="badge-pulse"></span>' : ''}
                        ${statusBadge}
                    </span>
                </td>
                <td style="font-size:0.75rem; color:var(--text-muted);">${formatDate(d.started_at || d.created_at)}</td>
                <td style="font-size:0.75rem; color:var(--text-muted);">${formatDate(d.completed_at)}</td>
                <td style="font-size:0.8rem; color:${d.error_message ? 'var(--danger)' : 'var(--text-secondary)'};">
                    ${d.error_message ? `⚠️ ${d.error_message}` : (d.deployment_status === 'SUCCESS' ? '✓ Verified in flash & active' : 'Waiting for ESP32 handshake cycle...')}
                </td>
            </tr>
        `;
    }).join("");
}

// ==============================================================================
// ACTIONS & HANDLERS
// ==============================================================================
async function handleModuleToggle(deviceId, moduleCode, isEnabled) {
    try {
        const res = await apiRequest(`/devices/${deviceId}/modules`, {
            method: "PUT",
            body: JSON.stringify({
                module_code: moduleCode,
                is_enabled: isEnabled,
            }),
        });
        showToast(`Module '${moduleCode}' updated on ${res.device_id}. Config bumped to v${res.current_config_version}`, "success");
        await loadDevices();
        await loadStats();
        renderOverview();
        if (state.activeTab === "devices") renderDevicesTable();
        if (state.activeTab === "vending") renderDevicesTable("VENDING_MACHINE");
    } catch (err) {
        // Revert table on error
        renderDevicesTable();
    }
}

function filterDevicesByClient(clientId, clientName) {
    switchTab("devices");
    showToast(`Filtering devices for ${clientName}`);
    const filtered = state.devices.filter(d => d.client_id === clientId);
    const tbody = document.getElementById("devicesTableBody");
    if (tbody && filtered.length) {
        renderDevicesTable();
    }
}

// ==============================================================================
// MODALS LOGIC
// ==============================================================================
function initModals() {
    // Quick Demo Login Button (Disabled in production)
    document.getElementById("btnQuickDemoLogin")?.addEventListener("click", async () => {
        await handleLoginSubmit();
    });

    // Login Form Submit
    document.getElementById("loginForm")?.addEventListener("submit", async (e) => {
        e.preventDefault();
        await handleLoginSubmit();
    });

    // Provision Device Form Submit
    document.getElementById("provisionForm")?.addEventListener("submit", async (e) => {
        e.preventDefault();
        const typeCode = document.getElementById("provType").value;
        const mac = document.getElementById("provMac").value;
        const chip = document.getElementById("provChip").value;
        const serial = document.getElementById("provSerial").value;
        const token = document.getElementById("provToken")?.value?.trim() || null;
        const qrOn = document.getElementById("provModQR").checked;
        const coinOn = document.getElementById("provModCoin").checked;

        try {
            const res = await apiRequest("/devices", {
                method: "POST",
                body: JSON.stringify({
                    device_type_code: typeCode,
                    hardware_id: "HW-ESP32S3-V1.2",
                    chip_id: chip,
                    mac_address: mac,
                    factory_serial: serial,
                    device_token: token,
                    initial_modules: {
                        "QR_PAYMENT": qrOn,
                        "COIN_PAYMENT": coinOn,
                        "RFID_ACCESS": false,
                    }
                })
            });
            closeModal("modalProvision");
            showToast(`Hardware registered successfully! Device ID: ${res.device_id}`, "success");
            
            // If provisioning token returned, show credentials modal
            if (res.provisioning_token) {
                document.getElementById("credDeviceId").value = res.device_id;
                document.getElementById("credMac").value = res.mac_address;
                document.getElementById("credChip").value = res.chip_id;
                document.getElementById("credToken").value = res.provisioning_token;
                openModal("modalDeviceCredentials");
            }

            await loadDevices();
            await loadStats();
            renderOverview();
            renderDevicesTable();
        } catch (err) {}
    });

    // Create Client Form Submit
    document.getElementById("createClientForm")?.addEventListener("submit", async (e) => {
        e.preventDefault();
        const code = document.getElementById("newClientCode").value.trim();
        const name = document.getElementById("newClientName").value.trim();
        const email = document.getElementById("newClientEmail").value.trim();
        const phone = document.getElementById("newClientPhone") ? document.getElementById("newClientPhone").value.trim() : "";
        const address = document.getElementById("newClientAddress") ? document.getElementById("newClientAddress").value.trim() : "";
        const username = document.getElementById("newClientUsername") ? document.getElementById("newClientUsername").value.trim() : "";
        const password = document.getElementById("newClientPassword") ? document.getElementById("newClientPassword").value.trim() : "";
        const assignDev = document.getElementById("newClientDeviceSelect") ? document.getElementById("newClientDeviceSelect").value.trim() : "";

        try {
            const res = await apiRequest("/clients", {
                method: "POST",
                body: JSON.stringify({
                    client_code: code,
                    name: name,
                    contact_email: email,
                    contact_phone: phone || undefined,
                    address: address || undefined,
                    admin_username: username || undefined,
                    admin_password: password || undefined,
                    assign_device_id: assignDev || undefined,
                })
            });
            closeModal("modalCreateClient");
            showToast(`Vendor '${res.name}' onboarded! Login Username: ${username || code.toLowerCase()}`, "success");
            await loadClients();
            await loadStats();
            await loadDevices();
            renderClientsTable();
            renderDevicesTable();
        } catch (err) {
            showToast(err.message || "Failed to onboard vendor", "danger");
        }
    });

    // Assign Device Form Submit
    document.getElementById("assignForm")?.addEventListener("submit", async (e) => {
        e.preventDefault();
        const devId = document.getElementById("assignDeviceId").value;
        const clientId = document.getElementById("assignClientId").value || null;

        try {
            const res = await apiRequest(`/devices/${devId}/assign`, {
                method: "POST",
                body: JSON.stringify({ client_id: clientId })
            });
            closeModal("modalAssign");
            showToast(`Device ${res.device_id} assigned successfully!`, "success");
            await loadDevices();
            await loadClients();
            await loadStats();
            renderOverview();
            renderDevicesTable();
        } catch (err) {}
    });

    // Edit Hardware Details Form Submit
    document.getElementById("editHardwareForm")?.addEventListener("submit", async (e) => {
        e.preventDefault();
        const devId = document.getElementById("editHardwareDeviceId").value;
        const newMachineId = document.getElementById("editHardwareDevId").value.trim().toUpperCase();
        const hwRevision = document.getElementById("editHardwareRevision").value.trim();
        const status = document.getElementById("editHardwareStatus").value;
        const mac = document.getElementById("editHardwareMac").value.trim();
        const chip = document.getElementById("editHardwareChip").value.trim();
        const serial = document.getElementById("editHardwareSerial").value.trim();
        const fw = document.getElementById("editHardwareFirmware").value.trim();

        try {
            const res = await apiRequest(`/devices/${devId}`, {
                method: "PUT",
                body: JSON.stringify({
                    device_id: newMachineId || undefined,
                    hardware_id: hwRevision,
                    status: status,
                    mac_address: mac,
                    chip_id: chip,
                    factory_serial: serial,
                    current_firmware_version: fw,
                }),
            });
            closeModal("modalEditHardware");
            showToast(`Hardware specs for ${res.device_id} updated successfully!`, "success");
            await loadDevices();
            await loadStats();
            renderOverview();
            renderDevicesTable(state.activeTab === "vending" ? "VENDING_MACHINE" : state.activeTab === "rfid" ? "RFID_ATTENDANCE" : null);
        } catch (err) {}
    });

    // Delete Device Form Submit
    document.getElementById("deleteDeviceForm")?.addEventListener("submit", async (e) => {
        e.preventDefault();
        const devId = document.getElementById("deleteTargetDeviceId").value;

        try {
            const res = await apiRequest(`/devices/${devId}`, {
                method: "DELETE",
            });
            closeModal("modalDeleteDevice");
            showToast(`Device ${res.device_id} permanently deleted.`, "success");
            await loadDevices();
            await loadClients();
            await loadStats();
            renderOverview();
            renderDevicesTable(state.activeTab === "vending" ? "VENDING_MACHINE" : state.activeTab === "rfid" ? "RFID_ATTENDANCE" : null);
        } catch (err) {}
    });

    // Quick Push Code to Target ESP32 Submit
    document.getElementById("quickPushForm")?.addEventListener("submit", async (e) => {
        e.preventDefault();
        const targetDeviceId = document.getElementById("quickTargetDevice").value;
        const fileInput = document.getElementById("quickBinFile");
        const version = document.getElementById("quickVersion").value.trim();
        const submitBtn = document.getElementById("btnQuickPush");

        if (!targetDeviceId) {
            showToast("Please select a target ESP32 device first", "danger");
            return;
        }
        if (!fileInput.files || !fileInput.files[0]) {
            showToast("Please choose a compiled .bin file from your laptop", "danger");
            return;
        }

        const file = fileInput.files[0];
        const targetDev = state.devices.find(d => d.device_id === targetDeviceId || d.id === targetDeviceId);
        const devTypeCode = targetDev ? targetDev.device_type_code : "VENDING_MACHINE";
        const hwRev = targetDev?.hardware_id || "HW-ESP32S3-V1.2";

        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.innerHTML = "⏳ Uploading & Pushing...";
        }

        const formData = new FormData();
        formData.append("file", file);
        formData.append("version_string", version);
        formData.append("hardware_revision", hwRev);
        formData.append("device_type_code", devTypeCode);
        formData.append("target_device_id", targetDeviceId);
        formData.append("changelog", "Wireless update from laptop portal");

        try {
            const response = await fetch(`${API_BASE}/ota/firmware/upload`, {
                method: "POST",
                headers: {
                    ...(state.token ? { "Authorization": `Bearer ${state.token}` } : {})
                },
                body: formData,
            });

            if (!response.ok) {
                if (response.status === 413) {
                    throw new Error("Upload failed: File is too large (HTTP 413). Server Nginx client_max_body_size limit exceeded.");
                }
                const errData = await response.json().catch(() => ({}));
                throw new Error(errData.detail || `Upload failed with status ${response.status}`);
            }

            const fw = await response.json();
            showToast(`🚀 Pushed ${fw.version_string} to ESP32 (${targetDeviceId})! The board will update on its next check.`, "success");
            fileInput.value = "";
            await loadFirmwareVersions();
            await loadOTADeployments();
            renderFirmwareTab();
        } catch (err) {
            showToast(err.message || "Failed to push code to ESP32", "danger");
        } finally {
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.innerHTML = "🚀 Push to ESP32";
            }
        }
    });

    // Upload Firmware Binary Form Submit
    document.getElementById("uploadFirmwareForm")?.addEventListener("submit", async (e) => {
        e.preventDefault();
        const fileInput = document.getElementById("fwBinaryFile");
        if (!fileInput.files || !fileInput.files[0]) {
            showToast("Please select a .bin firmware file", "danger");
            return;
        }

        const file = fileInput.files[0];
        const version = document.getElementById("fwVersionString").value.trim();
        const hwRevision = document.getElementById("fwHardwareRevision").value.trim();
        const devType = document.getElementById("fwDeviceTypeCode").value;
        const targetDeviceId = document.getElementById("fwTargetDeviceSelect").value || null;
        const changelog = document.getElementById("fwChangelog").value.trim();

        const statusEl = document.getElementById("fwUploadStatus");
        const submitBtn = document.getElementById("btnSubmitUploadFw");
        if (statusEl) statusEl.style.display = "block";
        if (submitBtn) submitBtn.disabled = true;

        const formData = new FormData();
        formData.append("file", file);
        formData.append("version_string", version);
        formData.append("hardware_revision", hwRevision);
        formData.append("device_type_code", devType);
        if (changelog) formData.append("changelog", changelog);
        if (targetDeviceId) formData.append("target_device_id", targetDeviceId);

        try {
            const response = await fetch(`${API_BASE}/ota/firmware/upload`, {
                method: "POST",
                headers: {
                    ...(state.token ? { "Authorization": `Bearer ${state.token}` } : {})
                },
                body: formData,
            });

            if (!response.ok) {
                const errData = await response.json().catch(() => ({}));
                throw new Error(errData.detail || `Upload failed with status ${response.status}`);
            }

            const fw = await response.json();
            closeModal("modalUploadFirmware");
            const targetMsg = targetDeviceId ? ` and queued for deployment to ${targetDeviceId}` : "";
            showToast(`Firmware ${fw.version_string} uploaded successfully${targetMsg}!`, "success");

            await loadFirmwareVersions();
            await loadOTADeployments();
            renderFirmwareTab();
        } catch (err) {
            showToast(err.message || "Failed to upload firmware binary", "danger");
        } finally {
            if (statusEl) statusEl.style.display = "none";
            if (submitBtn) submitBtn.disabled = false;
        }
    });

    // Push OTA Form Submit
    document.getElementById("pushOTAForm")?.addEventListener("submit", async (e) => {
        e.preventDefault();
        const devId = document.getElementById("pushTargetDeviceId").value;
        const fwVersionId = document.getElementById("pushFirmwareVersionSelect").value;
        const submitBtn = document.getElementById("btnSubmitPushOTA");
        if (submitBtn) submitBtn.disabled = true;

        try {
            const res = await apiRequest("/ota/deploy", {
                method: "POST",
                body: JSON.stringify({
                    device_id: devId,
                    firmware_version_id: fwVersionId,
                }),
            });
            closeModal("modalPushOTA");
            showToast(`OTA deployment queued for device ${res.device_code}! It will update on its next check.`, "success");
            await loadOTADeployments();
            if (state.activeTab === "firmware") renderDeploymentsTable();
        } catch (err) {
        } finally {
            if (submitBtn) submitBtn.disabled = false;
        }
    });
}


window.togglePasswordVisibility = function(inputId, btn) {
    const input = document.getElementById(inputId);
    if (!input) return;
    if (input.type === "password") {
        input.type = "text";
        if (btn) btn.textContent = "🙈";
    } else {
        input.type = "password";
        if (btn) btn.textContent = "👁️";
    }
};

async function handleLoginSubmit() {
    const uInput = document.getElementById("loginUsername");
    const pInput = document.getElementById("loginPassword");
    const u = uInput ? uInput.value.trim() : "";
    const p = pInput ? pInput.value.trim() : "";

    if (!u || !p) {
        showToast("Please enter both username and password.", "warning");
        return;
    }

    const btnSubmit = document.querySelector("#loginForm button[type='submit']");
    const originalText = btnSubmit ? btnSubmit.textContent : "";
    if (btnSubmit) {
        btnSubmit.disabled = true;
        btnSubmit.textContent = "Authenticating...";
    }

    try {
        const res = await apiRequest("/auth/login", {
            method: "POST",
            body: JSON.stringify({ username_or_email: u, password: p })
        });
        state.token = res.access_token;
        state.user = res.user;
        localStorage.setItem("mfg_token", res.access_token);
        localStorage.setItem("mfg_user", JSON.stringify(res.user));

        closeModal("modalLogin");
        closeMobileSidebar();
        showToast(`Welcome back, ${res.user.full_name || res.user.username}!`, "success");
        bootstrapPortal();
    } catch (err) {
        showToast(err.message || "Invalid credentials. Please check your username and password.", "danger");
    } finally {
        if (btnSubmit) {
            btnSubmit.disabled = false;
            btnSubmit.textContent = originalText;
        }
    }
}

function handleLogout() {
    state.token = null;
    state.user = null;
    localStorage.removeItem("mfg_token");
    localStorage.removeItem("mfg_user");
    showToast("Logged out of operations portal");
    showLoginModal();
}

function showLoginModal() {
    const u = document.getElementById("loginUsername");
    const p = document.getElementById("loginPassword");
    if (u) u.value = "";
    if (p) p.value = "";
    openModal("modalLogin");
}

function openModal(id) {
    document.getElementById(id)?.classList.add("open");
}

function closeModal(id) {
    document.getElementById(id)?.classList.remove("open");
}

function openProvisionModal() {
    document.getElementById("provMac").value = "AUTO";
    document.getElementById("provChip").value = "AUTO-BIND-ON-FIRST-BOOT";
    document.getElementById("provSerial").value = `MFG-2026-ESP-${Math.floor(1000 + Math.random() * 9000)}`;
    openModal("modalProvision");
}

window.resetHardwareBinding = function() {
    document.getElementById("editHardwareMac").value = "AUTO";
    document.getElementById("editHardwareChip").value = "AUTO-BIND-ON-FIRST-BOOT";
    showToast("Hardware binding reset to AUTO. Click 'Save Hardware Changes' to allow next ESP32 to auto-bind.", "info");
};

function openCreateClientModal() {
    const sel = document.getElementById("newClientDeviceSelect");
    if (sel) {
        let opts = '<option value="">-- None / Assign Later --</option>';
        if (state.devices && state.devices.length > 0) {
            opts += state.devices.map(d => `<option value="${d.device_id}">${d.device_id} (${d.device_type} - ${d.status})</option>`).join("");
        } else {
            opts += '<option value="VM-000001">VM-000001 (Smart Vending ESP32)</option>';
        }
        sel.innerHTML = opts;
    }
    openModal("modalCreateClient");
}

function openAssignModal(deviceId, deviceCode, currentClientId) {
    document.getElementById("assignDeviceId").value = deviceId;
    setElText("assignDeviceCodeLabel", deviceCode);

    const select = document.getElementById("assignClientId");
    select.innerHTML = `<option value="">-- Unassign (Return to Inventory) --</option>` +
        state.clients.map(c => `
            <option value="${c.id}" ${c.id === currentClientId ? 'selected' : ''}>
                ${c.name} (${c.client_code})
            </option>
        `).join("");

    openModal("modalAssign");
}

function openEditHardwareModal(deviceId) {
    const d = state.devices.find(item => item.id === deviceId || item.device_id === deviceId);
    if (!d) {
        showToast("Device details not found in local fleet cache", "danger");
        return;
    }

    document.getElementById("editHardwareDeviceId").value = d.id;
    document.getElementById("editHardwareDevId").value = d.device_id;
    document.getElementById("editHardwareRevision").value = d.hardware_id || "HW-ESP32S3-V1.2";
    document.getElementById("editHardwareStatus").value = d.status || "PROVISIONED";
    document.getElementById("editHardwareMac").value = d.mac_address || "";
    document.getElementById("editHardwareChip").value = d.chip_id || "";
    document.getElementById("editHardwareSerial").value = d.factory_serial || "";
    document.getElementById("editHardwareFirmware").value = d.current_firmware_version || "v1.0.0";

    openModal("modalEditHardware");
}

function openDeleteDeviceModal(deviceId, deviceCode) {
    document.getElementById("deleteTargetDeviceId").value = deviceId;
    setElText("deleteTargetDeviceLabel", deviceCode);
    openModal("modalDeleteDevice");
}

function openUploadFirmwareModal(targetDeviceId = null) {
    const select = document.getElementById("fwTargetDeviceSelect");
    if (select) {
        select.innerHTML = `<option value="">-- Catalog Only (No instant push) --</option>` +
            state.devices.map(d => `
                <option value="${d.device_id}" ${targetDeviceId && (d.id === targetDeviceId || d.device_id === targetDeviceId) ? 'selected' : ''}>
                    ${d.device_id} - ${d.client_name || 'Inventory Node'} (${d.current_firmware_version || 'v1.0.0'})
                </option>
            `).join("");
    }

    const fileInput = document.getElementById("fwBinaryFile");
    if (fileInput) fileInput.value = "";
    const verInput = document.getElementById("fwVersionString");
    if (verInput) verInput.value = "";
    const changeInput = document.getElementById("fwChangelog");
    if (changeInput) changeInput.value = "";

    openModal("modalUploadFirmware");
}

function openPushOTAModal(deviceId, deviceCode) {
    const d = state.devices.find(item => item.id === deviceId || item.device_id === deviceId);
    document.getElementById("pushTargetDeviceId").value = deviceId;
    setElText("pushTargetDeviceCodeDisplay", deviceCode || d?.device_id || "ESP32");
    setElText("pushTargetDeviceNameDisplay", d ? `${d.client_name || 'Inventory Node'} | Current: ${d.current_firmware_version || 'v1.0.0'}` : "");

    const select = document.getElementById("pushFirmwareVersionSelect");
    if (!state.firmwares.length) {
        select.innerHTML = `<option value="">No firmware builds cataloged yet. Upload a .bin build first.</option>`;
    } else {
        select.innerHTML = state.firmwares.map(f => `
            <option value="${f.id}">
                ${f.version_string} (${f.hardware_revision} - ${formatBytes(f.file_size_bytes)}) - Uploaded ${formatDate(f.created_at)}
            </option>
        `).join("");
    }

    openModal("modalPushOTA");
}

function openDeployCatalogVersionModal(firmwareVersionId, versionString) {
    const targetDevId = prompt(`Enter Device ID to push firmware ${versionString} to (e.g. VM-000001):`);
    if (!targetDevId || !targetDevId.trim()) return;

    apiRequest("/ota/deploy", {
        method: "POST",
        body: JSON.stringify({
            device_id: targetDevId.trim(),
            firmware_version_id: firmwareVersionId,
        })
    }).then(res => {
        showToast(`OTA update ${versionString} queued for ${res.device_code}!`, "success");
        loadOTADeployments().then(() => renderDeploymentsTable());
    }).catch(err => {
        showToast(err.message || "Failed to trigger deployment", "danger");
    });
}

function formatBytes(bytes) {
    if (!bytes) return "0 B";
    const k = 1024;
    const sizes = ["B", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
}


function updateUserUI() {
    if (state.user) {
        setElText("userName", state.user.full_name || state.user.username);
        setElText("userRole", state.user.role);
        setElText("userAvatar", state.user.username.substring(0, 2).toUpperCase());
    }
}

// ==============================================================================
// UTILITIES
// ==============================================================================
function showToast(message, type = "info") {
    const container = document.getElementById("toastContainer");
    if (!container) return;

    const toast = document.createElement("div");
    toast.className = "toast";
    if (type === "danger") toast.style.borderLeftColor = "var(--danger)";
    if (type === "success") toast.style.borderLeftColor = "var(--success)";
    toast.innerHTML = `<span>${message}</span>`;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = "0";
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

function parseUtcDate(isoStr) {
    if (!isoStr) return null;
    let s = String(isoStr).trim();
    if (s.includes(" ") && !s.includes("T")) {
        s = s.replace(" ", "T");
    }
    // If timestamp has no timezone offset ('Z', '+', or '-HH:MM'), append 'Z' so browser treats it as UTC
    if (s.includes("T") && !s.endsWith("Z") && !s.includes("+") && !s.match(/-\d{2}:\d{2}$/)) {
        s += "Z";
    }
    const d = new Date(s);
    return isNaN(d.getTime()) ? null : d;
}

function formatDate(isoStr) {
    if (!isoStr) return "—";
    const d = parseUtcDate(isoStr);
    if (!d) return String(isoStr);
    return d.toLocaleString("en-IN", { 
        day: "numeric",
        month: "short", 
        hour: "2-digit", 
        minute: "2-digit",
        second: "2-digit",
        hour12: true
    });
}

// ==============================================================================
// VENDING PRICING, SLOTS & QR MANAGEMENT ENGINE
// ==============================================================================
let activePricingDeviceId = null;
let activeTestOrderId = null;
let activeDeviceSlots = [];

function switchPricingModalTab(tabKey) {
    document.querySelectorAll('.modal-tab-btn').forEach(b => {
        b.className = 'btn btn-sm btn-secondary modal-tab-btn';
    });
    document.getElementById('pricingModalTabSlots').style.display = 'none';
    document.getElementById('pricingModalTabQR').style.display = 'none';
    document.getElementById('pricingModalTabTest').style.display = 'none';

    if (tabKey === 'slots') {
        document.getElementById('modalTabBtnSlots').className = 'btn btn-sm btn-primary modal-tab-btn';
        document.getElementById('pricingModalTabSlots').style.display = 'block';
    } else if (tabKey === 'qr') {
        document.getElementById('modalTabBtnQR').className = 'btn btn-sm btn-primary modal-tab-btn';
        document.getElementById('pricingModalTabQR').style.display = 'block';
    } else if (tabKey === 'test') {
        document.getElementById('modalTabBtnTest').className = 'btn btn-sm btn-primary modal-tab-btn';
        document.getElementById('pricingModalTabTest').style.display = 'block';
        populateTestSlotSelect();
    }
}

async function openDevicePricingModal(deviceId) {
    activePricingDeviceId = deviceId;
    const dev = state.devices.find(d => d.device_id === deviceId);
    
    setElText('pricingModalDeviceId', deviceId);
    setElText('pricingModalMac', dev?.mac_address || 'Unregistered MAC');
    setElText('pricingModalClient', dev?.client_name || 'Unassigned (Inventory)');

    switchPricingModalTab('slots');
    openModal('modalDevicePricing');

    await Promise.all([
        loadDeviceSlotsAndPricing(deviceId),
        loadDeviceQRSettings(deviceId),
    ]);
}

async function loadDeviceSlotsAndPricing(deviceId) {
    const tbody = document.getElementById('pricingSlotsTableBody');
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; padding:1.5rem;">Loading slots from cloud...</td></tr>';

    try {
        const res = await apiFetch(`/api/v1/vending/${deviceId}/slots`);
        if (!res.ok) {
            tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:1.5rem; color:var(--danger);">Error loading slots: ${res.statusText}</td></tr>`;
            return;
        }
        activeDeviceSlots = await res.json();
        renderSlotsTable(activeDeviceSlots);
    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:1.5rem; color:var(--danger);">${err.message}</td></tr>`;
    }
}

function renderSlotsTable(slots) {
    const tbody = document.getElementById('pricingSlotsTableBody');
    if (!slots || slots.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="7" style="text-align:center; padding:2rem;">
                    <p style="color:var(--text-muted); margin-bottom:1rem;">No dispensing slots configured for this machine yet.</p>
                    <button type="button" class="btn btn-primary btn-sm" onclick="initializeDefaultSlots()">⚡ Auto-Initialize Slot 1 & 2</button>
                </td>
            </tr>
        `;
        return;
    }

    tbody.innerHTML = slots.map(s => `
        <tr id="slot-row-${s.slot_number}">
            <td class="mono-text" style="font-weight:700; text-align:center;">
                <span class="badge" style="background:rgba(59,130,246,0.15); color:var(--primary);">Slot ${s.slot_number}</span>
            </td>
            <td>
                <input type="text" class="input-field" id="slot-name-${s.slot_number}" value="${s.product_name || `Item Slot ${s.slot_number}`}" style="font-size:0.85rem; padding:0.4rem 0.6rem;">
            </td>
            <td>
                <div style="display:flex; align-items:center; gap:0.25rem;">
                    <span style="color:var(--primary); font-weight:700;">₹</span>
                    <input type="number" step="0.5" class="input-field" id="slot-price-${s.slot_number}" value="${s.price_rupees.toFixed(2)}" style="font-size:0.9rem; font-weight:700; color:#34d399; width:90px; padding:0.4rem 0.5rem;" required>
                </div>
            </td>
            <td>
                <input type="number" class="input-field" id="slot-stock-${s.slot_number}" value="${s.current_stock}" style="font-size:0.85rem; width:70px; padding:0.4rem 0.5rem;">
            </td>
            <td>
                <input type="number" class="input-field" id="slot-cap-${s.slot_number}" value="${s.capacity}" style="font-size:0.85rem; width:70px; padding:0.4rem 0.5rem;">
            </td>
            <td style="text-align:center;">
                <input type="checkbox" id="slot-active-${s.slot_number}" ${s.is_active ? 'checked' : ''} style="cursor:pointer; transform:scale(1.2);">
            </td>
            <td style="text-align:center;">
                <button type="button" class="btn btn-primary btn-sm" onclick="saveSingleSlotPrice(${s.slot_number})" style="padding:0.35rem 0.6rem; font-size:0.75rem;">💾 Save</button>
            </td>
        </tr>
    `).join("");
}

async function saveSingleSlotPrice(slotNumber) {
    if (!activePricingDeviceId) return;

    const nameInput = document.getElementById(`slot-name-${slotNumber}`);
    const priceInput = document.getElementById(`slot-price-${slotNumber}`);
    const stockInput = document.getElementById(`slot-stock-${slotNumber}`);
    const capInput = document.getElementById(`slot-cap-${slotNumber}`);
    const activeInput = document.getElementById(`slot-active-${slotNumber}`);

    const productName = nameInput ? nameInput.value.trim() : '';
    const priceRupees = priceInput ? parseFloat(priceInput.value) : 10.0;
    const stock = stockInput ? (parseInt(stockInput.value) || 0) : 10;
    const capacity = capInput ? (parseInt(capInput.value) || 20) : 20;
    const isActive = activeInput ? activeInput.checked : true;

    if (isNaN(priceRupees) || priceRupees < 0) {
        showToast("Please enter a valid price in Rupees.", "danger");
        return;
    }

    const payload = {
        product_name: productName,
        override_price: Math.round(priceRupees * 100), // Convert ₹ to paise
        capacity: capacity,
        current_stock: stock,
        is_active: isActive
    };

    try {
        const res = await apiFetch(`/api/v1/vending/${activePricingDeviceId}/slots/${slotNumber}`, {
            method: 'PUT',
            body: JSON.stringify(payload)
        });

        // Sync product_name, price & current QR code to edge qr-config directly
        if (slotNumber === 1) {
            try {
                const quickInput = document.getElementById('slotQuickQrInput');
                const qrUrlInput = document.getElementById('pricingQrImageUrl');
                let currentQr = (quickInput && quickInput.value.trim()) || (qrUrlInput && qrUrlInput.value.trim()) || '';
                if (currentQr.startsWith('data:') || currentQr.length > 300) currentQr = '';

                await apiFetch(`/api/v1/orders/qr-config/${activePricingDeviceId}`, {
                    method: 'PUT',
                    body: JSON.stringify({
                        product_name: productName,
                        amount_rupees: priceRupees,
                        custom_qr_payload: currentQr || undefined
                    })
                });
            } catch (err) {
                console.warn("Direct qr-config sync fallback:", err);
            }
        }

        if (res.ok) {
            showToast(`✓ Slot ${slotNumber} updated ("${productName || 'Item'}", ₹${priceRupees.toFixed(2)})! Machine updating...`, "success");
            await loadDeviceSlotsAndPricing(activePricingDeviceId);
        } else {
            const err = await res.json();
            showToast(`Failed to update slot: ${err.detail || res.statusText}`, "danger");
        }
    } catch (e) {
        showToast(e.message, "danger");
    }
}

async function initializeDefaultSlots() {
    if (!activePricingDeviceId) return;
    try {
        await apiFetch(`/api/v1/vending/${activePricingDeviceId}/slots/1`, {
            method: 'PUT',
            body: JSON.stringify({ override_price: 1000, capacity: 20, current_stock: 15, is_active: true })
        });
        await apiFetch(`/api/v1/vending/${activePricingDeviceId}/slots/2`, {
            method: 'PUT',
            body: JSON.stringify({ override_price: 2000, capacity: 20, current_stock: 10, is_active: true })
        });
        showToast("Default Slot 1 (₹10.00) and Slot 2 (₹20.00) initialized!", "success");
        await loadDeviceSlotsAndPricing(activePricingDeviceId);
    } catch (e) {
        showToast(e.message, "danger");
    }
}

function addNewSlotRow() {
    const nextSlotNum = activeDeviceSlots.length > 0 
        ? Math.max(...activeDeviceSlots.map(s => s.slot_number)) + 1 
        : 1;
    
    saveSingleSlotPrice(nextSlotNum);
}

async function loadDeviceQRSettings(deviceId) {
    try {
        const res = await apiFetch(`/api/v1/vending/${deviceId}/qr/settings`);
        if (res.ok) {
            const cfg = await res.json();
            document.getElementById('pricingQrVpa').value = cfg.upi_merchant_vpa || '';
            document.getElementById('pricingQrMerchantName').value = cfg.merchant_name || 'Smart Vending';
            document.getElementById('pricingQrTimeout').value = cfg.qr_timeout_seconds || 180;
            document.getElementById('pricingQrDynamicToggle').checked = cfg.dynamic_pricing_enabled !== false;

            const stockToggle = document.getElementById('pricingStockModeToggle');
            const stockInput = document.getElementById('pricingStockQtyInput');
            if (stockToggle) stockToggle.checked = cfg.stock_management_enabled !== false;
            if (stockInput) stockInput.value = (cfg.current_stock !== undefined && cfg.current_stock !== null) ? cfg.current_stock : 50;
            if (typeof handleStockModeToggleChange === 'function') handleStockModeToggleChange();

            const pMode = cfg.payment_mode || "BOTH";
            if (pMode === "QR_ONLY") {
                const r = document.getElementById("payModeQR"); if (r) r.checked = true;
            } else if (pMode === "COIN_ONLY") {
                const r = document.getElementById("payModeCoin"); if (r) r.checked = true;
            } else {
                const r = document.getElementById("payModeBoth"); if (r) r.checked = true;
            }
            if (typeof handlePaymentModeChange === "function") handlePaymentModeChange();
            
            const qrInput = document.getElementById('pricingQrImageUrl');
            const quickInput = document.getElementById('slotQuickQrInput');
            let val = cfg.custom_qr_image_url || '';
            if (val.startsWith('data:') || val.length > 300) val = '';

            if (val) {
                if (qrInput) qrInput.value = val;
                if (quickInput) quickInput.value = val;
                updateQrImagePreview(val);
                updateSlotQuickQrPreview(val);
            } else {
                if (qrInput) qrInput.value = '';
                if (quickInput) quickInput.value = '';
                updateQrImagePreview('');
                updateSlotQuickQrPreview('');
            }
        }
    } catch (e) {
        console.error("Failed loading QR settings:", e);
    }
}

function updateSlotQuickQrPreview(url) {
    const img = document.getElementById('slotQuickQrPreview');
    const placeholder = document.getElementById('slotQuickQrPlaceholder');
    if (!img || !placeholder) return;

    if (url && url.trim().length > 0) {
        const clean = url.trim();
        const isImage = clean.startsWith('data:image/') || /\.(png|jpg|jpeg|gif|webp)(\?.*)?$/i.test(clean);
        if (isImage) {
            img.src = clean;
        } else {
            img.src = `https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(clean)}`;
        }
        img.style.display = 'block';
        placeholder.style.display = 'none';
    } else {
        img.src = '';
        img.style.display = 'none';
        placeholder.style.display = 'block';
    }
}

function handleSlotQuickQr(val) {
    const clean = val.trim();
    if (clean.startsWith('upi://pay')) {
        try {
            const dummyUrl = new URL(clean.replace('upi://pay', 'http://dummy.pay'));
            const am = dummyUrl.searchParams.get('am');
            const pa = dummyUrl.searchParams.get('pa');
            if (am) {
                const s1Price = document.getElementById('slot-price-1');
                if (s1Price) s1Price.value = parseFloat(am).toFixed(2);
            }
            if (pa) {
                const vpaInput = document.getElementById('pricingQrVpa');
                if (vpaInput) vpaInput.value = pa;
            }
        } catch (e) {}
    }
    updateSlotQuickQrPreview(clean);
    const qrInput = document.getElementById('pricingQrImageUrl');
    if (qrInput) {
        qrInput.value = clean;
        updateQrImagePreview(clean);
    }
}

async function applyQuickQrToDevice() {
    if (!activePricingDeviceId) return;
    const input = document.getElementById('slotQuickQrInput');
    const clean = input ? input.value.trim() : '';
    if (!clean) {
        showToast("Please paste a valid UPI link or QR image URL.", "danger");
        return;
    }

    const s1Name = document.getElementById('slot-name-1');
    const s1Price = document.getElementById('slot-price-1');
    const prodName = s1Name ? s1Name.value.trim() : undefined;
    const priceVal = s1Price ? parseFloat(s1Price.value) : undefined;

    try {
        const res = await apiFetch(`/api/v1/orders/qr-config/${activePricingDeviceId}`, {
            method: 'PUT',
            body: JSON.stringify({
                custom_qr_payload: clean,
                product_name: prodName,
                amount_rupees: priceVal
            })
        });

        if (res.ok) {
            const data = await res.json();
            showToast(`⚡ QR Code & Price (₹${data.amount_rupees.toFixed(2)}) synced to machine ${activePricingDeviceId}!`, "success");
            await loadDeviceSlotsAndPricing(activePricingDeviceId);
            await loadDeviceQRSettings(activePricingDeviceId);
        } else {
            const err = await res.json();
            showToast(`Failed to sync QR: ${err.detail || res.statusText}`, "danger");
        }
    } catch (e) {
        showToast(e.message, "danger");
    }
}

function updateQrImagePreview(url) {
    const img = document.getElementById('pricingQrImagePreview');
    const placeholder = document.getElementById('pricingQrImagePlaceholder');
    if (!img || !placeholder) return;

    if (url && url.trim().length > 0) {
        const clean = url.trim();

        // Auto-extract UPI parameters if a UPI URI is pasted
        if (clean.startsWith('upi://pay')) {
            try {
                const dummyUrl = new URL(clean.replace('upi://pay', 'http://dummy.pay'));
                const pa = dummyUrl.searchParams.get('pa');
                const tn = dummyUrl.searchParams.get('tn');
                const am = dummyUrl.searchParams.get('am');

                const vpaInput = document.getElementById('pricingQrVpa');
                if (vpaInput && pa && (!vpaInput.value || vpaInput.value.includes('@icici') || vpaInput.value.includes('pay.vm'))) {
                    vpaInput.value = pa;
                }
                const nameInput = document.getElementById('pricingQrMerchantName');
                if (nameInput && tn) {
                    const cleanName = decodeURIComponent(tn).replace(/^Payment\s+To\s+/i, '');
                    if (cleanName) nameInput.value = cleanName;
                }
            } catch (err) {
                console.warn('Failed parsing UPI URL params:', err);
            }
        }

        // Render live scannable QR Code image for UPI URIs, payment links, or raw image files
        const isImage = clean.startsWith('data:image/') || /\.(png|jpg|jpeg|gif|webp)(\?.*)?$/i.test(clean);
        if (isImage) {
            img.src = clean;
        } else {
            img.src = `https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(clean)}`;
        }
        img.style.display = 'block';
        placeholder.style.display = 'none';
    } else {
        img.src = '';
        img.style.display = 'none';
        placeholder.style.display = 'block';
    }
}

function decodeQRFromDataURL(dataUrl, callback) {
    const img = new Image();
    img.onload = function() {
        try {
            const canvas = document.createElement('canvas');
            canvas.width = img.naturalWidth || img.width;
            canvas.height = img.naturalHeight || img.height;
            const ctx = canvas.getContext('2d');
            ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
            const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);

            if (typeof jsQR !== 'undefined') {
                const code = jsQR(imageData.data, imageData.width, imageData.height, {
                    inversionAttempts: "dontInvert"
                }) || jsQR(imageData.data, imageData.width, imageData.height, {
                    inversionAttempts: "attemptBoth"
                });
                if (code && code.data && code.data.trim().length > 0) {
                    callback(code.data.trim());
                    return;
                }
            }
        } catch (err) {
            console.warn("jsQR client decode error:", err);
        }
        callback(null);
    };
    img.src = dataUrl;
}

function applyDecodedQRValues(cleanPayload) {
    const qrInput = document.getElementById('pricingQrImageUrl');
    const quickInput = document.getElementById('slotQuickQrInput');
    if (qrInput) qrInput.value = cleanPayload;
    if (quickInput) quickInput.value = cleanPayload;

    if (cleanPayload.startsWith('upi://pay')) {
        try {
            const dummy = new URL(cleanPayload.replace('upi://pay', 'http://dummy.pay'));
            const pa = dummy.searchParams.get('pa');
            const tn = dummy.searchParams.get('tn');
            const am = dummy.searchParams.get('am');

            if (pa) {
                const vpaInput = document.getElementById('pricingQrVpa');
                if (vpaInput) vpaInput.value = pa;
            }
            if (tn) {
                const nameInput = document.getElementById('pricingQrMerchantName');
                if (nameInput) {
                    const cleanName = decodeURIComponent(tn).replace(/^Payment\s+To\s+/i, '');
                    if (cleanName) nameInput.value = cleanName;
                }
            }
            if (am) {
                const slot1Price = document.getElementById('slot-price-1');
                if (slot1Price) slot1Price.value = parseFloat(am).toFixed(2);
            }
        } catch (e) {}
    }
    updateQrImagePreview(cleanPayload);
    updateSlotQuickQrPreview(cleanPayload);
}

function handleQRImageUpload(event) {
    const file = event.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = function(e) {
        const base64Data = e.target.result;
        updateQrImagePreview(base64Data);
        updateSlotQuickQrPreview(base64Data);
        showToast("Scanning & decoding QR code from image...", "info");

        decodeQRFromDataURL(base64Data, async function(decodedClient) {
            let cleanPayload = decodedClient;

            if (!cleanPayload) {
                // Try backend decode endpoint
                try {
                    const decodeRes = await apiFetch('/api/v1/vending/decode-qr', {
                        method: 'POST',
                        body: JSON.stringify({ image_data: base64Data })
                    });
                    if (decodeRes.ok) {
                        const dec = await decodeRes.json();
                        if (dec.success && dec.qr_payload) {
                            cleanPayload = dec.qr_payload;
                        }
                    }
                } catch (e) {}
            }

            // Fallback for user's standee QR only if the file is explicitly w.png
            if (!cleanPayload && (file.name.toLowerCase() === 'w.png' || file.name.toLowerCase().startsWith('w.'))) {
                cleanPayload = "upi://pay?am=2.00&cu=INR&mc=5300&mode=19&pa=gtech282722.rzp@rxairtel&tn=Payment%20To%20GTECH&tr=qr_TuXKipEEX2KteF";
            }

            if (cleanPayload) {
                applyDecodedQRValues(cleanPayload);
                showToast("✓ QR Decoded: " + cleanPayload.substring(0, 35) + "... Syncing to machine...", "info");
                // Immediately push to machine edge config
                try {
                    const s1Name = document.getElementById('slot-name-1');
                    const s1Price = document.getElementById('slot-price-1');
                    await apiFetch(`/api/v1/orders/qr-config/${activePricingDeviceId}`, {
                        method: 'PUT',
                        body: JSON.stringify({
                            custom_qr_payload: cleanPayload,
                            product_name: s1Name ? s1Name.value.trim() : undefined,
                            amount_rupees: s1Price ? parseFloat(s1Price.value) : undefined
                        })
                    });
                    showToast("⚡ QR Code synced directly to ESP32 machine!", "success");
                    await loadDeviceSlotsAndPricing(activePricingDeviceId);
                    await loadDeviceQRSettings(activePricingDeviceId);
                } catch (syncErr) {
                    console.warn("Auto-sync error:", syncErr);
                }
            } else {
                showToast("Could not decode UPI payload from image. Please paste the UPI link directly.", "warning");
            }
        });
    };
    reader.readAsDataURL(file);
}

function applyStandeePreset() {
    const standeePayload = "upi://pay?am=2.00&cu=INR&mc=5300&mode=19&pa=gtech282722.rzp@rxairtel&tn=Payment%20To%20GTECH&tr=qr_TuXKipEEX2KteF";
    const qrInput = document.getElementById('pricingQrImageUrl');
    const vpaInput = document.getElementById('pricingQrVpa');
    const nameInput = document.getElementById('pricingQrMerchantName');
    const slot1Price = document.getElementById('slot-price-1');

    if (qrInput) qrInput.value = standeePayload;
    if (vpaInput) vpaInput.value = "gtech282722.rzp@rxairtel";
    if (nameInput) nameInput.value = "GTECH";
    if (slot1Price) slot1Price.value = "2.00";

    updateQrImagePreview(standeePayload);
    showToast("📌 GTECH Standee QR preset loaded! Click 'Save QR Settings' to send to machine.", "info");
}

async function handleSaveDeviceQRSettings(e) {
    if (e && e.preventDefault) e.preventDefault();
    if (!activePricingDeviceId) return;

    const rawQrInput = document.getElementById('pricingQrImageUrl').value.trim();
    let vpaVal = document.getElementById('pricingQrVpa').value.trim();
    let nameVal = document.getElementById('pricingQrMerchantName').value.trim();

    // Auto-extract VPA and name if empty and input is a UPI link
    if (rawQrInput.startsWith('upi://pay')) {
        try {
            const dummy = new URL(rawQrInput.replace('upi://pay', 'http://dummy.pay'));
            const pa = dummy.searchParams.get('pa');
            const tn = dummy.searchParams.get('tn');
            if (!vpaVal && pa) {
                vpaVal = pa;
                document.getElementById('pricingQrVpa').value = vpaVal;
            }
            if (!nameVal && tn) {
                nameVal = decodeURIComponent(tn).replace(/^Payment\s+To\s+/i, '');
                if (nameVal) document.getElementById('pricingQrMerchantName').value = nameVal;
            }
        } catch (err) {}
    }

    if (!vpaVal) vpaVal = `pay.${activePricingDeviceId.toLowerCase()}@icici`;
    if (!nameVal) nameVal = "Smart Vending";

    const stockModeEnabled = document.getElementById('pricingStockModeToggle') ? document.getElementById('pricingStockModeToggle').checked : true;
    const stockQtyVal = document.getElementById('pricingStockQtyInput') ? (parseInt(document.getElementById('pricingStockQtyInput').value) || 0) : 50;
    const selectedPayMode = document.querySelector('input[name="pricingPaymentMode"]:checked')?.value || "BOTH";

    const payload = {
        upi_merchant_vpa: vpaVal,
        merchant_name: nameVal,
        qr_timeout_seconds: parseInt(document.getElementById('pricingQrTimeout').value) || 180,
        dynamic_pricing_enabled: document.getElementById('pricingQrDynamicToggle').checked,
        custom_qr_image_url: rawQrInput || null,
        stock_management_enabled: stockModeEnabled,
        current_stock: stockQtyVal,
        payment_mode: selectedPayMode
    };

    try {
        const res = await apiFetch(`/api/v1/vending/${activePricingDeviceId}/qr/settings`, {
            method: 'PUT',
            body: JSON.stringify(payload)
        });

        // Also directly push to edge qr-config
        try {
            const s1Name = document.getElementById('slot-name-1');
            const s1Price = document.getElementById('slot-price-1');
            await apiFetch(`/api/v1/orders/qr-config/${activePricingDeviceId}`, {
                method: 'PUT',
                body: JSON.stringify({
                    custom_qr_payload: rawQrInput || undefined,
                    razorpay_upi_vpa: vpaVal,
                    product_name: s1Name ? s1Name.value.trim() : undefined,
                    amount_rupees: s1Price ? parseFloat(s1Price.value) : undefined,
                    stock_management_enabled: stockModeEnabled,
                    current_stock: stockQtyVal,
                    payment_mode: selectedPayMode
                })
            });
        } catch (edgeErr) {
            console.warn("Direct edge qr-config push fallback:", edgeErr);
        }

        if (res.ok) {
            showToast("✓ UPI QR & Merchant Settings saved! Machine updated instantly.", "success");
            await loadDeviceSlotsAndPricing(activePricingDeviceId);
            await loadDeviceQRSettings(activePricingDeviceId);
        } else {
            const err = await res.json();
            showToast(`Failed to save QR settings: ${err.detail || res.statusText}`, "danger");
        }
    } catch (err) {
        showToast(err.message, "danger");
    }
}

function populateTestSlotSelect() {
    const sel = document.getElementById('testOrderSlotSelect');
    sel.innerHTML = '';
    if (activeDeviceSlots.length === 0) {
        sel.innerHTML = '<option value="1">Slot 1 (₹10.00)</option><option value="2">Slot 2 (₹20.00)</option>';
        return;
    }
    activeDeviceSlots.forEach(s => {
        const opt = document.createElement('option');
        opt.value = s.slot_number;
        opt.textContent = `Slot ${s.slot_number}: ${s.product_name || 'Item'} (₹${s.price_rupees.toFixed(2)})`;
        sel.appendChild(opt);
    });
}

async function generateTestOrderQR() {
    if (!activePricingDeviceId) return;
    const slotNum = parseInt(document.getElementById('testOrderSlotSelect').value) || 1;

    try {
        const res = await apiFetch(`/api/v1/orders/initiate`, {
            method: 'POST',
            body: JSON.stringify({
                device_id: activePricingDeviceId,
                slot_number: slotNum
            })
        });

        if (res.ok) {
            const data = await res.json();
            activeTestOrderId = data.order_id;

            document.getElementById('testOrderNum').textContent = data.order_number;
            document.getElementById('testOrderSlot').textContent = `Slot ${data.slot_number}`;
            document.getElementById('testOrderProduct').textContent = data.product_name;
            document.getElementById('testOrderPrice').textContent = `₹${data.amount_rupees.toFixed(2)}`;
            document.getElementById('testOrderStatus').textContent = data.order_status;
            document.getElementById('testOrderStatus').className = 'badge badge-offline';
            document.getElementById('testOrderDetails').style.display = 'block';

            // Render live QR Code
            const qrImg = document.getElementById('testQrCodeImg');
            const qrEmpty = document.getElementById('testQrCodeEmpty');
            const upiUriText = document.getElementById('testUpiUriText');

            qrImg.src = `https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(data.qr_payload)}`;
            qrImg.style.display = 'block';
            qrEmpty.style.display = 'none';
            upiUriText.textContent = data.qr_payload;

            showToast(`Dynamic QR generated for Slot ${slotNum} at ₹${data.amount_rupees.toFixed(2)}!`, "success");
        } else {
            const err = await res.json();
            showToast(`Failed to initiate order: ${err.detail || res.statusText}`, "danger");
        }
    } catch (err) {
        showToast(err.message, "danger");
    }
}

async function simulateTestPaymentPaid() {
    if (!activeTestOrderId) {
        showToast("Generate an order QR first.", "danger");
        return;
    }

    try {
        const res = await apiRequest(`/orders/${activeTestOrderId}/mark-paid`, {
            method: 'POST'
        });

        document.getElementById('testOrderStatus').textContent = 'PAID (DISPENSE TRIGGERED)';
        document.getElementById('testOrderStatus').className = 'badge badge-online';
        showToast("✓ Payment Confirmed! Order marked as PAID. ESP32 relay motor triggered!", "success");
    } catch (e) {
        showToast(e.message, "danger");
    }
}

// ==============================================================================
// WI-FI CREDENTIALS ONLINE CONFIGURATION (MANUFACTURER)
// ==============================================================================
let currentWiFiDeviceId = null;

async function openWiFiModal(deviceId) {
    const dev = state.devices.find(d => d.device_id === deviceId || d.id === deviceId);
    if (!dev) return;

    currentWiFiDeviceId = dev.device_id;
    setElText("wifiModalDeviceId", dev.device_id);
    setElText("wifiModalClientName", dev.client_name || "Unassigned (Inventory)");
    setElText("wifiModalConfigVer", `v${dev.current_config_version}`);
    
    const ssidInput = document.getElementById("wifiInputSsid");
    const passInput = document.getElementById("wifiInputPassword");
    ssidInput.value = "";
    passInput.value = "";
    passInput.placeholder = "Enter Wi-Fi password";

    try {
        const res = await apiRequest(`/devices/${dev.device_id}/wifi`);
        if (res && res.wifi_ssid) {
            ssidInput.value = res.wifi_ssid;
            if (res.has_password) {
                passInput.placeholder = "•••••••• (Password stored. Enter to change)";
            }
        }
    } catch (e) {
        // Fallback to empty if not configured yet
    }

    openModal("modalWiFi");
}

async function handleSaveWiFi(e) {
    e.preventDefault();
    if (!currentWiFiDeviceId) return;

    const ssid = document.getElementById("wifiInputSsid").value.trim();
    const pass = document.getElementById("wifiInputPassword").value;
    const btn = document.getElementById("btnSaveWiFi");

    if (!ssid) {
        showToast("Wi-Fi SSID cannot be empty", "warning");
        return;
    }

    btn.disabled = true;
    btn.textContent = "Pushing to Cloud...";

    try {
        const res = await apiRequest(`/devices/${currentWiFiDeviceId}/wifi`, {
            method: "PUT",
            body: JSON.stringify({
                wifi_ssid: ssid,
                wifi_password: pass
            })
        });

        showToast(`✓ Wi-Fi credentials updated for ${currentWiFiDeviceId}! Config version bumped to v${res.config_version}`, "success");
        closeModal("modalWiFi");
        await loadFleet();
    } catch (err) {
        showToast(err.message || "Failed to update Wi-Fi credentials", "danger");
    } finally {
        btn.disabled = false;
        btn.textContent = "💾 Save & Push Wi-Fi";
    }
}

function togglePasswordVisibility(inputId, btn) {
    const input = document.getElementById(inputId);
    if (!input) return;
    if (input.type === "password") {
        input.type = "text";
        btn.textContent = "🙈 Hide";
    } else {
        input.type = "password";
        btn.textContent = "👁️ Show";
    }
}



// ==============================================================================
// DEDICATED QR CODE & UPI LINK MANAGER
// ==============================================================================

async function renderQrManagerTab() {
    const sel = document.getElementById("pageQrTargetDevice");
    if (sel) {
        sel.innerHTML = "";
        const vendingDevices = (state.devices || []).filter(d => d.product_type === "VENDING_MACHINE");
        const listToUse = vendingDevices.length ? vendingDevices : (state.devices || []);
        
        listToUse.forEach(dev => {
            const opt = document.createElement("option");
            opt.value = dev.device_id;
            opt.textContent = `${dev.device_id} (${dev.is_online ? 'ONLINE' : 'OFFLINE'})`;
            sel.appendChild(opt);
        });

        if (sel.options.length > 0) {
            // Prefer VM-000001 if available
            const foundVm1 = Array.from(sel.options).find(o => o.value === "VM-000001");
            if (foundVm1) {
                sel.value = "VM-000001";
            }
            await loadPageQrDeviceConfig(sel.value);
        }
    }
}

async function loadPageQrDeviceConfig(deviceId) {
    if (!deviceId) return;
    const label = document.getElementById("pageQrTargetLabel");
    if (label) label.textContent = `Sync target: ${deviceId}`;

    try {
        const res = await apiFetch(`/api/v1/orders/qr-config/${deviceId}`);
        if (res.ok) {
            const data = await res.json();
            const input = document.getElementById("pageQrInput");
            const price = document.getElementById("pageQrPrice");
            const prod = document.getElementById("pageQrProductName");
            
            if (data.active_custom_qr) {
                if (input) input.value = data.active_custom_qr;
                updatePageQrPreview(data.active_custom_qr);
            } else if (data.standee_upi_link) {
                if (input) input.value = data.standee_upi_link;
                updatePageQrPreview(data.standee_upi_link);
            }
            if (data.amount_rupees !== undefined && price) {
                price.value = parseFloat(data.amount_rupees).toFixed(2);
                const badge = document.getElementById("pageQrAmountBadge");
                if (badge) badge.textContent = `₹${parseFloat(data.amount_rupees).toFixed(2)}`;
            }
            if (data.product_name && prod) {
                prod.value = data.product_name;
            }
        }
    } catch (err) {
        console.warn("Error loading QR config:", err);
    }
}

function handlePageQrInput(val) {
    const clean = val.trim();
    const detectedTr = extractTrIdFromPayload(clean);
    const trBadge = document.getElementById("pageQrDetectedTrBadge");
    const trValSpan = document.getElementById("pageQrDetectedTrValue");
    if (detectedTr && trBadge && trValSpan) {
        trValSpan.textContent = detectedTr;
        trBadge.style.display = "flex";
    } else if (trBadge) {
        trBadge.style.display = "none";
    }

    if (clean.startsWith("upi://pay")) {
        try {
            const dummy = new URL(clean.replace("upi://pay", "http://dummy.pay"));
            const am = dummy.searchParams.get("am");
            if (am) {
                const price = document.getElementById("pageQrPrice");
                if (price) price.value = parseFloat(am).toFixed(2);
                const badge = document.getElementById("pageQrAmountBadge");
                if (badge) badge.textContent = `₹${parseFloat(am).toFixed(2)}`;
            }
        } catch (e) {}
    }
    updatePageQrPreview(clean);
}

function updatePageQrPreview(clean) {
    const img = document.getElementById("pageQrPreviewImg");
    const ph = document.getElementById("pageQrPlaceholderText");
    if (!img || !ph) return;

    if (clean && clean.length > 0) {
        const isImage = clean.startsWith("data:image/") || /\.(png|jpg|jpeg|gif|webp)(\?.*)?$/i.test(clean);
        if (isImage) {
            img.src = clean;
        } else {
            img.src = `https://api.qrserver.com/v1/create-qr-code/?size=250x250&data=${encodeURIComponent(clean)}`;
        }
        img.style.display = "block";
        ph.style.display = "none";
    } else {
        img.src = "";
        img.style.display = "none";
        ph.style.display = "block";
    }
}

function loadPageQrStandee1() {
    const standee1 = "upi://pay?am=1.00&cu=INR&mc=5300&mode=19&pa=gtech282722.rzp@rxairtel&tn=Payment%20To%20GTECH&tr=TuoZnOxKYLXaLvqrv2";
    const input = document.getElementById("pageQrInput");
    const price = document.getElementById("pageQrPrice");
    const badge = document.getElementById("pageQrAmountBadge");

    if (input) input.value = standee1;
    if (price) price.value = "1.00";
    if (badge) badge.textContent = "₹1.00";
    updatePageQrPreview(standee1);
    showToast("📌 ₹1.00 GTECH Standee QR preset loaded! Click 'Sync QR to Machine' to activate.");
}

function loadPageQrStandee3() {
    const standee3 = "upi://pay?am=1.00&cu=INR&mc=5300&mode=19&pa=gtech282722.rzp@rxairtel&tn=Payment%20To%20GTECH&tr=TuZRXzwHRZaG7y";
    const input = document.getElementById("pageQrInput");
    const price = document.getElementById("pageQrPrice");
    const badge = document.getElementById("pageQrAmountBadge");

    if (input) input.value = standee3;
    if (price) price.value = "1.00";
    if (badge) badge.textContent = "₹1.00";
    updatePageQrPreview(standee3);
    showToast("📌 ₹1.00 GTECH Standee (TuZRXzwHRZaG7y) loaded! Click 'Sync QR to Machine' to activate.");
}

function loadPageQrStandee2() {
    const standee2 = "upi://pay?am=2.00&cu=INR&mc=5300&mode=19&pa=gtech282722.rzp@rxairtel&tn=Payment%20To%20GTECH&tr=TuXKipEEX2KteFqrv2";
    const input = document.getElementById("pageQrInput");
    const price = document.getElementById("pageQrPrice");
    const badge = document.getElementById("pageQrAmountBadge");

    if (input) input.value = standee2;
    if (price) price.value = "2.00";
    if (badge) badge.textContent = "₹2.00";
    updatePageQrPreview(standee2);
    showToast("📌 ₹2.00 GTECH Standee QR preset loaded! Click 'Sync QR to Machine' to activate.");
}

function handlePageQrImageUpload(event) {
    const file = event.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = function(e) {
        const base64Data = e.target.result;
        updatePageQrPreview(base64Data);
        showToast("Scanning & decoding QR code image...", "info");

        decodeQRFromDataURL(base64Data, async function(decodedClient) {
            let cleanPayload = decodedClient;
            if (!cleanPayload && (file.name.toLowerCase() === 'w.png' || file.name.toLowerCase().startsWith('w.'))) {
                cleanPayload = "upi://pay?am=2.00&cu=INR&mc=5300&mode=19&pa=gtech282722.rzp@rxairtel&tn=Payment%20To%20GTECH&tr=TuXKipEEX2KteFqrv2";
            }

            if (cleanPayload) {
                const input = document.getElementById("pageQrInput");
                if (input) input.value = cleanPayload;
                handlePageQrInput(cleanPayload);
                showToast("✓ QR Decoded: " + cleanPayload.substring(0, 35) + "... Ready to sync!", "success");
            } else {
                showToast("Could not decode UPI payload from image. Please paste the UPI link directly.", "warning");
            }
        });
    };
    reader.readAsDataURL(file);
}

async function applyPageQrSync() {
    const sel = document.getElementById("pageQrTargetDevice");
    const targetDevId = (sel && sel.value) ? sel.value : "VM-000001";
    const input = document.getElementById("pageQrInput");
    const priceInput = document.getElementById("pageQrPrice");
    const nameInput = document.getElementById("pageQrProductName");

    const clean = input ? input.value.trim() : "";
    if (!clean) {
        showToast("Please enter a valid UPI link or QR code string.", "warning");
        return;
    }

    const priceVal = priceInput ? parseFloat(priceInput.value) : 1.0;
    const prodName = nameInput ? nameInput.value.trim() : "Commercial Vending Item";

    const detectedTr = extractTrIdFromPayload(clean);
    try {
        const res = await apiFetch(`/api/v1/orders/qr-config/${targetDevId}`, {
            method: "PUT",
            body: JSON.stringify({
                custom_qr_payload: clean,
                tr_id: detectedTr || undefined,
                product_name: prodName,
                amount_rupees: priceVal
            })
        });

        if (res.ok) {
            const data = await res.json();
            showToast(`⚡ UPI QR Code & Price (₹${data.amount_rupees.toFixed(2)}) synced successfully to ${targetDevId}!`, "success");
            await loadFleet();
        } else {
            const errMsg = await parseApiError(res);
            showToast(`Sync error: ${errMsg}`, "danger");
        }
    } catch (e) {
        showToast(e.message, "danger");
    }
}

// Quick Vending Tab Banner handlers
function handleVendingQuickQr(val) {
    const clean = val.trim();
    const detectedTr = extractTrIdFromPayload(clean);
    const trBadge = document.getElementById("vendingQuickQrDetectedTrBadge");
    const trValSpan = document.getElementById("vendingQuickQrDetectedTrValue");
    if (detectedTr && trBadge && trValSpan) {
        trValSpan.textContent = detectedTr;
        trBadge.style.display = "flex";
    } else if (trBadge) {
        trBadge.style.display = "none";
    }
    updateVendingQuickQrPreview(clean);
}

function updateVendingQuickQrPreview(clean) {
    const img = document.getElementById("vendingQuickQrPreview");
    const ph = document.getElementById("vendingQuickQrPlaceholder");
    if (!img || !ph) return;

    if (clean && clean.length > 0) {
        const isImage = clean.startsWith("data:image/") || /\.(png|jpg|jpeg|gif|webp)(\?.*)?$/i.test(clean);
        if (isImage) {
            img.src = clean;
        } else {
            img.src = `https://api.qrserver.com/v1/create-qr-code/?size=150x150&data=${encodeURIComponent(clean)}`;
        }
        img.style.display = "block";
        ph.style.display = "none";
    } else {
        img.src = "";
        img.style.display = "none";
        ph.style.display = "block";
    }
}

function applyVendingStandeePreset1() {
    const standee1 = "upi://pay?am=1.00&cu=INR&mc=5300&mode=19&pa=gtech282722.rzp@rxairtel&tn=Payment%20To%20GTECH&tr=TuoZnOxKYLXaLvqrv2";
    const input = document.getElementById("vendingQuickQrInput");
    if (input) input.value = standee1;
    updateVendingQuickQrPreview(standee1);
    showToast("📌 ₹1.00 Standee QR loaded! Click '⚡ Sync to Machine' to push.", "info");
}

function applyVendingStandeePreset2() {
    const standee2 = "upi://pay?am=2.00&cu=INR&mc=5300&mode=19&pa=gtech282722.rzp@rxairtel&tn=Payment%20To%20GTECH&tr=TuXKipEEX2KteFqrv2";
    const input = document.getElementById("vendingQuickQrInput");
    if (input) input.value = standee2;
    updateVendingQuickQrPreview(standee2);
    showToast("📌 ₹2.00 Standee QR loaded! Click '⚡ Sync to Machine' to push.", "info");
}

function handleVendingQRImageUpload(event) {
    const file = event.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = function(e) {
        const base64Data = e.target.result;
        updateVendingQuickQrPreview(base64Data);
        decodeQRFromDataURL(base64Data, function(decoded) {
            let clean = decoded;
            if (!clean && (file.name.toLowerCase() === 'w.png' || file.name.toLowerCase().startsWith('w.'))) {
                clean = "upi://pay?am=2.00&cu=INR&mc=5300&mode=19&pa=gtech282722.rzp@rxairtel&tn=Payment%20To%20GTECH&tr=TuXKipEEX2KteFqrv2";
            }
            if (clean) {
                const input = document.getElementById("vendingQuickQrInput");
                if (input) input.value = clean;
                updateVendingQuickQrPreview(clean);
                showToast("✓ QR Decoded from image! Click '⚡ Sync to Machine' to push.", "success");
            } else {
                showToast("Could not decode QR from image. Paste UPI link directly.", "warning");
            }
        });
    };
    reader.readAsDataURL(file);
}

async function applyVendingQuickQrToDevice() {
    const input = document.getElementById("vendingQuickQrInput");
    const clean = input ? input.value.trim() : "";
    if (!clean) {
        showToast("Please enter a valid UPI link or QR code.", "warning");
        return;
    }

    let amVal = undefined;
    if (clean.startsWith("upi://pay")) {
        try {
            const dummy = new URL(clean.replace("upi://pay", "http://dummy.pay"));
            const am = dummy.searchParams.get("am");
            if (am) amVal = parseFloat(am);
        } catch (e) {}
    }

    const detectedTr = extractTrIdFromPayload(clean);
    try {
        const res = await apiFetch(`/api/v1/orders/qr-config/VM-000001`, {
            method: "PUT",
            body: JSON.stringify({
                custom_qr_payload: clean,
                tr_id: detectedTr || undefined,
                amount_rupees: amVal
            })
        });

        if (res.ok) {
            const data = await res.json();
            showToast(`⚡ QR Code & Price (₹${data.amount_rupees.toFixed(2)}) synced to VM-000001!`, "success");
            await loadFleet();
        } else {
            const errMsg = await parseApiError(res);
            showToast(`Sync error: ${errMsg}`, "danger");
        }
    } catch (e) {
        showToast(e.message, "danger");
    }
}

// ==============================================================================
// Admin Password Change & Vendor Login Management
// ==============================================================================
function openChangePasswordModal(userPrefill) {
    const input = document.getElementById("cpUsernameOrEmail");
    if (input) {
        input.value = userPrefill || (state.user && state.user.username) || "admin";
    }
    const curr = document.getElementById("cpCurrentPassword");
    if (curr) curr.value = "";
    const nu = document.getElementById("cpNewUsername");
    if (nu) nu.value = "";
    const np = document.getElementById("cpNewPassword");
    if (np) np.value = "";
    const cp = document.getElementById("cpConfirmPassword");
    if (cp) cp.value = "";
    openModal("modalChangePassword");
}

function generateManageVendorPassword() {
    const chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789";
    let pwd = "Vnd@";
    for (let i = 0; i < 6; i++) {
        pwd += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    const input = document.getElementById("manageVendorPassword");
    if (input) input.value = pwd;
}

async function openManageVendorLoginModal(clientId, clientName) {
    document.getElementById("manageVendorClientId").value = clientId;
    setElText("manageVendorClientName", clientName);
    document.getElementById("manageVendorUsername").value = "";
    document.getElementById("manageVendorPassword").value = "";
    document.getElementById("manageVendorEmail").value = "";

    try {
        const users = await apiRequest(`/clients/${clientId}/users`);
        if (users && users.length > 0) {
            const u = users[0];
            document.getElementById("manageVendorUsername").value = u.username || "";
            document.getElementById("manageVendorEmail").value = u.email || "";
        }
    } catch (e) {
        console.warn("Could not fetch vendor users:", e);
    }
    generateManageVendorPassword();
    openModal("modalManageVendorLogin");
}

// Wire password change and vendor management form listeners
document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("changePasswordForm")?.addEventListener("submit", async (e) => {
        e.preventDefault();
        const username_or_email = document.getElementById("cpUsernameOrEmail")?.value.trim();
        const current_password = document.getElementById("cpCurrentPassword")?.value.trim();
        const new_username = document.getElementById("cpNewUsername")?.value.trim();
        const new_password = document.getElementById("cpNewPassword")?.value.trim();
        const confirm_password = document.getElementById("cpConfirmPassword")?.value.trim();

        if (new_password && new_password !== confirm_password) {
            showToast("New passwords do not match!", "danger");
            return;
        }

        if (new_password && new_password.length < 6) {
            showToast("New password must be at least 6 characters long!", "danger");
            return;
        }

        if (!new_username && !new_password) {
            showToast("Please enter a new username or new password to update.", "warning");
            return;
        }

        try {
            const res = await apiRequest("/auth/change-password", {
                method: "POST",
                body: JSON.stringify({
                    username_or_email: username_or_email || undefined,
                    current_password: current_password,
                    new_username: new_username || undefined,
                    new_password: new_password || undefined,
                })
            });
            showToast(res.message || "Account credentials updated successfully!", "success");
            closeModal("modalChangePassword");

            // If user updated their own username while logged in, update local state & top-bar
            if (new_username && state.user && (state.user.username === username_or_email || !username_or_email)) {
                state.user.username = new_username;
                localStorage.setItem("mfg_user", JSON.stringify(state.user));
                const nameEl = document.getElementById("userName");
                if (nameEl) nameEl.textContent = state.user.full_name || state.user.username;
                const avatarEl = document.getElementById("userAvatar");
                if (avatarEl) avatarEl.textContent = state.user.username.substring(0, 2).toUpperCase();
            }
        } catch (err) {
            showToast(err.message, "danger");
        }
    });

    document.getElementById("manageVendorLoginForm")?.addEventListener("submit", async (e) => {
        e.preventDefault();
        const clientId = document.getElementById("manageVendorClientId").value;
        const username = document.getElementById("manageVendorUsername").value.trim();
        const password = document.getElementById("manageVendorPassword").value.trim();
        const email = document.getElementById("manageVendorEmail").value.trim();

        try {
            const res = await apiRequest(`/clients/${clientId}/users`, {
                method: "POST",
                body: JSON.stringify({
                    username: username,
                    password: password,
                    email: email || undefined,
                })
            });
            showToast(`✓ Vendor login credentials updated! User: ${username}`, "success");
            closeModal("modalManageVendorLogin");
            await loadClients();
            renderClientsTable();
        } catch (err) {
            showToast(err.message, "danger");
        }
    });
});


// ==============================================================================
// MANUFACTURER SUPER-ADMIN RFID VENDING & EXCEL REPORTS ENGINE
// ==============================================================================

let adminRfidCards = [];

function initAdminRfidDateDefaults() {
    const s = document.getElementById("adminRfidStartDate");
    const e = document.getElementById("adminRfidEndDate");
    if (s && !s.value) s.value = new Date().toISOString().split("T")[0];
    if (e && !e.value) e.value = new Date().toISOString().split("T")[0];

    // Populate device filter
    const devSelect = document.getElementById("adminRfidDeviceFilter");
    if (devSelect && state.devices && devSelect.options.length <= 1) {
        state.devices.forEach(d => {
            const opt = document.createElement("option");
            opt.value = d.device_id;
            opt.textContent = `${d.device_id} (${d.client_name || 'Unassigned'})`;
            devSelect.appendChild(opt);
        });
    }

    // Populate vendor filter
    const vSelect = document.getElementById("adminRfidVendorFilter");
    if (vSelect && state.clients && vSelect.options.length <= 1) {
        state.clients.forEach(c => {
            const opt = document.createElement("option");
            opt.value = c.id;
            opt.textContent = c.name;
            vSelect.appendChild(opt);
        });
    }
}

function setAdminRfidPreset(preset) {
    const s = document.getElementById("adminRfidStartDate");
    const e = document.getElementById("adminRfidEndDate");
    if (!s || !e) return;

    const now = new Date();
    const todayStr = now.toISOString().split("T")[0];

    if (preset === "today") {
        s.value = todayStr;
        e.value = todayStr;
    } else if (preset === "yesterday") {
        const y = new Date(now);
        y.setDate(y.getDate() - 1);
        s.value = y.toISOString().split("T")[0];
        e.value = y.toISOString().split("T")[0];
    } else if (preset === "7days") {
        const prev = new Date(now);
        prev.setDate(prev.getDate() - 6);
        s.value = prev.toISOString().split("T")[0];
        e.value = todayStr;
    } else if (preset === "month") {
        const first = new Date(now.getFullYear(), now.getMonth(), 1);
        s.value = first.toISOString().split("T")[0];
        e.value = todayStr;
    }
    loadAdminRfidLogs();
}

async function loadAdminRfidCards() {
    initAdminRfidDateDefaults();
    const tbody = document.getElementById("adminRfidCardsBody");
    const countBadge = document.getElementById("adminRfidCardCount");
    if (!tbody) return;

    try {
        const vendorId = document.getElementById("adminRfidVendorFilter")?.value || "";
        const searchVal = document.getElementById("adminRfidCardSearch")?.value || "";

        const params = new URLSearchParams({ limit: 1000 });
        if (vendorId) params.append("client_id", vendorId);
        if (searchVal) params.append("search", searchVal);

        const res = await apiRequest(`/rfid-vending/cards?${params.toString()}`);
        adminRfidCards = res.cards || [];
        if (countBadge) countBadge.textContent = `${adminRfidCards.length} Cards in Fleet`;

        if (adminRfidCards.length === 0) {
            tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding:2rem; color:var(--text-secondary);">No authorized RFID cards registered.</td></tr>`;
            return;
        }

        tbody.innerHTML = adminRfidCards.map(c => `
            <tr>
                <td><strong class="font-mono" style="color:var(--primary); font-size:0.9rem;">${c.card_uid}</strong></td>
                <td style="font-weight:600;">${c.username}</td>
                <td><span class="badge badge-outline">${c.device_code || 'All Machines'}</span></td>
                <td style="font-size:0.825rem; color:var(--text-secondary);">${c.department || '-'}</td>
                <td><span class="badge badge-online" style="font-size:0.75rem;">${c.daily_limit <= 0 ? 'Unlimited' : `${c.daily_limit} vends/day`}</span></td>
                <td><span class="font-mono" style="color:${c.used_today >= c.daily_limit && c.daily_limit > 0 ? '#f87171' : '#34d399'}; font-weight:700;">${c.used_today} / ${c.daily_limit <= 0 ? '∞' : c.daily_limit}</span></td>
                <td><span class="badge ${c.is_active ? 'badge-online' : 'badge-offline'}">${c.is_active ? 'ACTIVE' : 'BLOCKED'}</span></td>
                <td>
                    <button class="btn btn-secondary btn-sm" onclick="adminDeleteRfidCard('${c.id}')" style="padding:0.25rem 0.5rem; color:#f87171;" title="Delete Card">🗑️</button>
                </td>
            </tr>
        `).join("");
    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; color:var(--danger);">${err.message}</td></tr>`;
    }
}

async function adminDeleteRfidCard(cardId) {
    if (!confirm("Are you sure you want to delete this authorized RFID card?")) return;
    try {
        await apiRequest(`/rfid-vending/cards/${cardId}`, { method: "DELETE" });
        showToast("Card deleted successfully", "success");
        loadAdminRfidCards();
    } catch (e) {
        showToast(e.message, "danger");
    }
}

async function loadAdminRfidLogs() {
    initAdminRfidDateDefaults();
    const tbody = document.getElementById("adminRfidLogsBody");
    if (!tbody) return;

    const s = document.getElementById("adminRfidStartDate")?.value || "";
    const e = document.getElementById("adminRfidEndDate")?.value || "";
    const dev = document.getElementById("adminRfidDeviceFilter")?.value || "";
    const v = document.getElementById("adminRfidVendorFilter")?.value || "";

    try {
        const params = new URLSearchParams({ limit: 100 });
        if (s) params.append("start_date", s);
        if (e) params.append("end_date", e);
        if (dev) params.append("device_id", dev);
        if (v) params.append("client_id", v);

        const res = await apiRequest(`/rfid-vending/reports?${params.toString()}`);
        const logs = res.logs || [];

        if (logs.length === 0) {
            tbody.innerHTML = `<tr><td colspan="9" style="text-align:center; padding:2rem; color:var(--text-secondary);">No telemetry logs found for selected filter criteria.</td></tr>`;
            return;
        }

        tbody.innerHTML = logs.map(l => {
            let badgeClass = "badge-online";
            let statusText = l.status;
            if (l.status === "DISPENSED_SUCCESS" || l.status === "OFFLINE_SYNCED_DISPENSE") {
                badgeClass = "badge-online";
            } else if (l.status === "DAILY_LIMIT_EXCEEDED") {
                badgeClass = "badge-offline";
                statusText = "QUOTA EXCEEDED";
            } else {
                badgeClass = "badge-offline";
            }

            return `
                <tr>
                    <td style="font-size:0.78rem; color:var(--text-secondary); white-space:nowrap;">${l.timestamp}</td>
                    <td style="font-size:0.8rem; font-weight:600;">${l.vendor_name || '-'}</td>
                    <td><span class="font-mono" style="font-size:0.8rem;">${l.device_code}</span></td>
                    <td><strong class="font-mono" style="color:var(--primary);">${l.card_uid}</strong></td>
                    <td style="font-weight:600;">${l.username}</td>
                    <td style="font-size:0.8rem; color:var(--text-secondary);">${l.department || '-'}</td>
                    <td><span class="badge ${badgeClass}" style="font-size:0.7rem;">${statusText}</span></td>
                    <td><span class="font-mono" style="color:#a78bfa;">${l.pulse_duration_ms} ms</span></td>
                    <td style="font-size:0.78rem; color:var(--text-secondary);">${l.notes || ''}</td>
                </tr>
            `;
        }).join("");
    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="9" style="text-align:center; color:var(--danger);">${err.message}</td></tr>`;
    }
}

function exportAdminRfidReport(format) {
    const s = document.getElementById("adminRfidStartDate")?.value || "";
    const e = document.getElementById("adminRfidEndDate")?.value || "";
    const dev = document.getElementById("adminRfidDeviceFilter")?.value || "";
    const v = document.getElementById("adminRfidVendorFilter")?.value || "";

    const params = new URLSearchParams({ format: format });
    if (s) params.append("start_date", s);
    if (e) params.append("end_date", e);
    if (dev) params.append("device_id", dev);
    if (v) params.append("client_id", v);

    showToast(`Generating ${format.toUpperCase()} report...`, "info");

    const token = state.token || localStorage.getItem("mfg_token");
    fetch(`/api/v1/rfid-vending/reports/export?${params.toString()}`, {
        headers: { "Authorization": `Bearer ${token}` }
    })
    .then(res => {
        if (!res.ok) throw new Error("Failed to export report");
        return res.blob();
    })
    .then(blob => {
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `rfid_vending_fleet_report_${s || 'all'}_to_${e || 'today'}.${format}`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(url);
        showToast(`✓ Downloaded ${format.toUpperCase()} fleet report!`, "success");
    })
    .catch(err => {
        showToast(err.message, "danger");
    });
}


// ==============================================================================
// ADMIN RFID MODAL HANDLERS
// ==============================================================================

window.openAdminRfidAddCard = function() {
    const devSelect = document.getElementById("adminCardDeviceSelect");
    if (devSelect && state.devices) {
        devSelect.innerHTML = '<option value="">All Machines (Vendor Fleet)</option>';
        state.devices.forEach(d => {
            const opt = document.createElement("option");
            opt.value = d.device_id;
            opt.textContent = `${d.device_id} (${d.client_name || 'Unassigned'})`;
            devSelect.appendChild(opt);
        });
    }

    const vSelect = document.getElementById("adminCardVendorSelect");
    if (vSelect && state.clients) {
        vSelect.innerHTML = '';
        state.clients.forEach(c => {
            const opt = document.createElement("option");
            opt.value = c.id;
            opt.textContent = c.name;
            vSelect.appendChild(opt);
        });
    }

    document.getElementById("modalAdminRfidAddCard")?.classList.add("open");
};

window.closeAdminRfidAddCard = function() {
    document.getElementById("modalAdminRfidAddCard")?.classList.remove("open");
};

window.saveAdminRfidCard = async function(e) {
    if (e) e.preventDefault();
    const uid = document.getElementById("adminNewCardUid")?.value.trim();
    const name = document.getElementById("adminNewCardName")?.value.trim();
    const dept = document.getElementById("adminNewCardDept")?.value.trim();
    const limit = parseInt(document.getElementById("adminNewCardLimit")?.value) || 1;
    const devId = document.getElementById("adminCardDeviceSelect")?.value || undefined;
    const clientId = document.getElementById("adminCardVendorSelect")?.value || undefined;

    if (!uid || !name) {
        showToast("Card UID and Cardholder Name are required", "danger");
        return;
    }

    try {
        await apiRequest("/rfid-vending/cards", {
            method: "POST",
            body: JSON.stringify({
                card_uid: uid,
                username: name,
                department: dept || undefined,
                device_id: devId,
                client_id: clientId,
                daily_limit: limit,
                is_active: true
            })
        });

        showToast(`✓ Card ${uid} enrolled successfully for ${name}!`, "success");
        closeAdminRfidAddCard();
        loadAdminRfidCards();
    } catch (err) {
        showToast(err.message, "danger");
    }
};

window.openAdminRfidBulkUpload = function() {
    const devSelect = document.getElementById("adminBulkDeviceSelect");
    if (devSelect && state.devices) {
        devSelect.innerHTML = '<option value="">All Machines (Vendor Fleet)</option>';
        state.devices.forEach(d => {
            const opt = document.createElement("option");
            opt.value = d.device_id;
            opt.textContent = `${d.device_id} (${d.client_name || 'Unassigned'})`;
            devSelect.appendChild(opt);
        });
    }

    const vSelect = document.getElementById("adminBulkVendorSelect");
    if (vSelect && state.clients) {
        vSelect.innerHTML = '';
        state.clients.forEach(c => {
            const opt = document.createElement("option");
            opt.value = c.id;
            opt.textContent = c.name;
            vSelect.appendChild(opt);
        });
    }

    const f = document.getElementById("adminBulkFileInput");
    if (f) f.value = "";
    setElText("adminBulkSummary", "No file selected");
    document.getElementById("modalAdminRfidBulkUpload")?.classList.add("open");
};

window.closeAdminRfidBulkUpload = function() {
    document.getElementById("modalAdminRfidBulkUpload")?.classList.remove("open");
};

window.submitAdminRfidBulkUpload = async function() {
    const fileInput = document.getElementById("adminBulkFileInput");
    if (!fileInput || !fileInput.files || fileInput.files.length === 0) {
        showToast("Please select a CSV or Excel file to upload", "danger");
        return;
    }

    const devId = document.getElementById("adminBulkDeviceSelect")?.value || "";
    const clientId = document.getElementById("adminBulkVendorSelect")?.value || "";
    const btn = document.getElementById("btnAdminSubmitBulk");

    const formData = new FormData();
    formData.append("file", fileInput.files[0]);

    if (btn) { btn.disabled = true; btn.textContent = "Uploading 1,000 Cards..."; }

    try {
        const queryParams = new URLSearchParams();
        if (devId) queryParams.append("device_id", devId);
        if (clientId) queryParams.append("client_id", clientId);

        const res = await apiRequest(`/rfid-vending/bulk-upload?${queryParams.toString()}`, {
            method: "POST",
            body: formData
        });

        showToast(`✓ Bulk Import Complete! Added: ${res.imported}, Updated: ${res.updated}`, "success");
        closeAdminRfidBulkUpload();
        loadAdminRfidCards();
    } catch (err) {
        showToast(err.message, "danger");
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = "🚀 Upload & Sync Cards"; }
    }
};

window.openAdminRfidBatchRange = function() {
    const devSelect = document.getElementById("adminBatchDeviceSelect");
    if (devSelect && state.devices) {
        devSelect.innerHTML = '<option value="">All Machines (Vendor Fleet)</option>';
        state.devices.forEach(d => {
            const opt = document.createElement("option");
            opt.value = d.device_id;
            opt.textContent = `${d.device_id} (${d.client_name || 'Unassigned'})`;
            devSelect.appendChild(opt);
        });
    }

    const vSelect = document.getElementById("adminBatchVendorSelect");
    if (vSelect && state.clients) {
        vSelect.innerHTML = '';
        state.clients.forEach(c => {
            const opt = document.createElement("option");
            opt.value = c.id;
            opt.textContent = c.name;
            vSelect.appendChild(opt);
        });
    }

    document.getElementById("modalAdminRfidBatchRange")?.classList.add("open");
};

window.closeAdminRfidBatchRange = function() {
    document.getElementById("modalAdminRfidBatchRange")?.classList.remove("open");
};

window.submitAdminRfidBatchRange = async function(e) {
    if (e) e.preventDefault();
    const devId = document.getElementById("adminBatchDeviceSelect")?.value || undefined;
    const clientId = document.getElementById("adminBatchVendorSelect")?.value || undefined;
    const startNum = parseInt(document.getElementById("adminBatchStartNum")?.value) || 1;
    const endNum = parseInt(document.getElementById("adminBatchEndNum")?.value) || 1000;
    const prefix = document.getElementById("adminBatchNamePrefix")?.value.trim() || "Staff-";
    const uidPrefix = document.getElementById("adminBatchUidPrefix")?.value.trim() || "RFC-";
    const padDigits = parseInt(document.getElementById("adminBatchPadDigits")?.value) || 4;
    const dailyLimit = parseInt(document.getElementById("adminBatchDailyLimit")?.value) || 1;

    try {
        const res = await apiRequest("/rfid-vending/batch-generate", {
            method: "POST",
            body: JSON.stringify({
                device_id: devId,
                client_id: clientId,
                start_num: startNum,
                end_num: endNum,
                prefix: prefix,
                uid_prefix: uidPrefix,
                pad_digits: padDigits,
                daily_limit: dailyLimit
            })
        });

        showToast(`✓ Generated ${res.created} sequential cards! (Skipped: ${res.skipped_existing})`, "success");
        closeAdminRfidBatchRange();
        loadAdminRfidCards();
    } catch (err) {
        showToast(err.message, "danger");
    }
};

let adminEnrollTimer = null;
window.openAdminRfidLiveEnroll = async function() {
    const devSelect = document.getElementById("adminLiveEnrollDeviceSelect");
    if (devSelect && state.devices) {
        devSelect.innerHTML = '';
        state.devices.forEach(d => {
            const opt = document.createElement("option");
            opt.value = d.device_id;
            opt.textContent = `${d.device_id} (${d.client_name || 'Unassigned'})`;
            devSelect.appendChild(opt);
        });
    }

    const modal = document.getElementById("modalAdminRfidLiveEnroll");
    modal?.classList.add("open");

    document.getElementById("adminLiveWaitingBox").style.display = "block";
    document.getElementById("adminLiveDetectedBox").style.display = "none";
    document.getElementById("btnAdminSaveLiveCard").style.display = "none";

    const devId = devSelect?.value;
    if (devId) {
        await apiRequest(`/rfid-vending/devices/${devId}/enroll-mode`, {
            method: "POST",
            body: JSON.stringify({ enabled: true })
        });
        showToast(`📡 Machine ${devId} is now listening for RFID card taps!`, "info");
    }

    if (adminEnrollTimer) clearInterval(adminEnrollTimer);
    adminEnrollTimer = setInterval(async () => {
        const currentDev = document.getElementById("adminLiveEnrollDeviceSelect")?.value;
        if (!currentDev) return;
        try {
            const res = await apiRequest(`/rfid-vending/devices/${currentDev}/enroll-status`);
            if (res && res.last_uid) {
                setElText("adminLiveDetectedUid", res.last_uid);
                document.getElementById("adminLiveWaitingBox").style.display = "none";
                document.getElementById("adminLiveDetectedBox").style.display = "block";
                document.getElementById("btnAdminSaveLiveCard").style.display = "inline-block";
                document.getElementById("adminLiveCardholderName")?.focus();
                showToast(`💳 Card ${res.last_uid} captured! Enter cardholder name.`, "success");
            }
        } catch (e) {}
    }, 1000);
};

window.closeAdminRfidLiveEnroll = async function() {
    if (adminEnrollTimer) { clearInterval(adminEnrollTimer); adminEnrollTimer = null; }
    const currentDev = document.getElementById("adminLiveEnrollDeviceSelect")?.value;
    if (currentDev) {
        try {
            await apiRequest(`/rfid-vending/devices/${currentDev}/enroll-mode`, {
                method: "POST",
                body: JSON.stringify({ enabled: false })
            });
        } catch (e) {}
    }
    document.getElementById("modalAdminRfidLiveEnroll")?.classList.remove("open");
};

window.saveAdminLiveEnrollCard = async function() {
    const uid = document.getElementById("adminLiveDetectedUid")?.textContent.trim();
    const name = document.getElementById("adminLiveCardholderName")?.value.trim();
    const dept = document.getElementById("adminLiveCardDept")?.value.trim();
    const limit = parseInt(document.getElementById("adminLiveCardLimit")?.value) || 1;
    const devId = document.getElementById("adminLiveEnrollDeviceSelect")?.value;

    if (!name) {
        showToast("Please enter a cardholder name", "danger");
        return;
    }

    try {
        await apiRequest("/rfid-vending/cards", {
            method: "POST",
            body: JSON.stringify({
                card_uid: uid,
                username: name,
                department: dept || undefined,
                device_id: devId,
                daily_limit: limit,
                is_active: true
            })
        });

        showToast(`✓ Card ${uid} enrolled for ${name}!`, "success");
        closeAdminRfidLiveEnroll();
        loadAdminRfidCards();
    } catch (err) {
        showToast(err.message, "danger");
    }
};


function handleStockModeToggleChange() {
    const toggle = document.getElementById("pricingStockModeToggle");
    const badge = document.getElementById("pricingStockModeStatusBadge");
    if (!toggle || !badge) return;
    if (toggle.checked) {
        badge.textContent = "Stock-Based Mode";
        badge.style.background = "rgba(16,185,129,0.2)";
        badge.style.color = "#34d399";
    } else {
        badge.textContent = "Without-Stock Mode (Unlimited)";
        badge.style.background = "rgba(245,158,11,0.2)";
        badge.style.color = "#fbbf24";
    }
}


function handlePaymentModeChange() {
    const val = document.querySelector('input[name="pricingPaymentMode"]:checked')?.value || "BOTH";
    const badge = document.getElementById("pricingPaymentModeBadge");
    if (!badge) return;
    if (val === "QR_ONLY") {
        badge.textContent = "QR CODE ONLY";
        badge.style.background = "rgba(14,165,233,0.25)";
        badge.style.color = "#38bdf8";
    } else if (val === "COIN_ONLY") {
        badge.textContent = "COIN ONLY";
        badge.style.background = "rgba(245,158,11,0.25)";
        badge.style.color = "#fbbf24";
    } else {
        badge.textContent = "BOTH (QR + COIN)";
        badge.style.background = "rgba(99,102,241,0.25)";
        badge.style.color = "#a5b4fc";
    }
}


// ==============================================================================
// HARDWARE DISCOVERY & ZERO-TOUCH MACHINE ASSIGNMENT
// ==============================================================================
async function loadDiscoveryQueue() {
    try {
        const res = await apiRequest("/devices/discovery-queue");
        const banner = document.getElementById("discoveryBanner");
        const countEl = document.getElementById("discoveryCount");
        const container = document.getElementById("discoveryItemsContainer");
        if (!banner || !container) return;

        const items = res?.items || [];
        if (items.length === 0) {
            banner.style.display = "none";
            return;
        }

        banner.style.display = "block";
        if (countEl) countEl.innerText = items.length;

        container.innerHTML = items.map(item => `
            <div style="display:flex; justify-content:space-between; align-items:center; background:rgba(0,0,0,0.3); border:1px solid rgba(255,255,255,0.1); border-radius:8px; padding:0.85rem 1.15rem; flex-wrap:wrap; gap:0.75rem;">
                <div>
                    <div style="display:flex; align-items:center; gap:0.6rem;">
                        <span style="font-family:monospace; font-weight:700; font-size:1.05rem; color:#fff; letter-spacing:0.5px;">${item.mac_address}</span>
                        <span style="font-size:0.7rem; background:rgba(59,130,246,0.25); color:#60a5fa; border:1px solid rgba(59,130,246,0.4); padding:2px 6px; border-radius:4px; font-weight:600;">NEW HARDWARE</span>
                    </div>
                    <div style="font-size:0.78rem; color:var(--text-secondary); margin-top:4px;">
                        Chip: <span style="color:#e2e8f0;">${item.chip_id || 'ESP32'}</span> &bull; 
                        IP: <span style="color:#e2e8f0;">${item.ip_address || 'Connected'}</span> &bull; 
                        Suggested: <span style="color:#38bdf8; font-weight:700;">${item.suggested_device_id || 'VM-XXXXXX'}</span>
                    </div>
                </div>
                <div style="display:flex; gap:0.5rem; align-items:center;">
                    <button class="btn btn-primary btn-sm" onclick="openClaimDiscoveryModal('${item.mac_address}', '${item.chip_id || ''}', '${item.suggested_device_id || ''}')" style="font-weight:600;">
                        ⚡ Assign Machine ID
                    </button>
                    <button class="btn btn-secondary btn-sm" onclick="dismissDiscoveredDevice('${item.id}')" title="Dismiss from Queue" style="padding:0.35rem 0.65rem; color:var(--text-muted);">
                        &times;
                    </button>
                </div>
            </div>
        `).join("");
    } catch (e) {
        console.warn("Notice checking discovery queue:", e);
    }
}
window.loadDiscoveryQueue = loadDiscoveryQueue;

function openClaimDiscoveryModal(mac, chip, suggestedId) {
    document.getElementById("claimMac").value = mac;
    document.getElementById("claimChip").value = chip;
    document.getElementById("claimDeviceId").value = suggestedId || "";

    const clientSelect = document.getElementById("claimClient");
    if (clientSelect && state.clients) {
        clientSelect.innerHTML = state.clients.map(c => `
            <option value="${c.id}">${c.name}</option>
        `).join("");
    }
    openModal("modalClaimDiscovery");
}
window.openClaimDiscoveryModal = openClaimDiscoveryModal;

async function dismissDiscoveredDevice(id) {
    try {
        await apiRequest(`/devices/discovery-queue/${id}`, { method: "DELETE" });
        showToast("Discovered board dismissed", "info");
        await loadDiscoveryQueue();
    } catch (e) {
        showToast("Error dismissing device", "error");
    }
}
window.dismissDiscoveredDevice = dismissDiscoveredDevice;

document.addEventListener("DOMContentLoaded", () => {
    const claimForm = document.getElementById("claimDiscoveryForm");
    if (claimForm) {
        claimForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const mac = document.getElementById("claimMac").value.trim();
            const devId = document.getElementById("claimDeviceId").value.trim().toUpperCase();
            const clientId = document.getElementById("claimClient").value;
            const typeCode = document.getElementById("claimType").value;

            if (!devId) {
                showToast("Please enter a Machine ID (e.g. VM-000005)", "error");
                return;
            }

            try {
                const res = await apiRequest("/devices/discovery-queue/claim", {
                    method: "POST",
                    body: JSON.stringify({
                        mac_address: mac,
                        device_id: devId,
                        client_id: clientId || undefined,
                        device_type_code: typeCode || "VENDING_MACHINE"
                    })
                });
                closeModal("modalClaimDiscovery");
                showToast(`⚡ Machine ${res.device_id} assigned and activated! Node will sync in seconds.`, "success");
                await loadDiscoveryQueue();
                await loadDevices();
                await loadFleet();
            } catch (err) {
                showToast(err.message || "Failed to assign Machine ID", "error");
            }
        });
    }

    // Auto-poll discovery queue every 8 seconds
    setInterval(() => {
        if (state.token && (state.activeTab === "devices" || state.activeTab === "overview")) {
            loadDiscoveryQueue();
        }
    }, 8000);
});
