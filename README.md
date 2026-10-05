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

## 11. Phase 7 Verification: ESP32 Base Firmware Core

Phase 7 delivered the embedded C/C++ base firmware foundation for ESP32 devices running ESP-IDF v5.x / FreeRTOS.

### Key Capabilities Delivered:
1. **Hardware Abstraction Layer (HAL):**
   - Unified network interface ([`firmware/common/include/net_mgr.h`](file:///c:/Projects/iot-fleet-platform/firmware/common/include/net_mgr.h), [`firmware/common/src/net_mgr.c`](file:///c:/Projects/iot-fleet-platform/firmware/common/src/net_mgr.c)) supporting Wi-Fi, Ethernet, and automatic Cellular LTE-M failover.
   - Event-driven state loop notifying application tasks of IP acquisition and link transitions.
2. **Non-Volatile Storage (NVS) Manager:**
   - Dedicated flash partition manager ([`firmware/common/include/nvs_mgr.h`](file:///c:/Projects/iot-fleet-platform/firmware/common/include/nvs_mgr.h), [`firmware/common/src/nvs_mgr.c`](file:///c:/Projects/iot-fleet-platform/firmware/common/src/nvs_mgr.c)).
   - Persists permanent device identity (`device_id`, `client_id`, `hardware_serial`, `auth_token`), configuration cache (`config_version`, enabled modules bitmask, checksum), and boot cycle counters.
3. **Resilient TLS 1.3 / MQTT Client Manager:**
   - MQTT client ([`firmware/common/include/mqtt_mgr.h`](file:///c:/Projects/iot-fleet-platform/firmware/common/include/mqtt_mgr.h), [`firmware/common/src/mqtt_mgr.c`](file:///c:/Projects/iot-fleet-platform/firmware/common/src/mqtt_mgr.c)) with automatic exponential backoff and randomized jitter to eliminate thundering herd storms on broker reconnection.
   - Device-scoped topic formatting: `devices/{device_id}/heartbeat`, `telemetry`, `config`, `commands`, `ota`.
   - Standard heartbeat generator serializing device uptime, free heap, RSSI, and active config version.
4. **Dual-Core FreeRTOS Multi-Task Architecture:**
   - Clean task segregation ([`firmware/common/include/system_tasks.h`](file:///c:/Projects/iot-fleet-platform/firmware/common/include/system_tasks.h), [`firmware/common/src/system_tasks.c`](file:///c:/Projects/iot-fleet-platform/firmware/common/src/system_tasks.c)):
     - **Core 0:** Network and MQTT communication tasks (`PRIORITY_NET_MANAGER = 5`, `PRIORITY_MQTT_CLIENT = 4`).
     - **Core 1:** Real-time hardware I/O task (`PRIORITY_REALTIME_IO = 6`) for coin pulse ISRs, motor firing, and RFID card capture.
   - Thread-safe FreeRTOS queues: `xQueueTelemetry` (real-time events -> MQTT) and `xQueueCommands` (cloud commands -> actuator).
5. **Dual-Bank OTA Partition Table & Build Systems:**
   - Partition table ([`firmware/partitions_two_ota.csv`](file:///c:/Projects/iot-fleet-platform/firmware/partitions_two_ota.csv)) with dual A/B application slots (`ota_0`, `ota_1`) and `otadata`.
   - Native ESP-IDF CMake files and PlatformIO multi-environment file ([`firmware/platformio.ini`](file:///c:/Projects/iot-fleet-platform/firmware/platformio.ini)).

---

### How to Verify Phase 7

#### 1. Run the Firmware Core Test Suite
From the project root:
```powershell
python -m pytest backend/tests/test_firmware_core.py -v
```

Run all platform test suites (43 tests):
```powershell
python -m pytest backend/tests/ -v
```

#### 2. Verified Test Matrix (`test_firmware_core.py`):
- `test_firmware_directory_and_build_files_present`: Validates C source and header files, CMakeLists, and PlatformIO definitions.
- `test_dual_bank_ota_partition_table_layout`: Asserts dual A/B slots (`ota_0`, `ota_1`) and NVS storage.
- `test_module_bitflags_and_task_priority_definitions`: Validates hardware module masks and dual-core priorities.
- `test_mqtt_exponential_backoff_algorithm`: Asserts exponential doubling, ceiling cap, and jitter bounds.
- `test_device_scoped_mqtt_topic_hierarchy`: Confirms strict broker topic partitioning.
- `test_heartbeat_payload_schema`: Validates JSON heartbeat telemetry payload format.
- `test_freertos_queue_telemetry_and_command_dispatch`: Asserts thread-safe FIFO queuing between real-time I/O and network task.
- `test_network_hal_failover_logic`: Validates primary Wi-Fi to cellular LTE failover state transitions.

---

## 12. Phase 8 Verification: Device Registration and Secure Authentication Gateway

Phase 8 delivered the **Cloud Device Authentication Gateway** establishing cryptographically secure mutual verification, anti-cloning hardware identity protection, and time-series heartbeat ingestion.

### Key Capabilities Delivered:
1. **Physical Hardware Handshake (`POST /api/v1/device-gateway/authenticate`):**
   - Validates the device secret token against cryptographic SHA-256 hashes in `device_credentials`.
   - **Anti-Cloning Protection:** Validates that the presented eFuse Chip ID and MAC address match factory records. Mismatches are rejected with **HTTP 403 `HARDWARE_IDENTITY_MISMATCH`**.
   - Verifies credential validity, expiration, and revocation status.
   - Issues a short-lived device session JWT (`role: DEVICE_CLIENT`) and dynamically scoped MQTT broker topics (`devices/{device_id}/*`).
2. **Periodic Heartbeat Telemetry Ingestion (`POST /api/v1/device-gateway/heartbeat`):**
   - Ingests `uptime_seconds`, `free_heap_bytes`, `wifi_rssi`, and local IP into `device_heartbeats`.
   - **Configuration Drift Detection:** Detects if edge configuration version lags behind cloud revision, returning `config_in_sync: false` and `active_config_version` to trigger client-side config synchronization.
   - Updates `is_online = True` and `last_heartbeat_at`.
3. **Diagnostic Edge Log Batch Ingestion (`POST /api/v1/device-gateway/logs`):**
   - Flushes buffered error and debug events from LittleFS into `device_logs`.
4. **Fleet Health Offline Sweeper (`POST /api/v1/device-gateway/offline-check`):**
   - Scans and automatically transitions devices to `is_online = False` if heartbeats cease beyond the configured threshold window.

---

### How to Verify Phase 8

#### 1. Run the Device Authentication Test Suite
From the project root:
```powershell
python -m pytest backend/tests/test_device_authentication.py -v
```

Run all platform test suites across the platform (51 tests):
```powershell
python -m pytest backend/tests/ -v
```

#### 2. Verified Test Matrix (`test_device_authentication.py`):
- `test_device_successful_handshake_and_authentication`: Validates token, chip ID, MAC address, session JWT issuance, and MQTT topic map.
- `test_device_authentication_invalid_token_rejected`: Rejection of wrong token with HTTP 401 `DEVICE_AUTHENTICATION_FAILED`.
- `test_device_authentication_hardware_mismatch_rejected`: Rejection of token on cloned hardware with HTTP 403 `HARDWARE_IDENTITY_MISMATCH`.
- `test_device_authentication_revoked_credential_rejected`: Rejection of revoked credentials with HTTP 403 `CREDENTIAL_REVOKED`.
- `test_device_heartbeat_ingestion_and_telemetry`: Ingestion of metrics and time-series record creation.
- `test_device_heartbeat_detects_configuration_drift`: Asserts `config_in_sync: false` when edge lags cloud revision.
- `test_device_diagnostic_log_batch_ingestion`: Persists batch of edge logs into `device_logs`.
- `test_offline_detection_worker_marks_stale_devices`: Transitions uncommunicative nodes to `is_online = False`.

---

---

## 13. Phase 9 Verification: Cloud Configuration Synchronization

Phase 9 delivered the **versioned, decoupled configuration delivery engine** between Cloud and ESP32 hardware fleets. It guarantees that prices, feature modules, and telemetry timings can be modified dynamically in the cloud without requiring firmware recompilation or OTA flashing.

### Key Capabilities Delivered:
1. **Canonical JSON Serialization & SHA-256 Checksums (`config_service.py`):**
   - Deterministic, sorted-key JSON serialization ensures identical cryptographic hashes regardless of key order or whitespace variances.
   - Computes SHA-256 checksums over composite device payloads (modules, slot pricing, relay pins, telemetry timings).
2. **Version Incrementor & Immutable Snapshot Archival:**
   - Any modification via `PATCH /api/v1/devices/{device_id}/config` or module toggling automatically increments `current_config_version`, marks `is_synced = False`, archives an immutable `ConfigurationVersion` record, and emits an audit log.
   - Publishes real-time config updates to simulated MQTT distribution topic `devices/{device_id}/config`.
3. **Heartbeat Drift Detection & Edge Sync Recovery:**
   - Heartbeats reporting outdated revisions trigger `config_in_sync: false`, directing the edge node to fetch the latest configuration payload.
4. **Edge Device Handshake & Acknowledgment (`POST /api/v1/devices/{device_id}/config/ack`):**
   - Validates that edge node computed matching SHA-256 checksum and applied the correct active version.
   - Transitions `is_synced = True` and timestamps `last_synced_at`.
   - Tampered or corrupted checksums are rejected with `CHECKSUM_MISMATCH`, keeping `is_synced = False` and logging security warnings.
5. **Configuration Rollback & Append-Only History:**
   - Admin can restore any historical version via `POST /api/v1/devices/{device_id}/config/rollback`.
   - Preserves append-only immutability by creating a new forward version holding the restored payload.
6. **Key-Level Configuration Diff Engine:**
   - Compares two arbitrary configuration revisions via `GET /api/v1/devices/{device_id}/config/diff?base_version=X&target_version=Y`.
7. **Embedded C Firmware Persistence:**
   - FreeRTOS/ESP-IDF NVS manager functions (`nvs_mgr_save_config_payload`, `nvs_mgr_verify_checksum`, `nvs_mgr_build_config_ack`).
   - MQTT topic handlers (`mqtt_mgr_subscribe_config`, `mqtt_mgr_publish_config_ack`).

---

### How to Verify Phase 9

#### 1. Run the Configuration Synchronization Test Suite
From the project root:
```powershell
python -m pytest backend/tests/test_config_sync.py -v
```

#### 2. Run All 7 Test Suites Across the Entire Platform (62 tests):
```powershell
python -m pytest backend/tests/ -v
```

#### 3. Verified Test Matrix (`test_config_sync.py`):
- `test_canonical_checksum_generation_determinism`: Validates deterministic SHA-256 hash across varied key insertion orders.
- `test_composite_config_payload_generation`: Verifies composite payload generation for Vending (`slots`, `prices`, `pins`) and RFID (`reader_mode`).
- `test_cloud_config_update_bumps_version_and_marks_unsynced`: Updates configuration, asserts version increment, `is_synced = False`, version archival, and MQTT publication.
- `test_heartbeat_detects_out_of_sync_drift`: Edge heartbeat reporting stale version receives `config_in_sync: False`.
- `test_edge_device_fetches_active_config_and_acknowledges`: Edge fetches active config, validates checksum, publishes successful ACK; cloud marks `is_synced = True`.
- `test_tampered_or_corrupt_checksum_ack_rejected`: Edge submitting invalid checksum receives `CHECKSUM_MISMATCH`, keeping `is_synced = False`.
- `test_stale_version_ack_rejected`: Edge submitting mismatched version receives `VERSION_MISMATCH`.
- `test_edge_hardware_error_reported_in_ack`: Edge reporting hardware write error logs event and keeps `is_synced = False`.
- `test_configuration_rollback_creates_forward_revision`: Restores historical version by generating a forward revision v3 preserving immutability.
- `test_configuration_diff_endpoint`: Returns field-level differences between revisions.
- `test_multi_tenant_isolation_blocks_cross_tenant_config_access`: Enforces strict HTTP 403 Forbidden on cross-tenant config operations.

---

## 14. Phase 10 Verification: Vending Product & Slot Management

Phase 10 delivered the **multi-tenant product catalog, machine slot configuration engine, and real-time fleet price synchronization**. It ensures that updating product prices or slot configurations instantly propagates across the fleet, automatically incrementing firmware configuration revisions and recalculating cryptographic SHA-256 checksums without firmware recompilation.

### Key Capabilities Delivered:
1. **Multi-Tenant Product Catalog CRUD (`/api/v1/vending/products`):**
   - Products are scoped strictly per tenant client (`tenant_id`).
   - Supports SKU codes, names, base prices (decimal currency units), descriptions, and image URLs.
   - Enforces referential integrity guards: products mapped to active machine slots cannot be deleted (`HTTP 409 PRODUCT_IN_USE`).
2. **Machine Slot Assignment & Inventory Management (`/api/v1/vending/machines/{device_id}/slots`):**
   - Direct slot configuration mapping products to physical motor GPIO pins (`motor_pin`), maximum capacity, and optional slot-specific override prices.
   - Bulk slot configuration endpoint for multi-slot updates in a single atomic transaction.
   - Dedicated inventory restock endpoint (`POST /restock`): incrementing stock level logs restocking audits without bumping the firmware configuration revision or invalidating edge checksums.
3. **Fleet Price Update Synchronization Engine (`vending_service.py`):**
   - When a product price changes (e.g. ₹40 -> ₹45), the service automatically queries all vending machines in the client's fleet that contain slots assigned to this product without price overrides.
   - For every affected machine:
     - Automatically rebuilds the composite configuration payload.
     - Increments `current_config_version`.
     - Recomputes the canonical SHA-256 checksum.
     - Flags `is_synced = False`.
     - Archives an immutable `ConfigurationVersion` record.
     - Emits an audit log (`SLOT_PRICE_UPDATED`).
     - Publishes a real-time MQTT message to `devices/{device_id}/config`.
4. **Strict Multi-Tenant Isolation:**
   - Prevents cross-tenant product modification, slot mapping, or machine inventory queries with HTTP 403 Forbidden.

---

### How to Verify Phase 10

#### 1. Run the Vending Product & Slot Test Suite
From the project root:
```powershell
python -m pytest backend/tests/test_vending_slots.py -v
```

#### 2. Run All 8 Test Suites Across the Entire Platform (75 tests):
```powershell
python -m pytest backend/tests/ -v
```

#### 3. Verified Test Matrix (`test_vending_slots.py`):
- `test_list_client_products`: Verifies tenant-scoped product catalog retrieval.
- `test_create_new_product`: Creates a product, validates database persistence, and checks audit trail.
- `test_create_duplicate_product_code_rejected`: Confirms unique product SKU codes within a tenant with HTTP 409.
- `test_get_single_product_detail`: Fetches single product metadata and verified schema mapping.
- `test_product_price_update_propagates_to_vending_fleet`: Core test asserting that updating a product base price automatically updates slot pricing, increments machine config version (e.g. v1 -> v2), updates checksum, marks `is_synced = False`, archives version, and publishes MQTT message.
- `test_list_machine_slots`: Lists physical slots for a machine with effective pricing resolution.
- `test_configure_single_slot`: Assigns product to slot, sets motor GPIO pin, and verifies config version bump.
- `test_slot_override_price`: Validates that slot-level override price takes precedence over catalog base price.
- `test_bulk_configure_slots`: Configures multiple slots atomically, triggering a single config revision increment.
- `test_restock_slot_inventory_does_not_bump_firmware_config`: Proves that adding stock replenishes inventory without invalidating edge checksums or incrementing config revisions.
- `test_cannot_delete_product_assigned_to_active_slot`: Guards against foreign key corruption when product is in active use.
- `test_delete_unassigned_product_succeeds`: Validates clean deletion of unmapped products.
- `test_multi_tenant_isolation_on_products_and_slots`: Enforces strict cross-tenant access control with HTTP 403.

---

## 15. Phase 11 Requirements (Next Milestone)

Upon approval of Phase 10, development will proceed to **Phase 11: Coin Payment Engine**:
- ESP32 hardware interrupt driver for pulse train detection with hardware debouncing on coin acceptor GPIO.
- Configurable pulse-to-denomination mapping synced via cloud configuration (e.g., 1 pulse = ₹1, 2 pulses = ₹2, 5 pulses = ₹5).
- Autonomous edge vend logic: dispenses when accumulated credit >= price during cloud network disconnection.
- Local offline transaction buffer in LittleFS and cloud reconciliation upon reconnect.

---
*Multi-Tenant Cloud IoT Platform — Engineered for Industrial Commercial Deployment*




