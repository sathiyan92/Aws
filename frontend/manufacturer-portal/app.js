/**
 * Manufacturer Operations Portal - Reactive Single Page Application
 * Multi-Tenant Cloud IoT Platform for Vending and RFID Systems
 */

const API_BASE = window.location.origin.includes(":8000") 
    ? `${window.location.origin}/api/v1`
    : "http://localhost:8000/api/v1";

// Application State
const state = {
    token: localStorage.getItem("mfg_token") || null,
    user: JSON.parse(localStorage.getItem("mfg_user") || "null"),
    stats: null,
    clients: [],
    devices: [],
    auditLogs: [],
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
        audit: "System Security & Audit Trail",
    };
    document.getElementById("pageTitle").textContent = titleMap[tabName] || "Manufacturer Portal";

    if (tabName === "clients") renderClientsTable();
    if (tabName === "devices") renderDevicesTable();
    if (tabName === "vending") renderDevicesTable("VENDING_MACHINE");
    if (tabName === "rfid") renderDevicesTable("RFID_ATTENDANCE");
    if (tabName === "audit") renderAuditTable();
}

// ==============================================================================
// API CALLS & BOOTSTRAP
// ==============================================================================
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

        const data = await response.json();
        if (!response.ok) {
            const msg = data.detail?.message || data.detail || "API request failed";
            throw new Error(msg);
        }
        return data;
    } catch (err) {
        showToast(err.message, "danger");
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
                    <button class="btn btn-secondary btn-sm" onclick="openAssignModal('${d.id}', '${d.device_id}', '${d.client_id || ''}')">Assign</button>
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
                    initial_modules: {
                        "QR_PAYMENT": qrOn,
                        "COIN_PAYMENT": coinOn,
                        "RFID_ACCESS": false,
                    }
                })
            });
            closeModal("modalProvision");
            showToast(`Hardware registered successfully! Device ID: ${res.device_id}`, "success");
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
