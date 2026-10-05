# Multi-Tenant Cloud IoT Platform for Vending & RFID Systems

[![Platform Architecture](https://img.shields.io/badge/Architecture-Phase%201%20Completed-brightgreen.svg)](#)
[![Database Schema](https://img.shields.io/badge/Database%20Schema-Phase%202%20Completed-brightgreen.svg)](#)
[![Authentication & Tenancy](https://img.shields.io/badge/Multi--Tenant%20Auth-Phase%203%20Completed-brightgreen.svg)](#)
[![Device Lifecycle](https://img.shields.io/badge/Device%20Lifecycle-Phase%204%20Completed-brightgreen.svg)](#)
[![Manufacturer Portal](https://img.shields.io/badge/Manufacturer%20Portal-Phase%205%20Completed-brightgreen.svg)](#)
[![Status](https://img.shields.io/badge/Current%20State-Phase%205%20Complete-blue.svg)](#)
[![Target Hardware](https://img.shields.io/badge/Target%20Hardware-ESP32%20%7C%20ESP32--S3-orange.svg)](#)

---

## 1. Project Overview & Business Model

This repository contains the enterprise IoT platform for an original equipment manufacturer (OEM) producing commercial ESP32-based devices. The platform enables the manufacturer to manufacture, provision, deploy, configure, update, and monitor diverse commercial IoT hardware fleets across multiple independent corporate clients (tenants).

### Core Hardware Product Families
1. **Commercial Vending Machines (`VM-XXXXXX`):**
   - Autonomous vending controllers with configurable multi-payment subsystems:
     - `QR_PAYMENT`: Ephemeral, transaction-based dynamic UPI/QR payment with cloud order validation and dispense authorization.
     - `COIN_PAYMENT`: Autonomous electronic multi-coin pulse acceptor with edge credit accumulation, offline vending, and change calculation.
     - `RFID_ACCESS`: Subsidized or authorized card-based dispense.
   - Decoupled product catalog and pricing: changing a price (e.g., ₹40 to ₹45) is a versioned configuration push, **requiring zero firmware compilation or OTA flashing**.
2. **RFID Attendance Terminals (`RFID-XXXXXX`):**
   - High-throughput attendance recording units with edge card whitelist caching for instant offline tap recognition.
   - Comprehensive card status lifecycle (`ACTIVE`, `DISABLED`, `BLOCKED`, `REPLACED`) with permanent referential integrity for historical attendance records.
   - Directional IN/OUT tracking, shift reporting, and automatic batch synchronization upon reconnection.

### Multi-Tenant Model
- **Manufacturer (Platform Owner):** Creates clients, registers devices, burns Device IDs, manages module entitlements, uploads and signs firmware, orchestrates OTA campaigns, and inspects global fleet health.
- **Client Tenants:** Isolated operational domain. Clients can only view and manage devices assigned to their account. A client can **never** access another client's devices, data, or configuration.
- **Dynamic Feature Visibility:** Client dashboards dynamically display or conceal controls based on the modules enabled for each device (backed by strict backend API policy enforcement).

---

## 2. Repository Layout & Project Structure

```
iot-fleet-platform/
├── ARCHITECTURE.md                  # Comprehensive technical architecture & protocols
├── DEVELOPMENT_PHASES.md            # 22-phase execution roadmap & milestones
├── README.md                        # Project manual, setup, verification & guidelines
├── .gitignore                       # Multi-stack gitignore (Python, Web, ESP32, Certs)
│
├── docs/                            # Documentation & specifications
│   └── architecture/
│       ├── diagrams/                # Architectural flowcharts & sequence diagrams
│       └── specs/                   # Technical protocol specifications
│
├── backend/                         # Cloud backend & IoT device gateway
│   ├── src/
│   │   ├── api/
│   │   │   └── v1/
│   │   │       ├── auth/            # Authentication & session endpoints
│   │   │       ├── clients/         # Client tenant management
│   │   │       ├── devices/         # Device lifecycle & provisioning
│   │   │       ├── vending/         # Products, slots, orders & dispenses
│   │   │       ├── rfid/            # Cards, employees & attendance records
│   │   │       ├── configs/         # Versioned configuration sync engine
│   │   │       ├── ota/             # Firmware repository & OTA campaigns
│   │   │       └── telemetry/       # Heartbeats, metrics & logs
│   │   ├── core/
│   │   │   ├── config/              # Environment & application settings
│   │   │   ├── security/            # JWT, Argon2id, RBAC, Tenant Guards
│   │   │   └── exceptions/          # Standardized error definitions
│   │   ├── db/
│   │   │   ├── models/              # Relational models & ORM entities
│   │   │   ├── migrations/          # Database migration files
│   │   │   └── session/             # Database connection pools
│   │   ├── mqtt/
│   │   │   ├── handlers/            # Inbound telemetry, heartbeat & event handlers
│   │   │   └── client/              # Broker client connection manager
│   │   └── services/                # Business logic services
│   └── tests/                       # Unit & integration test suites
│
├── frontend/                        # Web applications & administrative portals
│   ├── manufacturer-portal/         # Platform admin portal (fleet, tenants, OTA)
│   │   ├── public/
│   │   └── src/
│   │       ├── assets/
│   │       ├── components/
│   │       ├── pages/
│   │       └── services/
│   └── client-portal/               # Tenant portal (dynamic by enabled modules)
│       ├── public/
│       └── src/
│           ├── assets/
│           ├── components/
│           ├── pages/
│           └── services/
│
├── firmware/                        # Embedded ESP-IDF / FreeRTOS source
│   ├── common/                      # Shared edge components (NVS, TLS, MQTT, OTA)
│   │   ├── include/
│   │   └── src/
│   ├── esp32-vending/               # Vending controller application
│   │   ├── include/
│   │   └── src/
│   └── esp32-rfid/                  # RFID attendance application
│       ├── include/
│       └── src/
│
└── infrastructure/                  # Infrastructure as Code & deployment
    ├── docker/
    │   ├── mosquitto/               # MQTT broker container configuration
    │   └── postgres/                # PostgreSQL container configuration
    ├── certs/                       # Development certificates & keys
    └── scripts/                     # Operational automation & provisioning scripts
```

---

## 3. How to Start

### Prerequisites
- **Operating System:** Windows, Linux, or macOS
- **Runtime Tools (for upcoming phases):**
  - Python 3.11+ (FastAPI backend)
  - PostgreSQL 15+ (Relational database)
  - Mosquitto / EMQX (MQTT message broker)
  - ESP-IDF v5.x / PlatformIO (for ESP32 firmware compilation)
  - Docker & Docker Compose (for local containerized testing)

### Initializing the Workspace
```powershell
# Clone or navigate to the workspace
cd c:\Projects\iot-fleet-platform

# Review the architecture and roadmap
Get-Content ARCHITECTURE.md | more
Get-Content DEVELOPMENT_PHASES.md | more
```

---

## 4. Phase 1 Verification Guide

Phase 1 focuses exclusively on architecture, modular system design, and foundational scaffolding. To verify Phase 1 completeness:

1. **Verify Architectural Specifications:**
   Confirm that [ARCHITECTURE.md](file:///c:/Projects/iot-fleet-platform/ARCHITECTURE.md) contains all core technical designs:
   - Multi-tenant data isolation & RBAC boundaries.
   - Device identity tuples (`VM-XXXXXX`, `RFID-XXXXXX`) and hardware verification.
   - Extensible product type system and dynamic device modules (`QR_PAYMENT`, `COIN_PAYMENT`, `RFID_ACCESS`).
   - Transaction-based dynamic QR payment sequence and drop-sensor-verified dispense flow.
   - Autonomous coin pulse processing, edge credit accumulator, and change logic.
   - RFID card lifecycle (`ACTIVE`, `DISABLED`, `BLOCKED`, `REPLACED`) with referential audit retention.
   - Monotonically versioned cloud configuration synchronization decoupled from firmware.
   - Secure A/B dual-bank OTA updates with digital signatures and automatic bootloader rollback.
   - End-to-end security architecture (mTLS, JWT, zero hardcoded secrets, rate limiting, audit logging).
   - Future scalability roadmap (MQTT broker clustering, time-series data partitioning).

2. **Verify Phase Roadmap:**
   Confirm that [DEVELOPMENT_PHASES.md](file:///c:/Projects/iot-fleet-platform/DEVELOPMENT_PHASES.md) specifies all 22 execution phases with deliverables, dependencies, and verification criteria, marking Phase 1 as COMPLETED and Phase 2 as NEXT UP.

3. **Verify Project Structure:**
   Confirm all required folders exist across `backend`, `frontend`, `firmware`, `infrastructure`, and `docs`.

---

## 5. Current Limitations (Phase 1 Scope)

In strict adherence to the project instructions:
- **No active payment gateway integrations** (Razorpay/UPI/Stripe) are implemented yet.
- **No live QR code generator or dynamic payment webhook handlers** are active.
- **No physical coin acceptor hardware interrupt routines** are running.
- **No physical RFID hardware reader drivers** are polling tags.
- **No live OTA firmware distribution** is deployed.
- **No database connections or active API servers** are executed in this phase.

All logic for these subsystems is defined architecturally and will be implemented sequentially according to the roadmap.

---

## 6. Phase 2 Verification & Database Execution

Phase 2 implemented the complete relational schema, automated migrations, seed data pipeline, and integrity test suite.

### How to Verify Phase 2
```powershell
# 1. Run the automated schema verification test suite
python backend/src/verify_schema.py

# 2. Run Alembic database migrations
python -m alembic -c backend/alembic.ini upgrade head

# 3. Inspect PostgreSQL production DDL script
Get-Content infrastructure/docker/postgres/init-schema.sql | Select-Object -First 50
```

---

## 7. Phase 3 Verification: Authentication & Multi-Tenant Authorization

Phase 3 implemented JWT token generation, refresh rotation, RBAC guards, and multi-tenant isolation boundaries.

### How to Verify Phase 3
Run the automated pytest suite:
```powershell
python -m pytest backend/tests/test_auth_and_tenancy.py -v
```

### Verified Test Matrix:
- `test_health_endpoint`: Public health status check.
- `test_manufacturer_admin_login`: Super-admin receives global token with `client_id=NULL`.
- `test_client_admin_login`: Client admin receives tenant-scoped token with assigned `client_id`.
- `test_login_invalid_credentials`: Rejection of wrong credentials with `NOT_AUTHENTICATED`.
- `test_protected_route_requires_token`: Bearer token enforcement on `/auth/me`.
- `test_auth_me_returns_profile`: Profile extraction from validated JWT.
- `test_token_refresh_flow`: Seamless access token rotation with refresh token.
- `test_strict_tenant_isolation_boundary`: **Client A user attempting to query Client B devices is rejected with HTTP 403 `TENANT_ISOLATION_VIOLATION`**.
- `test_manufacturer_admin_global_visibility`: Manufacturer super-admin can inspect any tenant's fleet.
- `test_rbac_manufacturer_admin_only_endpoint`: Non-manufacturer users rejected from admin routes with HTTP 403 `FORBIDDEN_ACCESS`.
- `test_backend_module_authorization_policy`: **Backend rejects direct requests to disabled modules (e.g. coin on QR-only machine) with HTTP 403 `MODULE_DISABLED_FOR_DEVICE`**.
- `test_device_cross_tenant_access_blocked`: Client A user cannot access Client B machines even if feature modules match.

---

## 8. Phase 4 Verification: Device Lifecycle & Fleet Management

Phase 4 implemented physical hardware registration, auto-generating permanent Device IDs (`VM-XXXXXX`, `RFID-XXXXXX`), unique device credentials, client tenant assignment/unassignment, and hardware feature module management with automated configuration version bumping.

### How to Verify Phase 4
Run the automated test suite:
```powershell
python -m pytest backend/tests/test_device_lifecycle.py -v
```

### Verified Test Matrix:
- `test_list_supported_device_types`: Returns product types with capability schemas.
- `test_manufacturer_registers_vending_machine_auto_naming`: Provisions hardware, verifies sequential Device ID generation (`VM-000100`), credentials, and config v1.
- `test_manufacturer_registers_rfid_terminal_auto_naming`: Provisions RFID unit, auto-generates `RFID-000002`.
- `test_client_admin_cannot_register_device`: Non-manufacturer users blocked with HTTP 403 `FORBIDDEN_ACCESS`.
- `test_duplicate_hardware_identifiers_rejected`: Duplicate MAC or chip ID raises HTTP 400 Bad Request.
- `test_manufacturer_assigns_and_unassigns_device`: Transitions between `PROVISIONED` (inventory) and `ASSIGNED` (tenant).
- `test_manufacturer_toggles_hardware_module_bumps_config_version`: Module toggle increments `current_config_version` (v1 -> v2), updates active configuration, and logs historical audit diff.
- `test_client_admin_cannot_toggle_modules`: Client admins blocked from modifying physical hardware capabilities.
- `test_fleet_listing_strict_multi_tenant_scoping`: Manufacturer sees full fleet; Client tenants see **strictly** their assigned units.
- `test_single_device_detail_tenant_scoping`: Direct access to another client's machine returns HTTP 403 `TENANT_ISOLATION_VIOLATION`.
- `test_client_onboarding_and_listing`: Manufacturer creates and lists client tenant organizations.

---

## 9. Phase 5 Verification: Manufacturer Operations Portal

Phase 5 implemented the modern web application for the platform manufacturer, hosting fleet analytics, client directory, hardware provisioning, device assignment, dynamic module toggling, and audit log inspection.

### How to Run & Verify Phase 5
1. **Run the Automated Pytest Suite:**
   ```powershell
   python -m pytest backend/tests/test_manufacturer_portal.py -v
   ```
2. **Launch the Live Platform Server:**
   ```powershell
   cd c:\Projects\iot-fleet-platform\backend
   python -m uvicorn src.main:app --port 8000 --reload
   ```
3. **Open the Operations Portal in your Browser:**
   - URL: `http://localhost:8000/portal/index.html` (or open [`frontend/manufacturer-portal/index.html`](file:///c:/Projects/iot-fleet-platform/frontend/manufacturer-portal/index.html) directly).
   - Click **⚡ Quick Demo Login (Super-Admin)** to authenticate as `admin` (`Admin@SecurePlatform2026!`).
   - Interact with the tabs:
     - **Overview:** Inspect connected fleet stats, active online count, module breakdown, and live audit stream.
     - **Clients:** View onboarded client organizations, device counts, and click "View Fleet".
     - **All Devices:** Provision new physical nodes (`VM-XXXXXX`), toggle modules (`QR_PAYMENT` / `COIN_PAYMENT`), and assign devices.
     - **Vending Machines:** Filter specifically for vending controllers with interactive switches.
     - **RFID Terminals:** Filter specifically for attendance units.
     - **Audit Trail:** Inspect immutable logs of all mutations.

---

## 10. Phase 6 Verification: Client Portal & Dynamic Feature Visibility

Phase 6 implemented the dedicated Client Tenant Portal ([`frontend/client-portal/`](file:///c:/Projects/iot-fleet-platform/frontend/client-portal)) with dynamic hardware feature visibility and server-side policy guard enforcement.

### Key Capabilities Delivered:
1. **Dynamic Feature Visibility:**
   - Client navigation tabs, forms, and tables adapt in real-time based on the hardware modules enabled on the currently selected machine.
   - If `QR_PAYMENT` is disabled on a machine (e.g., `VM-000002`), all QR settings and digital payment logs are purged from the UI using `.dynamic-hidden`.
   - If `COIN_PAYMENT` is disabled on a machine (e.g., `VM-000001`), coin pulse calibration and coin vault logs are purged from the UI.
   - If `RFID_ACCESS` is enabled (e.g., `RFID-000001`), the RFID whitelist manager and real-time attendance logs are displayed.
2. **Server-Side Policy Enforcement (Defense in Depth):**
   - Frontend hiding is strictly backed by the backend `require_device_module(module_code)` dependency.
   - Any crafted or forged HTTP request targeting a disabled module is blocked with **HTTP 403 Forbidden** and error code `MODULE_DISABLED_FOR_DEVICE`.
3. **Multi-Tenant Fleet Isolation:**
   - Client admins (`apex_admin`, `metro_admin`) strictly access devices owned by their organization.
   - Cross-tenant device queries are rejected with **HTTP 403 `TENANT_ISOLATION_VIOLATION`**.
4. **Decoupled Configuration Management:**
   - Modifying UPI VPA gateway details, timeouts, or coin pulse ratios bumps `current_config_version` and marks `is_synced = False` without requiring firmware recompilation.

---

### How to Run & Verify Phase 6

#### 1. Automated Test Suites
Run the dedicated Phase 6 dynamic visibility test suite:
```powershell
python -m pytest backend/tests/test_dynamic_visibility.py -v
```

Run all backend test suites across the platform (35 tests):
```powershell
python -m pytest backend/tests/ -v
```

#### 2. Live Browser Verification
1. Launch the FastAPI server:
   ```powershell
   cd c:\Projects\iot-fleet-platform\backend
   python -m uvicorn src.main:app --port 8000 --reload
   ```
2. Open the Client Tenant Portal:
   - **URL:** `http://localhost:8000/client-portal/index.html` (or open [`frontend/client-portal/index.html`](file:///c:/Projects/iot-fleet-platform/frontend/client-portal/index.html) in your browser).
   - Log in using **Apex Vending Admin** (`apex_admin` / `Apex@Admin2026!`).
3. Verify Dynamic Visibility in the Browser:
   - In the top header dropdown, select **`VM-000001` (QR Only)**:
     - Notice that the **QR Payments** tab is visible in the sidebar.
     - Notice that the **Coin Acceptor** tab is completely hidden.
   - Switch to **`VM-000002` (Coin Only)**:
     - Notice that the **QR Payments** tab is immediately hidden.
     - Notice that the **Coin Acceptor** tab appears.
   - Switch to **`VM-000003` (Hybrid)**:
     - Both **QR Payments** and **Coin Acceptor** tabs are visible.
   - Switch to **`RFID-000001` (RFID Attendance)**:
     - Vending payment tabs disappear; **RFID Cards & Logs** tab becomes active.
4. Verify Security Policy Enforcement Testbed:
   - Click the **Security Policy Guard** tab in the sidebar.
   - Under "Target Module", select `COIN_PAYMENT`. Under "Target Machine", select `VM-000001` (where Coin is disabled).
   - Click **Execute Forged Request**.
   - Observe the live security alert box showing **HTTP 403 FORBIDDEN** with exact error code `MODULE_DISABLED_FOR_DEVICE`, proving that frontend hiding is backed by rigid server authorization.

---

## 11. Phase 7 Requirements (Next Milestone)

Upon approval of Phase 6, development will proceed to **Phase 7: ESP32 Base Firmware Core**:
- Base embedded C/C++ firmware foundation for ESP32 (ESP-IDF v5.x / PlatformIO with FreeRTOS).
- Hardware abstraction layer for Wi-Fi and peripheral buses.
- Non-Volatile Storage (NVS) manager for cryptographic device identity and offline state.
- Secure TLS 1.3 client and resilient MQTT connectivity with exponential backoff.
- Multi-task FreeRTOS architecture cleanly isolating the networking stack from real-time hardware I/O.

---
*Multi-Tenant Cloud IoT Platform — Engineered for Industrial Commercial Deployment*

