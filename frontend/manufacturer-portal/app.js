/**
 * Manufacturer Operations Portal - Reactive Single Page Application
 * Multi-Tenant Cloud IoT Platform for Vending and RFID Systems
 */

function getApiBase() {
    if (window.location.protocol === "file:") {
        return "http://localhost:8000/api/v1";
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

function switchTab(tabName) {
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
        rfid: "RFID Attendance Fleet",
        firmware: "Firmware Artifacts & OTA Distribution Hub",
        audit: "System Security & Audit Trail",
    };
    document.getElementById("pageTitle").textContent = titleMap[tabName] || "Manufacturer Portal";

    if (tabName === "clients") renderClientsTable();
    if (tabName === "devices") renderDevicesTable();
    if (tabName === "vending") renderDevicesTable("VENDING_MACHINE");
    if (tabName === "rfid") renderDevicesTable("RFID_ATTENDANCE");
    if (tabName === "firmware") renderFirmwareTab();
    if (tabName === "audit") renderAuditTable();
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
    const headers = {
        "Content-Type": "application/json",
        ...(state.token ? { "Authorization": `Bearer ${state.token}` } : {}),
        ...options.headers,
    };

    try {
        const response = await fetch(`${API_BASE}${endpoint}`, {
            ...options,
            headers,
        });

        if (response.status === 401) {
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

    document.getElementById("statTotalDevices").textContent = s.devices_count || 0;
    document.getElementById("statOnlineDevices").textContent = s.online_devices_count || 0;
    document.getElementById("statClients").textContent = s.clients_count || 0;
    document.getElementById("statVending").textContent = s.product_type_breakdown?.VENDING_MACHINE || 0;
    document.getElementById("statRFID").textContent = s.product_type_breakdown?.RFID_ATTENDANCE || 0;

    // Module badges
    document.getElementById("statQRCount").textContent = s.module_breakdown?.QR_PAYMENT || 0;
    document.getElementById("statCoinCount").textContent = s.module_breakdown?.COIN_PAYMENT || 0;
    document.getElementById("statRFIDCount").textContent = s.module_breakdown?.RFID_ACCESS || 0;

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
            <td>
                <button class="btn btn-secondary btn-sm" onclick="filterDevicesByClient('${c.id}', '${c.name}')">View Fleet</button>
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
                <td class="mono-text" style="font-weight:700; font-size:0.9rem;">${d.device_id}</td>
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
    // Quick Demo Login Button
    document.getElementById("btnQuickDemoLogin")?.addEventListener("click", async () => {
        document.getElementById("loginUsername").value = "admin";
        document.getElementById("loginPassword").value = "Admin@SecurePlatform2026!";
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
        const code = document.getElementById("newClientCode").value;
        const name = document.getElementById("newClientName").value;
        const email = document.getElementById("newClientEmail").value;
        const phone = document.getElementById("newClientPhone").value;
        const address = document.getElementById("newClientAddress").value;

        try {
            const res = await apiRequest("/clients", {
                method: "POST",
                body: JSON.stringify({
                    client_code: code,
                    name: name,
                    contact_email: email,
                    contact_phone: phone,
                    address: address,
                })
            });
            closeModal("modalCreateClient");
            showToast(`Client '${res.name}' onboarded successfully!`, "success");
            await loadClients();
            await loadStats();
            renderClientsTable();
        } catch (err) {}
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


async function handleLoginSubmit() {
    const u = document.getElementById("loginUsername").value;
    const p = document.getElementById("loginPassword").value;

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
        showToast(`Welcome back, ${res.user.full_name}!`, "success");
        bootstrapPortal();
    } catch (err) {}
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
    openModal("modalLogin");
}

function openModal(id) {
    document.getElementById(id)?.classList.add("open");
}

function closeModal(id) {
    document.getElementById(id)?.classList.remove("open");
}

function openProvisionModal() {
    // Generate fresh demo hardware coordinates
    const randHex = Math.floor(Math.random() * 0xFFFFFF).toString(16).padStart(6, '0').toUpperCase();
    document.getElementById("provMac").value = `3C:84:27:${randHex.substring(0,2)}:${randHex.substring(2,4)}:${randHex.substring(4,6)}`;
    document.getElementById("provChip").value = `ESP32-S3-0x${randHex}`;
    document.getElementById("provSerial").value = `MFG-2026-ESP-${Math.floor(1000 + Math.random() * 9000)}`;
    openModal("modalProvision");
}

function openCreateClientModal() {
    openModal("modalCreateClient");
}

function openAssignModal(deviceId, deviceCode, currentClientId) {
    document.getElementById("assignDeviceId").value = deviceId;
    document.getElementById("assignDeviceCodeLabel").textContent = deviceCode;

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
    document.getElementById("deleteTargetDeviceLabel").textContent = deviceCode;
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
    document.getElementById("pushTargetDeviceCodeDisplay").textContent = deviceCode || d?.device_id || "ESP32";
    document.getElementById("pushTargetDeviceNameDisplay").textContent = d ? `${d.client_name || 'Inventory Node'} | Current: ${d.current_firmware_version || 'v1.0.0'}` : "";

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
        document.getElementById("userName").textContent = state.user.full_name || state.user.username;
        document.getElementById("userRole").textContent = state.user.role;
        document.getElementById("userAvatar").textContent = state.user.username.substring(0, 2).toUpperCase();
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

function formatDate(isoStr) {
    if (!isoStr) return "—";
    const d = new Date(isoStr);
    return d.toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
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
    
    document.getElementById('pricingModalDeviceId').textContent = deviceId;
    document.getElementById('pricingModalMac').textContent = dev?.mac_address || 'Unregistered MAC';
    document.getElementById('pricingModalClient').textContent = dev?.client_name || 'Unassigned (Inventory)';

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

    const priceInput = document.getElementById(`slot-price-${slotNumber}`);
    const stockInput = document.getElementById(`slot-stock-${slotNumber}`);
    const capInput = document.getElementById(`slot-cap-${slotNumber}`);
    const activeInput = document.getElementById(`slot-active-${slotNumber}`);

    const priceRupees = priceInput ? parseFloat(priceInput.value) : 10.0;
    const stock = stockInput ? (parseInt(stockInput.value) || 0) : 10;
    const capacity = capInput ? (parseInt(capInput.value) || 20) : 20;
    const isActive = activeInput ? activeInput.checked : true;

    if (isNaN(priceRupees) || priceRupees < 0) {
        showToast("Please enter a valid price in Rupees.", "danger");
        return;
    }

    const payload = {
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

        if (res.ok) {
            showToast(`✓ Slot ${slotNumber} price updated to ₹${priceRupees.toFixed(2)}! ESP32 resolved price dynamically.`, "success");
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
            
            const qrInput = document.getElementById('pricingQrImageUrl');
            const quickInput = document.getElementById('slotQuickQrInput');
            if (cfg.custom_qr_image_url) {
                if (qrInput) qrInput.value = cfg.custom_qr_image_url;
                if (quickInput) quickInput.value = cfg.custom_qr_image_url;
                updateQrImagePreview(cfg.custom_qr_image_url);
                updateSlotQuickQrPreview(cfg.custom_qr_image_url);
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

    try {
        const res = await apiFetch(`/api/v1/orders/qr-config/${activePricingDeviceId}`, {
            method: 'PUT',
            body: JSON.stringify({ custom_qr_payload: clean })
        });

        if (res.ok) {
            const data = await res.json();
            showToast(`✓ QR Code & Price (₹${data.amount_rupees.toFixed(2)}) synced to machine ${activePricingDeviceId}!`, "success");
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

function handleQRImageUpload(event) {
    const file = event.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = function(e) {
        const base64Data = e.target.result;
        const qrInput = document.getElementById('pricingQrImageUrl');
        const quickInput = document.getElementById('slotQuickQrInput');
        if (qrInput) qrInput.value = base64Data;
        if (quickInput) quickInput.value = base64Data;
        updateQrImagePreview(base64Data);
        updateSlotQuickQrPreview(base64Data);
        showToast("QR Code image loaded! Click 'Save QR Settings' to store.", "info");
    };
    reader.readAsDataURL(file);
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

    const payload = {
        upi_merchant_vpa: vpaVal,
        merchant_name: nameVal,
        qr_timeout_seconds: parseInt(document.getElementById('pricingQrTimeout').value) || 180,
        dynamic_pricing_enabled: document.getElementById('pricingQrDynamicToggle').checked,
        custom_qr_image_url: rawQrInput || null
    };

    try {
        const res = await apiFetch(`/api/v1/vending/${activePricingDeviceId}/qr/settings`, {
            method: 'PUT',
            body: JSON.stringify(payload)
        });

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
    document.getElementById("wifiModalDeviceId").textContent = dev.device_id;
    document.getElementById("wifiModalClientName").textContent = dev.client_name || "Unassigned (Inventory)";
    document.getElementById("wifiModalConfigVer").textContent = `v${dev.current_config_version}`;
    
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

