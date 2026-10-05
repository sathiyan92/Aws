# Multi-Tenant Cloud IoT Platform for Vending & RFID Systems

[![Platform Architecture](https://img.shields.io/badge/Architecture-Phase%201%20Completed-brightgreen.svg)](#)
[![Status](https://img.shields.io/badge/Current%20State-Phase%201%20Foundation-blue.svg)](#)
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

## 6. Phase 2 Requirements (Next Milestone)

Upon approval of Phase 1, development will proceed to **Phase 2: Database Schema & Data Model**.

Phase 2 will implement:
- Relational schema definitions for all 20 required entities:
  - `users`, `clients`, `devices`, `device_types`, `device_modules`, `device_credentials`
  - `device_configs`, `configuration_versions`
  - `products`, `machine_slots`
  - `firmware_versions`, `ota_deployments`
  - `rfid_cards`, `employees`, `attendance_events`
  - `orders`, `payments`, `transactions`
  - `device_heartbeats`, `device_logs`, `audit_logs`
- Multi-tenant foreign key constraints, composite unique keys, and tenant index optimization.
- Migration engine setup (SQL / Alembic).
- Initial seed data for system roles, default device types, and manufacturer admin account.

---
*Multi-Tenant Cloud IoT Platform — Engineered for Industrial Commercial Deployment*
