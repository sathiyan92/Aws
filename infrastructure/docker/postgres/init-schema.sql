-- ==============================================================================
-- MULTI-TENANT CLOUD IoT PLATFORM FOR VENDING & RFID SYSTEMS
-- PostgreSQL Production DDL Schema (Phase 2 Deliverable)
-- ==============================================================================

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ------------------------------------------------------------------------------
-- 1. CLIENTS (TENANTS)
-- ------------------------------------------------------------------------------
CREATE TABLE clients (
    id VARCHAR(36) PRIMARY KEY,
    client_code VARCHAR(32) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    contact_email VARCHAR(255) NOT NULL,
    contact_phone VARCHAR(50),
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    address TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_clients_status ON clients(status);

-- ------------------------------------------------------------------------------
-- 2. USERS (SUPERADMIN & TENANT USERS)
-- ------------------------------------------------------------------------------
CREATE TABLE users (
    id VARCHAR(36) PRIMARY KEY,
    client_id VARCHAR(36) REFERENCES clients(id) ON DELETE CASCADE,
    username VARCHAR(64) NOT NULL UNIQUE,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    role VARCHAR(32) NOT NULL, -- MANUFACTURER_ADMIN, MANUFACTURER_SUPPORT, CLIENT_ADMIN, CLIENT_OPERATOR, CLIENT_VIEWER
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_users_client_role ON users(client_id, role);
CREATE INDEX idx_users_status ON users(status);

-- ------------------------------------------------------------------------------
-- 3. DEVICE TYPES (EXTENSIBLE REGISTRY)
-- ------------------------------------------------------------------------------
CREATE TABLE device_types (
    id VARCHAR(36) PRIMARY KEY,
    code VARCHAR(64) NOT NULL UNIQUE, -- VENDING_MACHINE, RFID_ATTENDANCE
    name VARCHAR(128) NOT NULL,
    description TEXT,
    supported_modules JSONB,
    capability_schema JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ------------------------------------------------------------------------------
-- 4. DEVICES (PHYSICAL HARDWARE FLEET)
-- ------------------------------------------------------------------------------
CREATE TABLE devices (
    id VARCHAR(36) PRIMARY KEY,
    device_id VARCHAR(32) NOT NULL UNIQUE, -- VM-000001, RFID-000001
    client_id VARCHAR(36) REFERENCES clients(id) ON DELETE SET NULL,
    device_type_id VARCHAR(36) NOT NULL REFERENCES device_types(id) ON DELETE RESTRICT,
    hardware_id VARCHAR(64) NOT NULL,
    chip_id VARCHAR(64) NOT NULL,
    mac_address VARCHAR(32) NOT NULL,
    factory_serial VARCHAR(64) NOT NULL UNIQUE,
    status VARCHAR(32) NOT NULL DEFAULT 'PROVISIONED',
    is_online BOOLEAN NOT NULL DEFAULT FALSE,
    current_firmware_version VARCHAR(32) NOT NULL DEFAULT 'v1.0.0',
    current_config_version INTEGER NOT NULL DEFAULT 1,
    last_heartbeat_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_devices_client_status ON devices(client_id, status);
CREATE INDEX idx_devices_chip_mac ON devices(chip_id, mac_address);
CREATE INDEX idx_devices_last_heartbeat ON devices(last_heartbeat_at);

-- ------------------------------------------------------------------------------
-- 5. DEVICE MODULES (INDEPENDENT HARDWARE FEATURE FLAGS)
-- ------------------------------------------------------------------------------
CREATE TABLE device_modules (
    id VARCHAR(36) PRIMARY KEY,
    device_id VARCHAR(36) NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    module_code VARCHAR(64) NOT NULL, -- QR_PAYMENT, COIN_PAYMENT, RFID_ACCESS
    is_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    configuration JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_device_module UNIQUE (device_id, module_code)
);
CREATE INDEX idx_device_module_enabled ON device_modules(device_id, module_code, is_enabled);

-- ------------------------------------------------------------------------------
-- 6. DEVICE CREDENTIALS (AUTHENTICATION MATERIAL)
-- ------------------------------------------------------------------------------
CREATE TABLE device_credentials (
    id VARCHAR(36) PRIMARY KEY,
    device_id VARCHAR(36) NOT NULL UNIQUE REFERENCES devices(id) ON DELETE CASCADE,
    auth_type VARCHAR(32) NOT NULL DEFAULT 'TOKEN',
    token_hash VARCHAR(255),
    client_cert_fingerprint VARCHAR(128),
    secret_key_hash VARCHAR(255),
    is_revoked BOOLEAN NOT NULL DEFAULT FALSE,
    last_used_at TIMESTAMP WITH TIME ZONE,
    expires_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ------------------------------------------------------------------------------
-- 7. DEVICE CONFIGS (ACTIVE SYNCHRONIZED STATE)
-- ------------------------------------------------------------------------------
CREATE TABLE device_configs (
    id VARCHAR(36) PRIMARY KEY,
    device_id VARCHAR(36) NOT NULL UNIQUE REFERENCES devices(id) ON DELETE CASCADE,
    client_id VARCHAR(36) REFERENCES clients(id) ON DELETE CASCADE,
    active_version INTEGER NOT NULL DEFAULT 1,
    config_payload JSONB NOT NULL,
    checksum VARCHAR(64) NOT NULL,
    is_synced BOOLEAN NOT NULL DEFAULT FALSE,
    last_synced_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_device_configs_client ON device_configs(client_id);

-- ------------------------------------------------------------------------------
-- 8. CONFIGURATION VERSIONS (AUDITABLE ROLLBACK HISTORY)
-- ------------------------------------------------------------------------------
CREATE TABLE configuration_versions (
    id VARCHAR(36) PRIMARY KEY,
    device_id VARCHAR(36) NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    client_id VARCHAR(36) REFERENCES clients(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    config_payload JSONB NOT NULL,
    checksum VARCHAR(64) NOT NULL,
    change_reason VARCHAR(255),
    created_by_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_device_config_version UNIQUE (device_id, version_number)
);
CREATE INDEX idx_config_history_lookup ON configuration_versions(device_id, version_number);

-- ------------------------------------------------------------------------------
-- 9. PRODUCTS (TENANT PRODUCT CATALOG)
-- ------------------------------------------------------------------------------
CREATE TABLE products (
    id VARCHAR(36) PRIMARY KEY,
    client_id VARCHAR(36) NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    product_code VARCHAR(64) NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    price INTEGER NOT NULL, -- Price in paise / smallest currency unit
    image_url VARCHAR(512),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_client_product_code UNIQUE (client_id, product_code)
);
CREATE INDEX idx_products_client_active ON products(client_id, is_active);

-- ------------------------------------------------------------------------------
-- 10. MACHINE SLOTS (VENDING HARDWARE COILS & PINS)
-- ------------------------------------------------------------------------------
CREATE TABLE machine_slots (
    id VARCHAR(36) PRIMARY KEY,
    device_id VARCHAR(36) NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    client_id VARCHAR(36) NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    slot_number INTEGER NOT NULL,
    slot_code VARCHAR(32) NOT NULL,
    product_id VARCHAR(36) REFERENCES products(id) ON DELETE SET NULL,
    override_price INTEGER,
    capacity INTEGER NOT NULL DEFAULT 10,
    current_stock INTEGER NOT NULL DEFAULT 0,
    motor_pin INTEGER,
    pulse_duration_ms INTEGER NOT NULL DEFAULT 500,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_device_slot_number UNIQUE (device_id, slot_number)
);
CREATE INDEX idx_slots_client_device ON machine_slots(client_id, device_id);

-- ------------------------------------------------------------------------------
-- 11. FIRMWARE VERSIONS (MANUFACTURER BINARY REPO)
-- ------------------------------------------------------------------------------
CREATE TABLE firmware_versions (
    id VARCHAR(36) PRIMARY KEY,
    device_type_id VARCHAR(36) NOT NULL REFERENCES device_types(id) ON DELETE RESTRICT,
    version_string VARCHAR(32) NOT NULL,
    hardware_revision VARCHAR(64) NOT NULL,
    binary_url VARCHAR(512) NOT NULL,
    file_size_bytes INTEGER NOT NULL,
    sha256_checksum VARCHAR(64) NOT NULL,
    signature TEXT NOT NULL,
    changelog TEXT,
    is_deprecated BOOLEAN NOT NULL DEFAULT FALSE,
    created_by_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_firmware_type_version_hw UNIQUE (device_type_id, version_string, hardware_revision)
);
CREATE INDEX idx_firmware_lookup ON firmware_versions(device_type_id, version_string);

-- ------------------------------------------------------------------------------
-- 12. OTA DEPLOYMENTS (DEVICE UPDATE JOBS)
-- ------------------------------------------------------------------------------
CREATE TABLE ota_deployments (
    id VARCHAR(36) PRIMARY KEY,
    firmware_version_id VARCHAR(36) NOT NULL REFERENCES firmware_versions(id) ON DELETE RESTRICT,
    device_id VARCHAR(36) NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    client_id VARCHAR(36) REFERENCES clients(id) ON DELETE SET NULL,
    deployment_status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    error_message TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    created_by_user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_ota_device_status ON ota_deployments(device_id, deployment_status);

-- ------------------------------------------------------------------------------
-- 13. EMPLOYEES (TENANT PERSONNEL ROSTER)
-- ------------------------------------------------------------------------------
CREATE TABLE employees (
    id VARCHAR(36) PRIMARY KEY,
    client_id VARCHAR(36) NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    employee_code VARCHAR(64) NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    department VARCHAR(128),
    designation VARCHAR(128),
    email VARCHAR(255),
    phone VARCHAR(50),
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_client_employee_code UNIQUE (client_id, employee_code)
);
CREATE INDEX idx_employees_client_status ON employees(client_id, status);

-- ------------------------------------------------------------------------------
-- 14. RFID CARDS (CARD LIFECYCLE & REPLACEMENT HISTORY)
-- ------------------------------------------------------------------------------
CREATE TABLE rfid_cards (
    id VARCHAR(36) PRIMARY KEY,
    client_id VARCHAR(36) NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    employee_id VARCHAR(36) REFERENCES employees(id) ON DELETE SET NULL,
    card_uid VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE', -- ACTIVE, DISABLED, BLOCKED, REPLACED
    replacement_card_id VARCHAR(36) REFERENCES rfid_cards(id) ON DELETE SET NULL,
    issued_at TIMESTAMP WITH TIME ZONE,
    revoked_at TIMESTAMP WITH TIME ZONE,
    revocation_reason VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_client_card_uid UNIQUE (client_id, card_uid)
);
CREATE INDEX idx_rfid_cards_client_status ON rfid_cards(client_id, status);

-- ------------------------------------------------------------------------------
-- 15. ATTENDANCE EVENTS (IMMUTABLE LOG WITH IDEMPOTENCY KEY)
-- ------------------------------------------------------------------------------
CREATE TABLE attendance_events (
    id VARCHAR(36) PRIMARY KEY,
    event_uuid VARCHAR(64) NOT NULL UNIQUE,
    client_id VARCHAR(36) NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    device_id VARCHAR(36) NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    card_id VARCHAR(36) REFERENCES rfid_cards(id) ON DELETE SET NULL,
    employee_id VARCHAR(36) REFERENCES employees(id) ON DELETE SET NULL,
    card_uid_scanned VARCHAR(64) NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    event_type VARCHAR(16) NOT NULL, -- IN, OUT, UNKNOWN
    is_offline_sync BOOLEAN NOT NULL DEFAULT FALSE,
    synced_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_attendance_client_time ON attendance_events(client_id, timestamp);
CREATE INDEX idx_attendance_device_time ON attendance_events(device_id, timestamp);
CREATE INDEX idx_attendance_employee_time ON attendance_events(employee_id, timestamp);

-- ------------------------------------------------------------------------------
-- 16. ORDERS (VENDING DISPENSE PURCHASE ORDERS)
-- ------------------------------------------------------------------------------
CREATE TABLE orders (
    id VARCHAR(36) PRIMARY KEY,
    order_number VARCHAR(64) NOT NULL UNIQUE,
    client_id VARCHAR(36) NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    device_id VARCHAR(36) NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    slot_id VARCHAR(36) NOT NULL REFERENCES machine_slots(id) ON DELETE RESTRICT,
    product_id VARCHAR(36) NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    payment_method VARCHAR(32) NOT NULL,
    unit_price INTEGER NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    total_amount INTEGER NOT NULL,
    order_status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    dispense_token VARCHAR(128),
    dispense_token_expires_at TIMESTAMP WITH TIME ZONE,
    dispensed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_orders_client_created ON orders(client_id, created_at);
CREATE INDEX idx_orders_device_created ON orders(device_id, created_at);
CREATE INDEX idx_orders_status ON orders(order_status);

-- ------------------------------------------------------------------------------
-- 17. PAYMENTS (GATEWAY INTENTS & SETTLEMENT)
-- ------------------------------------------------------------------------------
CREATE TABLE payments (
    id VARCHAR(36) PRIMARY KEY,
    order_id VARCHAR(36) NOT NULL UNIQUE REFERENCES orders(id) ON DELETE CASCADE,
    client_id VARCHAR(36) NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    gateway_provider VARCHAR(64) NOT NULL,
    gateway_payment_intent_id VARCHAR(128),
    gateway_transaction_id VARCHAR(128),
    amount INTEGER NOT NULL,
    currency VARCHAR(8) NOT NULL DEFAULT 'INR',
    payment_status VARCHAR(32) NOT NULL DEFAULT 'INITIATED',
    raw_gateway_response JSONB,
    paid_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_payments_client_status ON payments(client_id, payment_status);

-- ------------------------------------------------------------------------------
-- 18. TRANSACTIONS (IMMUTABLE FINANCIAL LEDGER)
-- ------------------------------------------------------------------------------
CREATE TABLE transactions (
    id VARCHAR(36) PRIMARY KEY,
    transaction_number VARCHAR(64) NOT NULL UNIQUE,
    client_id VARCHAR(36) NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    device_id VARCHAR(36) NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    order_id VARCHAR(36) REFERENCES orders(id) ON DELETE SET NULL,
    payment_id VARCHAR(36) REFERENCES payments(id) ON DELETE SET NULL,
    transaction_type VARCHAR(32) NOT NULL,
    amount INTEGER NOT NULL,
    currency VARCHAR(8) NOT NULL DEFAULT 'INR',
    coins_inserted JSONB,
    change_dispensed INTEGER NOT NULL DEFAULT 0,
    dispense_status VARCHAR(32) NOT NULL,
    is_offline_sync BOOLEAN NOT NULL DEFAULT FALSE,
    transacted_at TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_transactions_client_time ON transactions(client_id, transacted_at);
CREATE INDEX idx_transactions_device_time ON transactions(device_id, transacted_at);

-- ------------------------------------------------------------------------------
-- 19. DEVICE HEARTBEATS (HIGH-FREQUENCY METRICS)
-- ------------------------------------------------------------------------------
CREATE TABLE device_heartbeats (
    id VARCHAR(36) PRIMARY KEY,
    device_id VARCHAR(36) NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    client_id VARCHAR(36) REFERENCES clients(id) ON DELETE CASCADE,
    status VARCHAR(32) NOT NULL DEFAULT 'ONLINE',
    current_firmware_version VARCHAR(32) NOT NULL,
    current_config_version INTEGER NOT NULL,
    uptime_seconds INTEGER NOT NULL,
    free_heap_bytes INTEGER NOT NULL,
    wifi_rssi INTEGER,
    ip_address VARCHAR(45),
    active_errors JSONB,
    recorded_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_heartbeat_device_recorded ON device_heartbeats(device_id, recorded_at);

-- ------------------------------------------------------------------------------
-- 20. DEVICE LOGS (EDGE DIAGNOSTICS & FAULTS)
-- ------------------------------------------------------------------------------
CREATE TABLE device_logs (
    id VARCHAR(36) PRIMARY KEY,
    device_id VARCHAR(36) NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    client_id VARCHAR(36) REFERENCES clients(id) ON DELETE CASCADE,
    log_level VARCHAR(16) NOT NULL,
    subsystem VARCHAR(32) NOT NULL,
    message TEXT NOT NULL,
    log_data JSONB,
    recorded_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_device_logs_device_time ON device_logs(device_id, recorded_at);
CREATE INDEX idx_device_logs_level_time ON device_logs(log_level, recorded_at);

-- ------------------------------------------------------------------------------
-- 21. AUDIT LOGS (SECURITY & MUTATION AUDIT TRAIL)
-- ------------------------------------------------------------------------------
CREATE TABLE audit_logs (
    id VARCHAR(36) PRIMARY KEY,
    client_id VARCHAR(36) REFERENCES clients(id) ON DELETE SET NULL,
    user_id VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    action VARCHAR(64) NOT NULL,
    entity_type VARCHAR(64) NOT NULL,
    entity_id VARCHAR(64) NOT NULL,
    old_state JSONB,
    new_state JSONB,
    ip_address VARCHAR(45),
    user_agent VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_audit_client_created ON audit_logs(client_id, created_at);
CREATE INDEX idx_audit_entity ON audit_logs(entity_type, entity_id);

-- ==============================================================================
-- END OF SCHEMA DEFINITION
-- ==============================================================================
