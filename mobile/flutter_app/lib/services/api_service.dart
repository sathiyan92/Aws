import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import '../config/api_config.dart';
import '../models/models.dart';

class ApiService {
  static final ApiService _instance = ApiService._internal();
  factory ApiService() => _instance;
  ApiService._internal();

  String _baseUrl = ApiConfig.defaultBaseUrl;
  String? _token;
  UserModel? _currentUser;

  String get baseUrl => _baseUrl;
  String? get token => _token;
  UserModel? get currentUser => _currentUser;
  bool get isAuthenticated => _token != null;

  Future<void> init() async {
    final prefs = await SharedPreferences.getInstance();
    final savedServer = prefs.getString(ApiConfig.prefsServerKey);
    if (savedServer != null && savedServer.trim().isNotEmpty) {
      String clean = savedServer.trim().replaceAll(RegExp(r'/+$'), '');
      _baseUrl = clean.endsWith('/api/v1') ? clean : '$clean/api/v1';
    } else {
      _baseUrl = ApiConfig.defaultBaseUrl;
    }

    _token = prefs.getString(ApiConfig.prefsTokenKey);
    final userJsonStr = prefs.getString(ApiConfig.prefsUserKey);
    if (userJsonStr != null) {
      try {
        _currentUser = UserModel.fromJson(jsonDecode(userJsonStr));
      } catch (_) {}
    }
  }

  Future<void> setServerUrl(String newUrl) async {
    final prefs = await SharedPreferences.getInstance();
    String clean = newUrl.trim().replaceAll(RegExp(r'/+$'), '');
    _baseUrl = clean.endsWith('/api/v1') ? clean : '$clean/api/v1';
    await prefs.setString(ApiConfig.prefsServerKey, _baseUrl);
  }

  Map<String, String> _headers() {
    final map = <String, String>{
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    };
    if (_token != null && _token!.isNotEmpty) {
      map['Authorization'] = 'Bearer $_token';
    }
    return map;
  }

  // Auth: Login
  Future<UserModel> login(String usernameOrEmail, String password) async {
    final uri = Uri.parse('$_baseUrl${ApiConfig.login}');
    final response = await http.post(
      uri,
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'username_or_email': usernameOrEmail.trim(),
        'password': password.trim(),
      }),
    ).timeout(const Duration(seconds: 15));

    final data = jsonDecode(response.body);
    if (response.statusCode >= 200 && response.statusCode < 300) {
      _token = data['access_token'];
      _currentUser = UserModel.fromJson(data['user']);

      final prefs = await SharedPreferences.getInstance();
      if (_token != null) {
        await prefs.setString(ApiConfig.prefsTokenKey, _token!);
      }
      if (_currentUser != null) {
        await prefs.setString(ApiConfig.prefsUserKey, jsonEncode(_currentUser!.toJson()));
      }
      return _currentUser!;
    } else {
      final msg = data['detail'] ?? data['message'] ?? 'Login failed (${response.statusCode})';
      throw Exception(msg);
    }
  }

  Future<void> logout() async {
    _token = null;
    _currentUser = null;
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(ApiConfig.prefsTokenKey);
    await prefs.remove(ApiConfig.prefsUserKey);
  }

  // Get Fleet Devices (Robust parsing for both {devices: [...]} and {items: [...]})
  Future<List<DeviceModel>> getDevices({String? clientId}) async {
    String endpoint = '${ApiConfig.devices}?limit=150';
    if (clientId != null && clientId.isNotEmpty) {
      endpoint += '&client_id=$clientId';
    }
    final uri = Uri.parse('$_baseUrl$endpoint');
    final res = await http.get(uri, headers: _headers()).timeout(const Duration(seconds: 12));

    if (res.statusCode == 200) {
      final data = jsonDecode(res.body);
      List rawList = [];
      if (data is List) {
        rawList = data;
      } else if (data is Map) {
        rawList = data['devices'] ?? data['items'] ?? [];
      }
      return rawList.map((i) => DeviceModel.fromJson(i)).toList();
    } else {
      throw Exception('Failed to load fleet devices (${res.statusCode})');
    }
  }

  // Get Real Fleet Stats from SuperAdmin endpoint (/manufacturer/platform-stats)
  Future<Map<String, dynamic>> getStats() async {
    final uri = Uri.parse('$_baseUrl${ApiConfig.platformStats}');
    try {
      final res = await http.get(uri, headers: _headers()).timeout(const Duration(seconds: 10));
      if (res.statusCode == 200) {
        final d = jsonDecode(res.body);
        final modBreakdown = d['module_breakdown'] is Map ? d['module_breakdown'] : {};
        int activeMods = 0;
        modBreakdown.forEach((k, v) {
          if (v is num) activeMods += v.toInt();
        });

        return {
          'total_devices': d['devices_count'] ?? 0,
          'online_devices': d['online_devices_count'] ?? 0,
          'offline_devices': d['offline_devices_count'] ?? 0,
          'clients_count': d['clients_count'] ?? 0,
          'active_modules': activeMods > 0 ? activeMods : 4,
        };
      }
    } catch (_) {}
    return {
      'total_devices': 0,
      'online_devices': 0,
      'offline_devices': 0,
      'clients_count': 0,
      'active_modules': 4,
    };
  }

  // Get Hardware Discovery Queue (/devices/discovery-queue)
  Future<List<DiscoveryDeviceModel>> getDiscoveryQueue() async {
    final uri = Uri.parse('$_baseUrl${ApiConfig.discoveryQueue}');
    try {
      final res = await http.get(uri, headers: _headers()).timeout(const Duration(seconds: 8));
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body);
        List rawList = [];
        if (data is List) {
          rawList = data;
        } else if (data is Map) {
          rawList = data['items'] ?? data['queue'] ?? [];
        }
        return rawList.map((i) => DiscoveryDeviceModel.fromJson(i)).toList();
      }
    } catch (_) {}
    return [];
  }

  // Claim & Assign ID to Discovered Hardware
  Future<bool> claimDiscoveryDevice({
    required String macAddress,
    required String targetDeviceId,
    String? clientId,
  }) async {
    final uri = Uri.parse('$_baseUrl${ApiConfig.discoveryClaim}');
    final res = await http.post(
      uri,
      headers: _headers(),
      body: jsonEncode({
        'mac_address': macAddress,
        'device_id': targetDeviceId,
        'client_id': clientId,
        'device_type_code': 'VENDING_MACHINE',
      }),
    ).timeout(const Duration(seconds: 12));
    return res.statusCode >= 200 && res.statusCode < 300;
  }

  // Get Clients (Vendors)
  Future<List<ClientModel>> getClients() async {
    final uri = Uri.parse('$_baseUrl${ApiConfig.clients}?limit=50');
    try {
      final res = await http.get(uri, headers: _headers()).timeout(const Duration(seconds: 10));
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body);
        List list = (data is List) ? data : (data['clients'] ?? data['items'] ?? []);
        return list.map((i) => ClientModel.fromJson(i)).toList();
      }
    } catch (_) {}
    return [];
  }

  // Dynamic QR & Price Configuration (/orders/qr-config/{deviceId})
  Future<QrConfigModel> getQrConfig(String deviceId) async {
    final uri = Uri.parse('$_baseUrl${ApiConfig.qrConfig(deviceId)}');
    final res = await http.get(uri, headers: _headers()).timeout(const Duration(seconds: 10));
    if (res.statusCode == 200) {
      final data = jsonDecode(res.body);
      return QrConfigModel.fromJson(deviceId, data);
    } else {
      throw Exception('Failed to load QR configuration (${res.statusCode})');
    }
  }

  // Decode uploaded QR code image to UPI URI (/vending/decode-qr)
  Future<Map<String, dynamic>> decodeQrImage(String base64Image) async {
    final uri = Uri.parse('$_baseUrl${ApiConfig.decodeQr}');
    final res = await http.post(
      uri,
      headers: _headers(),
      body: jsonEncode({'image_data': base64Image}),
    ).timeout(const Duration(seconds: 15));
    if (res.statusCode >= 200 && res.statusCode < 300) {
      return jsonDecode(res.body) as Map<String, dynamic>;
    } else {
      throw Exception('QR decode failed (${res.statusCode}): ${res.body}');
    }
  }

  // Create Client Tenant / Vendor (/clients)
  Future<bool> createClient({
    required String clientCode,
    required String name,
    required String contactEmail,
    String? contactPhone,
    String? address,
    String? adminUsername,
    String? adminPassword,
    String? assignDeviceId,
  }) async {
    final uri = Uri.parse('$_baseUrl${ApiConfig.createClient}');
    final res = await http.post(
      uri,
      headers: _headers(),
      body: jsonEncode({
        'client_code': clientCode,
        'name': name,
        'contact_email': contactEmail,
        if (contactPhone != null && contactPhone.isNotEmpty) 'contact_phone': contactPhone,
        if (address != null && address.isNotEmpty) 'address': address,
        if (adminUsername != null && adminUsername.isNotEmpty) 'admin_username': adminUsername,
        if (adminPassword != null && adminPassword.isNotEmpty) 'admin_password': adminPassword,
        if (assignDeviceId != null && assignDeviceId.isNotEmpty) 'assign_device_id': assignDeviceId,
      }),
    ).timeout(const Duration(seconds: 15));
    if (res.statusCode >= 200 && res.statusCode < 300) {
      return true;
    } else {
      throw Exception('Create Vendor failed (${res.statusCode}): ${res.body}');
    }
  }

  // Create or Reset Vendor User Password (/clients/{clientId}/users)
  Future<bool> createClientUser({
    required String clientId,
    required String username,
    required String password,
    String? email,
    String? fullName,
  }) async {
    final uri = Uri.parse('$_baseUrl${ApiConfig.clientUsers(clientId)}');
    final res = await http.post(
      uri,
      headers: _headers(),
      body: jsonEncode({
        'username': username,
        'password': password,
        if (email != null && email.isNotEmpty) 'email': email,
        if (fullName != null && fullName.isNotEmpty) 'full_name': fullName,
      }),
    ).timeout(const Duration(seconds: 12));
    if (res.statusCode >= 200 && res.statusCode < 300) {
      return true;
    } else {
      throw Exception('Set Vendor User failed (${res.statusCode}): ${res.body}');
    }
  }

  // Register / Provision Physical Device (/devices)
  Future<bool> registerDevice({
    required String deviceTypeCode,
    required String hardwareId,
    String? macAddress,
    String? clientId,
  }) async {
    final uri = Uri.parse('$_baseUrl${ApiConfig.registerDevice}');
    final res = await http.post(
      uri,
      headers: _headers(),
      body: jsonEncode({
        'device_type_code': deviceTypeCode,
        'hardware_id': hardwareId,
        if (macAddress != null && macAddress.isNotEmpty) 'mac_address': macAddress,
        if (clientId != null && clientId.isNotEmpty) 'client_id': clientId,
      }),
    ).timeout(const Duration(seconds: 12));
    if (res.statusCode >= 200 && res.statusCode < 300) {
      return true;
    } else {
      throw Exception('Register Hardware failed (${res.statusCode}): ${res.body}');
    }
  }

  // Upload Firmware Artifact (.bin) (/ota/firmware/upload)
  Future<bool> uploadFirmware({
    required List<int> fileBytes,
    required String filename,
    required String versionString,
    String deviceTypeCode = 'VENDING_MACHINE',
    String? targetDeviceId,
  }) async {
    final uri = Uri.parse('$_baseUrl${ApiConfig.firmwareUpload}');
    final req = http.MultipartRequest('POST', uri);
    final headers = _headers();
    headers.remove('Content-Type');
    req.headers.addAll(headers);
    req.fields['version_string'] = versionString;
    req.fields['device_type_code'] = deviceTypeCode;
    if (targetDeviceId != null && targetDeviceId.isNotEmpty) {
      req.fields['target_device_id'] = targetDeviceId;
    }
    req.files.add(http.MultipartFile.fromBytes('file', fileBytes, filename: filename));

    final streamedRes = await req.send().timeout(const Duration(seconds: 45));
    final res = await http.Response.fromStream(streamedRes);
    if (res.statusCode >= 200 && res.statusCode < 300) {
      return true;
    } else {
      throw Exception('Firmware Upload failed (${res.statusCode}): ${res.body}');
    }
  }

  Future<bool> updateQrConfig(String deviceId, {
    required double price,
    required String standeeUpiLink,
    String? productName,
    double? coinPrice,
    bool? stockManagementEnabled,
    int? currentStock,
    String? paymentMode,
    String? wifiSsid,
    String? wifiPassword,
  }) async {
    final uri = Uri.parse('$_baseUrl${ApiConfig.qrConfig(deviceId)}');
    final res = await http.put(
      uri,
      headers: _headers(),
      body: jsonEncode({
        'amount_rupees': price,
        'custom_qr_payload': standeeUpiLink,
        'standee_upi_link': standeeUpiLink,
        'product_name': productName ?? 'Commercial Vending Item',
        if (coinPrice != null) 'coin_price': coinPrice,
        if (stockManagementEnabled != null) 'stock_management_enabled': stockManagementEnabled,
        if (currentStock != null) 'current_stock': currentStock,
        if (paymentMode != null) 'payment_mode': paymentMode,
        if (wifiSsid != null) 'wifi_ssid': wifiSsid,
        if (wifiPassword != null) 'wifi_password': wifiPassword,
      }),
    ).timeout(const Duration(seconds: 12));
    return res.statusCode >= 200 && res.statusCode < 300;
  }

  // OTA Firmware Hub (/ota/firmware)
  Future<List<FirmwareModel>> getFirmwareList() async {
    final uri = Uri.parse('$_baseUrl${ApiConfig.firmwareList}');
    try {
      final res = await http.get(uri, headers: _headers()).timeout(const Duration(seconds: 10));
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body);
        List list = (data is List) ? data : (data['firmware_versions'] ?? data['firmware'] ?? data['items'] ?? []);
        return list.map((i) => FirmwareModel.fromJson(i)).toList();
      }
    } catch (_) {}
    return [];
  }

  // OTA Deployments Status (/ota/deployments)
  Future<List<OtaDeploymentModel>> getOtaDeployments() async {
    final uri = Uri.parse('$_baseUrl${ApiConfig.otaDeployments}');
    try {
      final res = await http.get(uri, headers: _headers()).timeout(const Duration(seconds: 10));
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body);
        List list = (data is List) ? data : (data['deployments'] ?? data['items'] ?? []);
        return list.map((i) => OtaDeploymentModel.fromJson(i)).toList();
      }
    } catch (_) {}
    return [];
  }

  // Push OTA Update to Machine (/ota/deploy)
  Future<bool> deployOtaUpdate(String deviceId, String firmwareVersionId) async {
    final uri = Uri.parse('$_baseUrl${ApiConfig.otaDeploy}');
    final res = await http.post(
      uri,
      headers: _headers(),
      body: jsonEncode({
        'device_ids': [deviceId],
        'firmware_version_id': firmwareVersionId,
        'rollout_strategy': 'IMMEDIATE',
      }),
    ).timeout(const Duration(seconds: 15));
    return res.statusCode >= 200 && res.statusCode < 300;
  }

  // Trigger Hardware Test Dispense
  Future<Map<String, dynamic>> triggerDispense(String deviceId, {int pulses = 1}) async {
    final uri = Uri.parse('$_baseUrl${ApiConfig.deviceDispense(deviceId)}');
    final res = await http.post(
      uri,
      headers: _headers(),
      body: jsonEncode({'pulses': pulses}),
    ).timeout(const Duration(seconds: 15));

    final data = jsonDecode(res.body);
    if (res.statusCode >= 200 && res.statusCode < 300) {
      return data;
    } else {
      throw Exception(data['detail'] ?? 'Dispense command failed');
    }
  }

  // Update Stock & Pricing
  Future<bool> updateDeviceConfig(String deviceId, {
    int? currentStock,
    int? maxStock,
    double? upiPrice,
    double? coinPrice,
    String? paymentMode,
  }) async {
    final uri = Uri.parse('$_baseUrl${ApiConfig.deviceConfig(deviceId)}');
    final body = <String, dynamic>{};
    if (currentStock != null) body['current_stock'] = currentStock;
    if (maxStock != null) body['max_stock'] = maxStock;
    if (upiPrice != null) body['upi_price'] = upiPrice;
    if (coinPrice != null) body['coin_price'] = coinPrice;
    if (paymentMode != null) body['payment_mode'] = paymentMode;

    final res = await http.put(uri, headers: _headers(), body: jsonEncode(body))
        .timeout(const Duration(seconds: 10));
    return res.statusCode >= 200 && res.statusCode < 300;
  }
}
