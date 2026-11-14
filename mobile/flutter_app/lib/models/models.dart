class UserModel {
  final String id;
  final String username;
  final String? email;
  final String? fullName;
  final String role;
  final String? clientId;

  UserModel({
    required this.id,
    required this.username,
    this.email,
    this.fullName,
    required this.role,
    this.clientId,
  });

  bool get isManufacturerAdmin => role == 'MANUFACTURER_ADMIN' || role == 'SUPER_ADMIN';
  bool get isClientAdmin => role == 'CLIENT_ADMIN' || role == 'VENDOR';

  factory UserModel.fromJson(Map<String, dynamic> json) {
    return UserModel(
      id: json['id']?.toString() ?? '',
      username: json['username'] ?? '',
      email: json['email'],
      fullName: json['full_name'],
      role: json['role'] ?? 'CLIENT_ADMIN',
      clientId: json['client_id']?.toString(),
    );
  }

  Map<String, dynamic> toJson() => {
    'id': id,
    'username': username,
    'email': email,
    'full_name': fullName,
    'role': role,
    'client_id': clientId,
  };
}

class DeviceModel {
  final String id;
  final String deviceId;
  final String name;
  final String? clientName;
  final String? clientId;
  final String status;
  final String paymentMode;
  final int currentStock;
  final int maxStock;
  final double upiPrice;
  final double coinPrice;
  final int totalDispensed;
  final String? ipAddress;
  final String? macAddress;
  final String firmwareVersion;
  final int? rssi;
  final bool isOnline;
  final String? lastSeen;
  final bool stockManagementEnabled;

  DeviceModel({
    required this.id,
    required this.deviceId,
    required this.name,
    this.clientName,
    this.clientId,
    required this.status,
    required this.paymentMode,
    required this.currentStock,
    required this.maxStock,
    required this.upiPrice,
    required this.coinPrice,
    required this.totalDispensed,
    this.ipAddress,
    this.macAddress,
    required this.firmwareVersion,
    this.rssi,
    required this.isOnline,
    this.lastSeen,
    this.stockManagementEnabled = true,
  });

  factory DeviceModel.fromJson(Map<String, dynamic> json) {
    double upi = 5.0;
    double coin = 5.0;
    int stock = 10;
    int maxStk = 50;
    String mode = 'BOTH';
    bool qrEnabled = true;
    bool coinEnabled = true;

    if (json['modules'] is List) {
      for (final m in json['modules']) {
        final code = m['module_code']?.toString() ?? '';
        final isEnabled = m['is_enabled'] == true;
        final cfg = (m['configuration'] is Map) ? m['configuration'] as Map : {};
        if (code == 'QR_PAYMENT') {
          qrEnabled = isEnabled;
          if (cfg['amount'] is num) upi = (cfg['amount'] as num).toDouble();
          if (cfg['amount_rupees'] is num) upi = (cfg['amount_rupees'] as num).toDouble();
        } else if (code == 'COIN_PAYMENT') {
          coinEnabled = isEnabled;
          if (cfg['coin_price'] is num) coin = (cfg['coin_price'] as num).toDouble();
          if (cfg['price'] is num) coin = (cfg['price'] as num).toDouble();
        } else if (code == 'INVENTORY' || code == 'STOCK') {
          if (cfg['current_stock'] is num) stock = (cfg['current_stock'] as num).toInt();
          if (cfg['max_stock'] is num) maxStk = (cfg['max_stock'] as num).toInt();
        }
      }
      if (qrEnabled && coinEnabled) {
        mode = 'BOTH';
      } else if (qrEnabled) {
        mode = 'QR_ONLY';
      } else if (coinEnabled) {
        mode = 'COIN_ONLY';
      }
    }

    if (json['upi_price'] is num) upi = (json['upi_price'] as num).toDouble();
    if (json['coin_price'] is num) coin = (json['coin_price'] as num).toDouble();
    if (json['current_stock'] is num) stock = (json['current_stock'] as num).toInt();
    if (json['max_stock'] is num) maxStk = (json['max_stock'] as num).toInt();
    if (json['payment_mode'] is String) mode = json['payment_mode'];

    final online = json['is_online'] == true || json['status'] == 'ONLINE';

    return DeviceModel(
      id: json['id']?.toString() ?? '',
      deviceId: json['device_id'] ?? json['id'] ?? '',
      name: json['name'] ?? json['device_id'] ?? 'Machine',
      clientName: json['client_name'] ?? 'Unassigned',
      clientId: json['client_id']?.toString(),
      status: json['status'] ?? (online ? 'ONLINE' : 'ACTIVE'),
      paymentMode: mode,
      currentStock: stock,
      maxStock: maxStk,
      upiPrice: upi,
      coinPrice: coin,
      totalDispensed: json['total_dispensed'] is int ? json['total_dispensed'] : 0,
      ipAddress: json['ip_address'],
      macAddress: json['mac_address'],
      firmwareVersion: json['current_firmware_version'] ?? json['firmware_version'] ?? 'v1.0.0',
      rssi: json['rssi'] is int ? json['rssi'] : null,
      isOnline: online,
      lastSeen: json['last_heartbeat_at'] ?? json['last_seen'],
      stockManagementEnabled: json['stock_management_enabled'] != false,
    );
  }
}

class QrConfigModel {
  final String deviceId;
  final String standeeUpiLink;
  final String? activeCustomQr;
  final double amountRupees;
  final String productName;
  final bool isCoinEnabled;
  final double coinPrice;
  final bool stockManagementEnabled;
  final int currentStock;
  final String paymentMode;
  final String wifiSsid;
  final String wifiPassword;
  final String? trId;
  final String? vpa;
  final int configVersion;

  QrConfigModel({
    required this.deviceId,
    required this.standeeUpiLink,
    this.activeCustomQr,
    required this.amountRupees,
    required this.productName,
    required this.isCoinEnabled,
    required this.coinPrice,
    this.stockManagementEnabled = true,
    this.currentStock = 50,
    this.paymentMode = 'BOTH',
    this.wifiSsid = '',
    this.wifiPassword = '',
    this.trId,
    this.vpa,
    this.configVersion = 1,
  });

  factory QrConfigModel.fromJson(String deviceId, Map<String, dynamic> json) {
    final rawPayload = json['qr_payload'] ?? json['custom_qr_payload'] ?? json['standee_upi_link'] ?? json['active_custom_qr'] ?? '';
    return QrConfigModel(
      deviceId: deviceId,
      standeeUpiLink: rawPayload.toString(),
      activeCustomQr: json['active_custom_qr'] ?? rawPayload.toString(),
      amountRupees: (json['amount_rupees'] is num) ? (json['amount_rupees'] as num).toDouble() : 2.0,
      productName: json['product_name'] ?? 'Commercial Vending Item',
      isCoinEnabled: json['has_coin_payment'] != false && json['is_coin_enabled'] != false,
      coinPrice: (json['coin_price'] is num) ? (json['coin_price'] as num).toDouble() : 5.0,
      stockManagementEnabled: json['stock_management_enabled'] != false,
      currentStock: json['current_stock'] is int ? json['current_stock'] : 50,
      paymentMode: (json['payment_mode'] ?? 'BOTH').toString().toUpperCase(),
      wifiSsid: json['wifi_ssid']?.toString() ?? '',
      wifiPassword: json['wifi_password']?.toString() ?? '',
      trId: json['tr_id']?.toString(),
      vpa: json['razorpay_upi_vpa']?.toString() ?? json['vpa']?.toString(),
      configVersion: json['config_version'] is int ? json['config_version'] : 1,
    );
  }
}

class FirmwareModel {
  final String id;
  final String version;
  final String deviceTypeCode;
  final String filename;
  final int fileSizeBytes;
  final String? description;
  final String createdAt;

  FirmwareModel({
    required this.id,
    required this.version,
    required this.deviceTypeCode,
    required this.filename,
    required this.fileSizeBytes,
    this.description,
    required this.createdAt,
  });

  factory FirmwareModel.fromJson(Map<String, dynamic> json) {
    final rawUrl = json['binary_url']?.toString() ?? '';
    final fname = rawUrl.isNotEmpty ? rawUrl.split('/').last : (json['filename'] ?? 'firmware.bin');
    return FirmwareModel(
      id: json['id']?.toString() ?? '',
      version: json['version_string'] ?? json['version'] ?? 'v1.0.0',
      deviceTypeCode: json['device_type_code'] ?? 'VENDING_MACHINE',
      filename: fname,
      fileSizeBytes: json['file_size_bytes'] is int ? json['file_size_bytes'] : 0,
      description: json['changelog'] ?? json['description'],
      createdAt: json['created_at'] ?? '',
    );
  }
}

class OtaDeploymentModel {
  final String id;
  final String deviceId;
  final String targetVersion;
  final String status;
  final int progressPercent;
  final String? updatedAt;

  OtaDeploymentModel({
    required this.id,
    required this.deviceId,
    required this.targetVersion,
    required this.status,
    required this.progressPercent,
    this.updatedAt,
  });

  factory OtaDeploymentModel.fromJson(Map<String, dynamic> json) {
    return OtaDeploymentModel(
      id: json['id']?.toString() ?? '',
      deviceId: json['device_code'] ?? json['device_id'] ?? '',
      targetVersion: json['version_string'] ?? json['target_version'] ?? json['version'] ?? 'v1.0.0',
      status: json['deployment_status'] ?? json['status'] ?? 'QUEUED',
      progressPercent: json['progress_percent'] is int ? json['progress_percent'] : 0,
      updatedAt: json['updated_at'] ?? json['created_at'],
    );
  }
}

class DiscoveryDeviceModel {
  final String tempId;
  final String? macAddress;
  final String? ipAddress;
  final String? firmwareVersion;
  final String discoveredAt;

  DiscoveryDeviceModel({
    required this.tempId,
    this.macAddress,
    this.ipAddress,
    this.firmwareVersion,
    required this.discoveredAt,
  });

  factory DiscoveryDeviceModel.fromJson(Map<String, dynamic> json) {
    return DiscoveryDeviceModel(
      tempId: json['temp_id'] ?? json['device_id'] ?? json['id'] ?? '',
      macAddress: json['mac_address'],
      ipAddress: json['ip_address'],
      firmwareVersion: json['firmware_version'],
      discoveredAt: json['discovered_at'] ?? json['created_at'] ?? 'Just now',
    );
  }
}

class ClientModel {
  final String id;
  final String name;
  final String code;
  final String? contactEmail;
  final int allocatedDevices;

  ClientModel({
    required this.id,
    required this.name,
    required this.code,
    this.contactEmail,
    required this.allocatedDevices,
  });

  factory ClientModel.fromJson(Map<String, dynamic> json) {
    return ClientModel(
      id: json['id']?.toString() ?? '',
      name: json['name'] ?? '',
      code: json['code'] ?? '',
      contactEmail: json['contact_email'],
      allocatedDevices: json['allocated_devices'] is int
          ? json['allocated_devices']
          : (json['devices_count'] is int ? json['devices_count'] : 0),
    );
  }
}
