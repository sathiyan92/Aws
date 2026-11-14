import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import '../models/models.dart';
import '../services/api_service.dart';
import 'login_screen.dart';

class OperationsScreen extends StatefulWidget {
  const OperationsScreen({super.key});

  @override
  State<OperationsScreen> createState() => _OperationsScreenState();
}

class _OperationsScreenState extends State<OperationsScreen> {
  int _currentTabIndex = 0;
  bool _isLoading = false;

  List<DeviceModel> _devices = [];
  List<DiscoveryDeviceModel> _discoveryQueue = [];
  List<ClientModel> _clients = [];
  List<FirmwareModel> _firmwareList = [];
  List<OtaDeploymentModel> _otaDeployments = [];
  Map<String, dynamic> _stats = {};

  // QR & Operating Settings Tab state
  String? _selectedQrDeviceId;
  QrConfigModel? _currentQrConfig;
  bool _isLoadingQr = false;
  final _qrUpiLinkCtrl = TextEditingController();
  final _qrPriceCtrl = TextEditingController(text: '2');
  final _qrProductCtrl = TextEditingController(text: 'Commercial Vending Item');
  final _stockQtyCtrl = TextEditingController(text: '50');
  final _wifiSsidCtrl = TextEditingController();
  final _wifiPasswordCtrl = TextEditingController();
  bool _stockManagementEnabled = true;
  String _paymentMode = 'BOTH'; // 'BOTH', 'QR_ONLY', 'COIN_ONLY'
  String? _selectedImageFilename;

  @override
  void initState() {
    super.initState();
    _loadAllData();
  }

  @override
  void dispose() {
    _qrUpiLinkCtrl.dispose();
    _qrPriceCtrl.dispose();
    _qrProductCtrl.dispose();
    _stockQtyCtrl.dispose();
    _wifiSsidCtrl.dispose();
    _wifiPasswordCtrl.dispose();
    super.dispose();
  }

  Future<void> _loadAllData() async {
    setState(() => _isLoading = true);
    try {
      final results = await Future.wait([
        ApiService().getDevices(),
        ApiService().getDiscoveryQueue(),
        ApiService().getClients(),
        ApiService().getStats(),
        ApiService().getFirmwareList(),
        ApiService().getOtaDeployments(),
      ]);
      if (!mounted) return;
      setState(() {
        _devices = results[0] as List<DeviceModel>;
        _discoveryQueue = results[1] as List<DiscoveryDeviceModel>;
        _clients = results[2] as List<ClientModel>;
        _stats = results[3] as Map<String, dynamic>;
        _firmwareList = results[4] as List<FirmwareModel>;
        _otaDeployments = results[5] as List<OtaDeploymentModel>;

        if (_devices.isNotEmpty) {
          if (_selectedQrDeviceId == null || !_devices.any((d) => d.deviceId == _selectedQrDeviceId)) {
            _selectedQrDeviceId = _devices.firstWhere(
              (d) => d.deviceId == 'VM-000001',
              orElse: () => _devices.first,
            ).deviceId;
            _loadDeviceQrConfig(_selectedQrDeviceId!);
          }
        }
      });
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Data error: $e'), backgroundColor: Colors.red),
        );
      }
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  Future<void> _loadDeviceQrConfig(String deviceId) async {
    setState(() => _isLoadingQr = true);
    try {
      final config = await ApiService().getQrConfig(deviceId);
      if (!mounted) return;
      setState(() {
        _currentQrConfig = config;
        _qrUpiLinkCtrl.text = config.standeeUpiLink;
        _qrPriceCtrl.text = config.amountRupees.toStringAsFixed(0);
        _qrProductCtrl.text = config.productName;
        _stockManagementEnabled = config.stockManagementEnabled;
        _stockQtyCtrl.text = config.currentStock.toString();
        _paymentMode = config.paymentMode;
        _wifiSsidCtrl.text = config.wifiSsid;
        _wifiPasswordCtrl.text = config.wifiPassword;
        _selectedImageFilename = null;
      });
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Failed to load settings: $e'), backgroundColor: Colors.red),
        );
      }
    } finally {
      if (mounted) setState(() => _isLoadingQr = false);
    }
  }

  Future<void> _saveQrConfig() async {
    final devId = _selectedQrDeviceId ?? (_devices.isNotEmpty ? _devices.first.deviceId : null);
    if (devId == null) return;
    final price = double.tryParse(_qrPriceCtrl.text.trim()) ?? 2.0;
    final link = _qrUpiLinkCtrl.text.trim();
    final prod = _qrProductCtrl.text.trim();
    final stock = int.tryParse(_stockQtyCtrl.text.trim()) ?? 50;

    try {
      final ok = await ApiService().updateQrConfig(
        devId,
        price: price,
        standeeUpiLink: link,
        productName: prod,
        stockManagementEnabled: _stockManagementEnabled,
        currentStock: stock,
        paymentMode: _paymentMode,
        wifiSsid: _wifiSsidCtrl.text.trim(),
        wifiPassword: _wifiPasswordCtrl.text.trim(),
      );
      if (!mounted) return;
      if (ok) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('✓ Synchronized settings to $devId!'),
            backgroundColor: const Color(0xFF10B981),
          ),
        );
        _loadAllData();
      }
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Update failed: $e'), backgroundColor: Colors.red),
      );
    }
  }

  Future<void> _pickAndDecodeQrImage({required ImageSource source}) async {
    try {
      final picker = ImagePicker();
      final picked = await picker.pickImage(source: source);
      if (picked == null) return;

      final bytes = await picked.readAsBytes();
      final base64String = 'data:image/png;base64,${base64Encode(bytes)}';

      setState(() {
        _selectedImageFilename = picked.name;
      });

      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Scanning & decoding QR code image...'),
          backgroundColor: Color(0xFF0284C7),
          duration: Duration(seconds: 2),
        ),
      );

      final result = await ApiService().decodeQrImage(base64String);
      if (!mounted) return;

      final qrPayload = result['qr_payload']?.toString();
      if (qrPayload != null && qrPayload.isNotEmpty) {
        setState(() {
          _qrUpiLinkCtrl.text = qrPayload;
          if (result['amount_rupees'] is num) {
            _qrPriceCtrl.text = (result['amount_rupees'] as num).toDouble().toStringAsFixed(0);
          }
          if (result['merchant_name'] != null && result['merchant_name'].toString().isNotEmpty) {
            _qrProductCtrl.text = result['merchant_name'].toString();
          }
        });
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('✓ QR Decoded: ${qrPayload.substring(0, qrPayload.length > 35 ? 35 : qrPayload.length)}...'),
            backgroundColor: const Color(0xFF10B981),
          ),
        );
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Could not decode QR payload. You can paste the UPI link directly.'),
            backgroundColor: Colors.orange,
          ),
        );
      }
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('QR Upload failed: $e'), backgroundColor: Colors.red),
      );
    }
  }

  void _showQrImageSourcePicker() {
    showModalBottomSheet(
      context: context,
      backgroundColor: const Color(0xFF131B2E),
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (ctx) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 20, horizontal: 16),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Text(
                'Upload QR Code / Standee Image',
                style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.w700),
              ),
              const SizedBox(height: 16),
              ListTile(
                leading: const Icon(Icons.photo_library, color: Color(0xFF38BDF8)),
                title: const Text('Choose from Photo Gallery', style: TextStyle(color: Colors.white)),
                onTap: () {
                  Navigator.pop(ctx);
                  _pickAndDecodeQrImage(source: ImageSource.gallery);
                },
              ),
              ListTile(
                leading: const Icon(Icons.camera_alt, color: Color(0xFF10B981)),
                title: const Text('Take Photo with Camera', style: TextStyle(color: Colors.white)),
                onTap: () {
                  Navigator.pop(ctx);
                  _pickAndDecodeQrImage(source: ImageSource.camera);
                },
              ),
            ],
          ),
        ),
      ),
    );
  }

  void _applyStandeePreset(double price, String tr) {
    setState(() {
      _qrPriceCtrl.text = price.toStringAsFixed(0);
      _qrUpiLinkCtrl.text = 'upi://pay?am=${price.toStringAsFixed(2)}&cu=INR&mc=5300&mode=19&pa=gtech282722.rzp@rxairtel&tn=Payment%20To%20GTECH&tr=$tr';
      _qrProductCtrl.text = 'G-TECH Smart Dispenser';
    });
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text('📌 Loaded ₹${price.toStringAsFixed(0)} Standee Preset! Tap "Save & Sync" to push to machine.'),
        backgroundColor: const Color(0xFF0284C7),
      ),
    );
  }

  Future<void> _deployOta(String deviceId, String firmwareId) async {
    try {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Deploying OTA to $deviceId...'), backgroundColor: const Color(0xFF0284C7)),
      );
      final ok = await ApiService().deployOtaUpdate(deviceId, firmwareId);
      if (!mounted) return;
      if (ok) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('✓ Queued OTA Update for $deviceId!'), backgroundColor: const Color(0xFF10B981)),
        );
        _loadAllData();
      }
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Deployment failed: $e'), backgroundColor: Colors.red),
      );
    }
  }

  Future<void> _triggerTestDispense(DeviceModel device) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF131B2E),
        title: Text('Test Vend: ${device.deviceId}', style: const TextStyle(color: Colors.white)),
        content: const Text(
          'Send remote test pulse to trigger physical solenoid / vending motor for Slot 1?',
          style: TextStyle(color: Colors.white70),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancel', style: TextStyle(color: Colors.white54)),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF0284C7)),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Confirm Vend'),
          ),
        ],
      ),
    );

    if (ok == true) {
      try {
        final res = await ApiService().triggerDispense(device.deviceId);
        if (!mounted) return;
        final success = res['status'] == 'success' || res['detail'] == null;
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(success ? '✓ Dispense pulse sent to ${device.deviceId}!' : 'Dispense command failed.'),
            backgroundColor: success ? const Color(0xFF10B981) : Colors.red,
          ),
        );
      } catch (e) {
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Test vend error: $e'), backgroundColor: Colors.red),
        );
      }
    }
  }

  void _showAssignDialog(DiscoveryDeviceModel disc) {
    final deviceIdCtrl = TextEditingController(
      text: 'VM-${(_devices.length + 1).toString().padLeft(6, '0')}',
    );
    String? selectedClientId = _clients.isNotEmpty ? _clients.first.id : null;

    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF131B2E),
        title: const Text('Assign Hardware ID', style: TextStyle(color: Colors.white)),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text('Discovered Node: ${disc.tempId}', style: const TextStyle(color: Colors.white70, fontSize: 13)),
            const SizedBox(height: 12),
            TextField(
              controller: deviceIdCtrl,
              style: const TextStyle(color: Colors.white),
              decoration: const InputDecoration(
                labelText: 'Permanent Machine ID',
                labelStyle: TextStyle(color: Colors.white70),
              ),
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<String>(
              initialValue: _clients.any((c) => c.id == selectedClientId) ? selectedClientId : (_clients.isNotEmpty ? _clients.first.id : null),
              dropdownColor: const Color(0xFF131B2E),
              style: const TextStyle(color: Colors.white),
              decoration: const InputDecoration(
                labelText: 'Assign to Tenant Vendor',
                labelStyle: TextStyle(color: Colors.white70),
              ),
              items: _clients.map((c) => DropdownMenuItem(value: c.id, child: Text(c.name))).toList(),
              onChanged: (val) => selectedClientId = val,
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancel', style: TextStyle(color: Colors.white54)),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF0284C7)),
            onPressed: () async {
              Navigator.pop(ctx);
              final ok = await ApiService().claimDiscoveryDevice(
                macAddress: disc.macAddress ?? '',
                targetDeviceId: deviceIdCtrl.text.trim(),
                clientId: selectedClientId,
              );
              if (ok) {
                if (!mounted) return;
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(content: Text('Assigned Machine ${deviceIdCtrl.text}!'), backgroundColor: const Color(0xFF10B981)),
                );
                _loadAllData();
              }
            },
            child: const Text('Assign & Deploy'),
          ),
        ],
      ),
    );
  }

  void _showCreateVendorDialog() {
    final nameCtrl = TextEditingController();
    final codeCtrl = TextEditingController();
    final emailCtrl = TextEditingController();
    final phoneCtrl = TextEditingController();
    final userCtrl = TextEditingController();
    final passCtrl = TextEditingController(text: 'Vendor@2026');
    String? assignDeviceId = _devices.isNotEmpty ? _devices.first.deviceId : null;

    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF131B2E),
        title: const Text('👤 Create Vendor Login', style: TextStyle(color: Colors.white, fontWeight: FontWeight.w700)),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: nameCtrl,
                style: const TextStyle(color: Colors.white),
                decoration: const InputDecoration(
                  labelText: 'Company / Vendor Name',
                  labelStyle: TextStyle(color: Colors.white70),
                  hintText: 'e.g. Airport Vending Terminal',
                  hintStyle: TextStyle(color: Colors.white24, fontSize: 12),
                ),
                onChanged: (val) {
                  if (codeCtrl.text.isEmpty && val.trim().isNotEmpty) {
                    codeCtrl.text = val.trim().replaceAll(RegExp(r'[^a-zA-Z0-9]'), '_').toUpperCase();
                  }
                  if (userCtrl.text.isEmpty && val.trim().isNotEmpty) {
                    userCtrl.text = val.trim().replaceAll(RegExp(r'[^a-zA-Z0-9]'), '_').toLowerCase();
                  }
                },
              ),
              const SizedBox(height: 10),
              TextField(
                controller: codeCtrl,
                style: const TextStyle(color: Colors.white, fontFamily: 'monospace'),
                decoration: const InputDecoration(
                  labelText: 'Vendor Tenant Code',
                  labelStyle: TextStyle(color: Colors.white70),
                  hintText: 'e.g. AIRPORT_VENDORS',
                  hintStyle: TextStyle(color: Colors.white24, fontSize: 12),
                ),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: emailCtrl,
                keyboardType: TextInputType.emailAddress,
                style: const TextStyle(color: Colors.white),
                decoration: const InputDecoration(
                  labelText: 'Contact Email',
                  labelStyle: TextStyle(color: Colors.white70),
                  hintText: 'vendor@example.com',
                  hintStyle: TextStyle(color: Colors.white24, fontSize: 12),
                ),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: phoneCtrl,
                keyboardType: TextInputType.phone,
                style: const TextStyle(color: Colors.white),
                decoration: const InputDecoration(
                  labelText: 'Contact Phone (Optional)',
                  labelStyle: TextStyle(color: Colors.white70),
                ),
              ),
              const SizedBox(height: 14),
              const Divider(color: Colors.white12),
              const SizedBox(height: 6),
              const Align(
                alignment: Alignment.centerLeft,
                child: Text('Vendor Login Credentials', style: TextStyle(color: Color(0xFF38BDF8), fontSize: 12, fontWeight: FontWeight.w700)),
              ),
              const SizedBox(height: 8),
              TextField(
                controller: userCtrl,
                style: const TextStyle(color: Colors.white),
                decoration: const InputDecoration(
                  labelText: 'Login Username',
                  labelStyle: TextStyle(color: Colors.white70),
                ),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: passCtrl,
                style: const TextStyle(color: Colors.white),
                decoration: const InputDecoration(
                  labelText: 'Login Password',
                  labelStyle: TextStyle(color: Colors.white70),
                ),
              ),
              const SizedBox(height: 10),
              DropdownButtonFormField<String>(
                initialValue: (assignDeviceId != null && _devices.any((d) => d.deviceId == assignDeviceId)) ? assignDeviceId : null,
                dropdownColor: const Color(0xFF131B2E),
                style: const TextStyle(color: Colors.white),
                decoration: const InputDecoration(
                  labelText: 'Assign Machine',
                  labelStyle: TextStyle(color: Colors.white70),
                ),
                items: [
                  const DropdownMenuItem(value: null, child: Text('No Machine (Assign Later)')),
                  ..._devices.map((d) => DropdownMenuItem(value: d.deviceId, child: Text(d.deviceId))),
                ],
                onChanged: (val) => assignDeviceId = val,
              ),
            ],
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel', style: TextStyle(color: Colors.white54))),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF6366F1)),
            onPressed: () async {
              if (nameCtrl.text.trim().isEmpty || codeCtrl.text.trim().isEmpty || emailCtrl.text.trim().isEmpty) {
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(content: Text('Please fill in Company Name, Code, and Email'), backgroundColor: Colors.orange),
                );
                return;
              }
              Navigator.pop(ctx);
              try {
                final ok = await ApiService().createClient(
                  clientCode: codeCtrl.text.trim(),
                  name: nameCtrl.text.trim(),
                  contactEmail: emailCtrl.text.trim(),
                  contactPhone: phoneCtrl.text.trim(),
                  adminUsername: userCtrl.text.trim(),
                  adminPassword: passCtrl.text.trim(),
                  assignDeviceId: assignDeviceId,
                );
                if (!mounted) return;
                if (ok) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(
                      content: Text('✓ Created Vendor: ${nameCtrl.text.trim()}! Login: ${userCtrl.text.trim()}'),
                      backgroundColor: const Color(0xFF10B981),
                    ),
                  );
                  _loadAllData();
                }
              } catch (e) {
                if (!mounted) return;
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(content: Text('Create Vendor failed: $e'), backgroundColor: Colors.red),
                );
              }
            },
            child: const Text('Create Vendor Login'),
          ),
        ],
      ),
    );
  }

  void _showResetVendorPasswordDialog(ClientModel client) {
    final userCtrl = TextEditingController(text: '${client.code.toLowerCase()}_admin');
    final passCtrl = TextEditingController(text: 'Vendor@2026');

    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF131B2E),
        title: Text('🔑 Reset Password for ${client.name}', style: const TextStyle(color: Colors.white, fontSize: 15)),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: userCtrl,
              style: const TextStyle(color: Colors.white),
              decoration: const InputDecoration(labelText: 'Username', labelStyle: TextStyle(color: Colors.white70)),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: passCtrl,
              style: const TextStyle(color: Colors.white),
              decoration: const InputDecoration(labelText: 'New Password', labelStyle: TextStyle(color: Colors.white70)),
            ),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel', style: TextStyle(color: Colors.white54))),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF10B981)),
            onPressed: () async {
              Navigator.pop(ctx);
              try {
                final ok = await ApiService().createClientUser(
                  clientId: client.id,
                  username: userCtrl.text.trim(),
                  password: passCtrl.text.trim(),
                  email: client.contactEmail,
                );
                if (!mounted) return;
                if (ok) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(
                      content: Text('✓ Password set for ${userCtrl.text.trim()}!'),
                      backgroundColor: const Color(0xFF10B981),
                    ),
                  );
                }
              } catch (e) {
                if (!mounted) return;
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(content: Text('Failed to set password: $e'), backgroundColor: Colors.red),
                );
              }
            },
            child: const Text('Save Password'),
          ),
        ],
      ),
    );
  }

  void _showRegisterHardwareDialog() {
    final devIdCtrl = TextEditingController(text: 'VM-${(_devices.length + 1).toString().padLeft(6, '0')}');
    final macCtrl = TextEditingController();
    String? selectedClientId = _clients.isNotEmpty ? _clients.first.id : null;

    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF131B2E),
        title: const Text('⚡ Register New Hardware', style: TextStyle(color: Colors.white, fontWeight: FontWeight.w700)),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: devIdCtrl,
              style: const TextStyle(color: Colors.white),
              decoration: const InputDecoration(labelText: 'Permanent Device ID', labelStyle: TextStyle(color: Colors.white70)),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: macCtrl,
              style: const TextStyle(color: Colors.white, fontFamily: 'monospace'),
              decoration: const InputDecoration(
                labelText: 'Hardware MAC Address (Optional)',
                labelStyle: TextStyle(color: Colors.white70),
                hintText: 'e.g. 34:85:18:8f:55:10',
                hintStyle: TextStyle(color: Colors.white24, fontSize: 12),
              ),
            ),
            const SizedBox(height: 10),
            DropdownButtonFormField<String>(
              initialValue: _clients.any((c) => c.id == selectedClientId) ? selectedClientId : (_clients.isNotEmpty ? _clients.first.id : null),
              dropdownColor: const Color(0xFF131B2E),
              style: const TextStyle(color: Colors.white),
              decoration: const InputDecoration(labelText: 'Assign to Tenant Vendor', labelStyle: TextStyle(color: Colors.white70)),
              items: _clients.map((c) => DropdownMenuItem(value: c.id, child: Text(c.name))).toList(),
              onChanged: (val) => selectedClientId = val,
            ),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel', style: TextStyle(color: Colors.white54))),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF0284C7)),
            onPressed: () async {
              Navigator.pop(ctx);
              try {
                final ok = await ApiService().registerDevice(
                  deviceTypeCode: 'VENDING_MACHINE',
                  hardwareId: devIdCtrl.text.trim(),
                  macAddress: macCtrl.text.trim().isNotEmpty ? macCtrl.text.trim() : null,
                  clientId: selectedClientId,
                );
                if (!mounted) return;
                if (ok) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    SnackBar(content: Text('✓ Registered Machine ${devIdCtrl.text.trim()}!'), backgroundColor: const Color(0xFF10B981)),
                  );
                  _loadAllData();
                }
              } catch (e) {
                if (!mounted) return;
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(content: Text('Registration failed: $e'), backgroundColor: Colors.red),
                );
              }
            },
            child: const Text('Register Hardware'),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final user = ApiService().currentUser;

    final totalFleet = _stats['total_devices'] ?? _devices.length;
    final onlineFleet = _stats['online_devices'] ?? _devices.where((d) => d.isOnline).length;
    final offlineFleet = _stats['offline_devices'] ?? (_devices.length - onlineFleet);

    return Scaffold(
      backgroundColor: const Color(0xFF0B0F19),
      appBar: AppBar(
        backgroundColor: const Color(0xFF131B2E),
        elevation: 0,
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Fleet Command Center',
              style: TextStyle(fontSize: 17, fontWeight: FontWeight.w800, color: Colors.white),
            ),
            Text(
              '${user?.username ?? 'Admin'} • Operations SuperAdmin',
              style: const TextStyle(fontSize: 11, color: Color(0xFF38BDF8)),
            ),
          ],
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh, color: Colors.white70),
            onPressed: _isLoading ? null : _loadAllData,
          ),
          IconButton(
            icon: const Icon(Icons.logout, color: Colors.redAccent),
            tooltip: 'Logout',
            onPressed: () async {
              await ApiService().logout();
              if (!mounted) return;
              Navigator.of(context).pushReplacement(
                MaterialPageRoute(builder: (_) => const LoginScreen()),
              );
            },
          ),
        ],
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator(color: Color(0xFF0284C7)))
          : RefreshIndicator(
              onRefresh: _loadAllData,
              color: const Color(0xFF0284C7),
              child: ListView(
                padding: const EdgeInsets.all(16),
                children: [
                  // Stat Cards (Live Fleet Telemetry)
                  Row(
                    children: [
                      _buildStatCard('Total Fleet', '$totalFleet', Icons.dns, const Color(0xFF0284C7)),
                      const SizedBox(width: 8),
                      _buildStatCard('Online', '$onlineFleet', Icons.check_circle_outline, const Color(0xFF10B981)),
                      const SizedBox(width: 8),
                      _buildStatCard('Offline', '$offlineFleet', Icons.highlight_off, Colors.grey),
                      const SizedBox(width: 8),
                      _buildStatCard('Queue', '${_discoveryQueue.length}', Icons.radar, const Color(0xFFF59E0B)),
                    ],
                  ),
                  const SizedBox(height: 18),

                  // Current tab view
                  if (_currentTabIndex == 0) _buildDevicesTab(),
                  if (_currentTabIndex == 1) _buildQrManagerTab(),
                  if (_currentTabIndex == 2) _buildOtaHubTab(),
                  if (_currentTabIndex == 3) _buildDiscoveryTab(),
                  if (_currentTabIndex == 4) _buildClientsTab(),
                ],
              ),
            ),
      bottomNavigationBar: BottomNavigationBar(
        backgroundColor: const Color(0xFF131B2E),
        currentIndex: _currentTabIndex,
        selectedItemColor: const Color(0xFF38BDF8),
        unselectedItemColor: const Color(0xFF94A3B8),
        type: BottomNavigationBarType.fixed,
        selectedFontSize: 11,
        unselectedFontSize: 11,
        onTap: (idx) => setState(() => _currentTabIndex = idx),
        items: [
          const BottomNavigationBarItem(
            icon: Icon(Icons.developer_board),
            label: 'Fleet',
          ),
          const BottomNavigationBarItem(
            icon: Icon(Icons.qr_code_2),
            label: 'QR & UPI',
          ),
          const BottomNavigationBarItem(
            icon: Icon(Icons.system_update_alt),
            label: 'OTA Hub',
          ),
          BottomNavigationBarItem(
            icon: Badge(
              isLabelVisible: _discoveryQueue.isNotEmpty,
              label: Text('${_discoveryQueue.length}'),
              child: const Icon(Icons.radar),
            ),
            label: 'Discovery',
          ),
          const BottomNavigationBarItem(
            icon: Icon(Icons.business),
            label: 'Vendors',
          ),
        ],
      ),
    );
  }

  Widget _buildStatCard(String title, String val, IconData icon, Color color) {
    return Expanded(
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 12),
        decoration: BoxDecoration(
          color: const Color(0xFF131B2E),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: Colors.white.withValues(alpha: 0.06)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, color: color, size: 18),
            const SizedBox(height: 6),
            Text(val, style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.w800)),
            Text(title, style: const TextStyle(color: Color(0xFF94A3B8), fontSize: 10), maxLines: 1, overflow: TextOverflow.ellipsis),
          ],
        ),
      ),
    );
  }

  Widget _buildDevicesTab() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            const Text(
              'Connected Hardware Fleet',
              style: TextStyle(color: Colors.white, fontSize: 15, fontWeight: FontWeight.w700),
            ),
            OutlinedButton.icon(
              style: OutlinedButton.styleFrom(
                foregroundColor: const Color(0xFF38BDF8),
                side: const BorderSide(color: Color(0xFF0284C7)),
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              ),
              onPressed: _showRegisterHardwareDialog,
              icon: const Icon(Icons.add, size: 14),
              label: const Text('Register', style: TextStyle(fontSize: 12)),
            ),
          ],
        ),
        const SizedBox(height: 12),
        if (_devices.isEmpty)
          Container(
            padding: const EdgeInsets.all(30),
            decoration: BoxDecoration(color: const Color(0xFF131B2E), borderRadius: BorderRadius.circular(14)),
            child: const Center(
              child: Text('No devices registered in fleet yet', style: TextStyle(color: Colors.white54)),
            ),
          )
        else
          ListView.separated(
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            itemCount: _devices.length,
            separatorBuilder: (_, __) => const SizedBox(height: 10),
            itemBuilder: (context, idx) {
              final d = _devices[idx];
              return Container(
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: const Color(0xFF131B2E),
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(
                    color: d.isOnline ? const Color(0xFF10B981).withValues(alpha: 0.4) : Colors.white.withValues(alpha: 0.08),
                  ),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Row(
                          children: [
                            Text(
                              d.deviceId,
                              style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 16),
                            ),
                            const SizedBox(width: 8),
                            Container(
                              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                              decoration: BoxDecoration(
                                color: const Color(0xFF1E293B),
                                borderRadius: BorderRadius.circular(4),
                              ),
                              child: Text(
                                'FW ${d.firmwareVersion}',
                                style: const TextStyle(color: Color(0xFF94A3B8), fontSize: 10),
                              ),
                            ),
                          ],
                        ),
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                          decoration: BoxDecoration(
                            color: (d.isOnline ? const Color(0xFF10B981) : Colors.grey).withValues(alpha: 0.15),
                            borderRadius: BorderRadius.circular(6),
                          ),
                          child: Text(
                            d.isOnline ? 'ONLINE' : 'OFFLINE',
                            style: TextStyle(
                              color: d.isOnline ? const Color(0xFF10B981) : Colors.grey,
                              fontSize: 10,
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 6),
                    Text(
                      'Vendor: ${d.clientName ?? 'Unassigned'}  •  Mode: ${d.paymentMode}',
                      style: const TextStyle(color: Color(0xFF94A3B8), fontSize: 12),
                    ),
                    if (d.macAddress != null) ...[
                      const SizedBox(height: 2),
                      Text(
                        'MAC: ${d.macAddress}',
                        style: const TextStyle(color: Color(0xFF64748B), fontSize: 11, fontFamily: 'monospace'),
                      ),
                    ],
                    const SizedBox(height: 8),
                    Row(
                      children: [
                        Text(
                          d.stockManagementEnabled ? 'Stock: ${d.currentStock}/${d.maxStock}' : 'Without-Stock Mode',
                          style: TextStyle(
                            color: d.stockManagementEnabled ? Colors.white70 : const Color(0xFF10B981),
                            fontSize: 12,
                            fontWeight: d.stockManagementEnabled ? FontWeight.normal : FontWeight.w600,
                          ),
                        ),
                        const Spacer(),
                        Text('UPI: ₹${d.upiPrice.toStringAsFixed(0)}', style: const TextStyle(color: Color(0xFF38BDF8), fontSize: 12, fontWeight: FontWeight.w600)),
                        const SizedBox(width: 8),
                        Text('Coin: ₹${d.coinPrice.toStringAsFixed(0)}', style: const TextStyle(color: Color(0xFFF59E0B), fontSize: 12, fontWeight: FontWeight.w600)),
                      ],
                    ),
                    const SizedBox(height: 10),
                    Row(
                      children: [
                        Expanded(
                          child: OutlinedButton.icon(
                            style: OutlinedButton.styleFrom(
                              foregroundColor: const Color(0xFF38BDF8),
                              side: const BorderSide(color: Color(0xFF0284C7)),
                            ),
                            onPressed: () => _triggerTestDispense(d),
                            icon: const Icon(Icons.flash_on, size: 16),
                            label: const Text('Test Vend'),
                          ),
                        ),
                        const SizedBox(width: 8),
                        OutlinedButton.icon(
                          style: OutlinedButton.styleFrom(
                            foregroundColor: const Color(0xFFF59E0B),
                            side: const BorderSide(color: Color(0xFFF59E0B)),
                          ),
                          onPressed: () {
                            setState(() {
                              _selectedQrDeviceId = d.deviceId;
                              _currentTabIndex = 1;
                              _loadDeviceQrConfig(d.deviceId);
                            });
                          },
                          icon: const Icon(Icons.qr_code, size: 16),
                          label: const Text('QR Config'),
                        ),
                      ],
                    ),
                  ],
                ),
              );
            },
          ),
      ],
    );
  }

  Widget _buildQrManagerTab() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'UPI QR Code & Operating Configuration',
          style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.w700),
        ),
        const SizedBox(height: 4),
        const Text(
          'Upload QR standee image, select stock/without-stock mode, and sync live to ESP32.',
          style: TextStyle(color: Color(0xFF94A3B8), fontSize: 12),
        ),
        const SizedBox(height: 14),

        // Device Selector Dropdown
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 4),
          decoration: BoxDecoration(
            color: const Color(0xFF131B2E),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: Colors.white.withValues(alpha: 0.08)),
          ),
          child: DropdownButtonHideUnderline(
            child: DropdownButton<String>(
              isExpanded: true,
              dropdownColor: const Color(0xFF131B2E),
              value: _devices.any((d) => d.deviceId == _selectedQrDeviceId)
                  ? _selectedQrDeviceId
                  : (_devices.isNotEmpty ? _devices.first.deviceId : null),
              items: _devices.map((d) => DropdownMenuItem<String>(
                value: d.deviceId,
                child: Text(
                  '${d.deviceId} (${d.isOnline ? "ONLINE" : "OFFLINE"}) - ${d.clientName ?? "Unassigned"}',
                  style: const TextStyle(color: Colors.white),
                  overflow: TextOverflow.ellipsis,
                ),
              )).toList(),
              onChanged: (id) {
                if (id != null) {
                  setState(() => _selectedQrDeviceId = id);
                  _loadDeviceQrConfig(id);
                }
              },
            ),
          ),
        ),
        const SizedBox(height: 14),

        if (_isLoadingQr)
          const Center(child: Padding(padding: EdgeInsets.all(30), child: CircularProgressIndicator(color: Color(0xFF0284C7))))
        else
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: const Color(0xFF131B2E),
              borderRadius: BorderRadius.circular(16),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                // Active status pill
                if (_currentQrConfig != null)
                  Container(
                    margin: const EdgeInsets.only(bottom: 14),
                    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                    decoration: BoxDecoration(
                      color: const Color(0xFF10B981).withValues(alpha: 0.12),
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: const Color(0xFF10B981).withValues(alpha: 0.3)),
                    ),
                    child: Row(
                      children: [
                        const Icon(Icons.check_circle, color: Color(0xFF10B981), size: 16),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Text(
                            'Active: ${_currentQrConfig!.productName} • ₹${_currentQrConfig!.amountRupees.toStringAsFixed(0)} • ${_stockManagementEnabled ? "Stock Tracking" : "Without-Stock"}',
                            style: const TextStyle(color: Color(0xFF10B981), fontSize: 11, fontWeight: FontWeight.w600),
                          ),
                        ),
                      ],
                    ),
                  ),

                // Upload QR Image Action Bar
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: const Color(0xFF0F172A),
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(color: const Color(0xFF38BDF8).withValues(alpha: 0.2)),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Row(
                        children: [
                          Icon(Icons.qr_code_scanner, color: Color(0xFF38BDF8), size: 18),
                          SizedBox(width: 6),
                          Text('Upload Standee QR Code Photo', style: TextStyle(color: Colors.white, fontSize: 13, fontWeight: FontWeight.w700)),
                        ],
                      ),
                      const SizedBox(height: 4),
                      const Text(
                        'Upload your standee QR code or photo. The app auto-decodes the UPI link.',
                        style: TextStyle(color: Color(0xFF94A3B8), fontSize: 11),
                      ),
                      const SizedBox(height: 10),
                      Row(
                        children: [
                          Expanded(
                            child: ElevatedButton.icon(
                              style: ElevatedButton.styleFrom(
                                backgroundColor: const Color(0xFF0284C7),
                                padding: const EdgeInsets.symmetric(vertical: 8),
                              ),
                              onPressed: _showQrImageSourcePicker,
                              icon: const Icon(Icons.photo_camera, size: 16),
                              label: const Text('📷 Upload QR Image', style: TextStyle(fontSize: 12)),
                            ),
                          ),
                          if (_selectedImageFilename != null) ...[
                            const SizedBox(width: 8),
                            Container(
                              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
                              decoration: BoxDecoration(
                                color: const Color(0xFF10B981).withValues(alpha: 0.2),
                                borderRadius: BorderRadius.circular(6),
                              ),
                              child: Row(
                                children: [
                                  const Icon(Icons.check, color: Color(0xFF10B981), size: 14),
                                  const SizedBox(width: 4),
                                  Text(
                                    _selectedImageFilename!,
                                    style: const TextStyle(color: Color(0xFF10B981), fontSize: 11),
                                  ),
                                ],
                              ),
                            ),
                          ],
                        ],
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 14),

                // 1-Click Standee Quick Presets
                const Text('Quick 1-Click Standee Presets:', style: TextStyle(color: Colors.white70, fontSize: 12, fontWeight: FontWeight.w600)),
                const SizedBox(height: 6),
                Wrap(
                  spacing: 8,
                  runSpacing: 6,
                  children: [
                    ActionChip(
                      backgroundColor: const Color(0xFF1E293B),
                      side: const BorderSide(color: Color(0xFF38BDF8)),
                      avatar: const Text('₹2', style: TextStyle(color: Color(0xFF38BDF8), fontWeight: FontWeight.bold, fontSize: 11)),
                      label: const Text('₹2 Standee QR', style: TextStyle(color: Colors.white, fontSize: 11)),
                      onPressed: () => _applyStandeePreset(2.0, 'TuXKipEEX2KteFqrv2'),
                    ),
                    ActionChip(
                      backgroundColor: const Color(0xFF1E293B),
                      side: const BorderSide(color: Color(0xFF10B981)),
                      avatar: const Text('₹5', style: TextStyle(color: Color(0xFF10B981), fontWeight: FontWeight.bold, fontSize: 11)),
                      label: const Text('₹5 Standee QR', style: TextStyle(color: Colors.white, fontSize: 11)),
                      onPressed: () => _applyStandeePreset(5.0, 'TuXKipEEX2KteFqrv2'),
                    ),
                    ActionChip(
                      backgroundColor: const Color(0xFF1E293B),
                      side: const BorderSide(color: Color(0xFFF59E0B)),
                      avatar: const Text('₹10', style: TextStyle(color: Color(0xFFF59E0B), fontWeight: FontWeight.bold, fontSize: 11)),
                      label: const Text('₹10 Standee QR', style: TextStyle(color: Colors.white, fontSize: 11)),
                      onPressed: () => _applyStandeePreset(10.0, 'TuXKipEEX2KteFqrv2'),
                    ),
                  ],
                ),
                const SizedBox(height: 14),

                // Product Name Field
                TextField(
                  controller: _qrProductCtrl,
                  style: const TextStyle(color: Colors.white),
                  decoration: const InputDecoration(
                    labelText: 'Product / Item Name',
                    labelStyle: TextStyle(color: Colors.white70),
                  ),
                ),
                const SizedBox(height: 12),

                // Amount Field
                TextField(
                  controller: _qrPriceCtrl,
                  keyboardType: TextInputType.number,
                  style: const TextStyle(color: Colors.white),
                  decoration: const InputDecoration(
                    labelText: 'UPI Price (₹)',
                    labelStyle: TextStyle(color: Color(0xFF38BDF8)),
                  ),
                ),
                const SizedBox(height: 12),

                // Standee UPI Link / Custom QR URL
                TextField(
                  controller: _qrUpiLinkCtrl,
                  maxLines: 2,
                  style: const TextStyle(color: Colors.white, fontFamily: 'monospace', fontSize: 11),
                  decoration: const InputDecoration(
                    labelText: 'Standee UPI Link / Razorpay QR Payload',
                    labelStyle: TextStyle(color: Color(0xFFF59E0B)),
                  ),
                ),
                const SizedBox(height: 16),

                // ==========================================
                // STOCK MODE (With Stock vs Without Stock)
                // ==========================================
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: _stockManagementEnabled
                        ? const Color(0xFF10B981).withValues(alpha: 0.08)
                        : const Color(0xFF6366F1).withValues(alpha: 0.08),
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(
                      color: _stockManagementEnabled
                          ? const Color(0xFF10B981).withValues(alpha: 0.3)
                          : const Color(0xFF6366F1).withValues(alpha: 0.3),
                    ),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Row(
                                  children: [
                                    Text(
                                      _stockManagementEnabled ? '📦 Stock-Based Mode' : '⚡ Without-Stock Mode',
                                      style: TextStyle(
                                        color: _stockManagementEnabled ? const Color(0xFF34D399) : const Color(0xFF818CF8),
                                        fontWeight: FontWeight.w700,
                                        fontSize: 13,
                                      ),
                                    ),
                                  ],
                                ),
                                const SizedBox(height: 2),
                                Text(
                                  _stockManagementEnabled
                                      ? 'Track inventory (machine halts when empty)'
                                      : 'Continuous vending (no stock count limit)',
                                  style: const TextStyle(color: Color(0xFF94A3B8), fontSize: 11),
                                ),
                              ],
                            ),
                          ),
                          Switch(
                            value: _stockManagementEnabled,
                            activeColor: const Color(0xFF10B981),
                            inactiveTrackColor: const Color(0xFF6366F1).withValues(alpha: 0.5),
                            onChanged: (val) {
                              setState(() => _stockManagementEnabled = val);
                            },
                          ),
                        ],
                      ),
                      if (_stockManagementEnabled) ...[
                        const SizedBox(height: 10),
                        const Divider(color: Colors.white12),
                        const SizedBox(height: 6),
                        Row(
                          children: [
                            const Text('Stock Units (1 - 50):', style: TextStyle(color: Colors.white70, fontSize: 12)),
                            const SizedBox(width: 12),
                            IconButton(
                              icon: const Icon(Icons.remove_circle_outline, color: Color(0xFF38BDF8), size: 20),
                              onPressed: () {
                                int cur = int.tryParse(_stockQtyCtrl.text) ?? 50;
                                if (cur > 0) {
                                  setState(() => _stockQtyCtrl.text = (cur - 1).toString());
                                }
                              },
                            ),
                            SizedBox(
                              width: 50,
                              child: TextField(
                                controller: _stockQtyCtrl,
                                keyboardType: TextInputType.number,
                                textAlign: TextAlign.center,
                                style: const TextStyle(color: Color(0xFF34D399), fontWeight: FontWeight.bold),
                                decoration: const InputDecoration(isDense: true, contentPadding: EdgeInsets.symmetric(vertical: 4)),
                              ),
                            ),
                            IconButton(
                              icon: const Icon(Icons.add_circle_outline, color: Color(0xFF38BDF8), size: 20),
                              onPressed: () {
                                int cur = int.tryParse(_stockQtyCtrl.text) ?? 50;
                                if (cur < 50) {
                                  setState(() => _stockQtyCtrl.text = (cur + 1).toString());
                                }
                              },
                            ),
                          ],
                        ),
                        const SizedBox(height: 4),
                        const Text(
                          '🔘 Machine Switch 1 (GPIO 32): cycle stock | 💾 Switch 2 (GPIO 33): save to Flash',
                          style: TextStyle(color: Color(0xFF64748B), fontSize: 10),
                        ),
                      ],
                    ],
                  ),
                ),
                const SizedBox(height: 14),

                // ==========================================
                // PAYMENT ACCEPTANCE MODE
                // ==========================================
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: const Color(0xFF0F172A),
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(color: Colors.white.withValues(alpha: 0.08)),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text('💳 Payment Acceptance Mode:', style: TextStyle(color: Colors.white, fontSize: 13, fontWeight: FontWeight.w700)),
                      const SizedBox(height: 8),
                      Row(
                        children: [
                          Expanded(
                            child: ChoiceChip(
                              label: const Text('⚡ Both (QR+Coin)', style: TextStyle(fontSize: 10)),
                              selected: _paymentMode == 'BOTH',
                              selectedColor: const Color(0xFF0284C7),
                              onSelected: (_) => setState(() => _paymentMode = 'BOTH'),
                            ),
                          ),
                          const SizedBox(width: 4),
                          Expanded(
                            child: ChoiceChip(
                              label: const Text('📱 QR Only', style: TextStyle(fontSize: 10)),
                              selected: _paymentMode == 'QR_ONLY',
                              selectedColor: const Color(0xFF0284C7),
                              onSelected: (_) => setState(() => _paymentMode = 'QR_ONLY'),
                            ),
                          ),
                          const SizedBox(width: 4),
                          Expanded(
                            child: ChoiceChip(
                              label: const Text('🪙 Coin Only', style: TextStyle(fontSize: 10)),
                              selected: _paymentMode == 'COIN_ONLY',
                              selectedColor: const Color(0xFF0284C7),
                              onSelected: (_) => setState(() => _paymentMode = 'COIN_ONLY'),
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 14),

                // ==========================================
                // WI-FI CREDENTIALS PUSH TO ESP32
                // ==========================================
                Theme(
                  data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
                  child: ExpansionTile(
                    title: const Text('📶 Machine Wi-Fi Setup (Push to ESP32)', style: TextStyle(color: Colors.white70, fontSize: 12)),
                    children: [
                      TextField(
                        controller: _wifiSsidCtrl,
                        style: const TextStyle(color: Colors.white),
                        decoration: const InputDecoration(labelText: 'Wi-Fi SSID', labelStyle: TextStyle(color: Colors.white70)),
                      ),
                      const SizedBox(height: 8),
                      TextField(
                        controller: _wifiPasswordCtrl,
                        obscureText: true,
                        style: const TextStyle(color: Colors.white),
                        decoration: const InputDecoration(labelText: 'Wi-Fi Password', labelStyle: TextStyle(color: Colors.white70)),
                      ),
                      const SizedBox(height: 8),
                    ],
                  ),
                ),
                const SizedBox(height: 16),

                // Save & Sync Button
                ElevatedButton.icon(
                  style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFF0284C7),
                    padding: const EdgeInsets.symmetric(vertical: 14),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                  ),
                  onPressed: _saveQrConfig,
                  icon: const Icon(Icons.sync),
                  label: const Text('Save & Sync to Machine', style: TextStyle(fontWeight: FontWeight.w700)),
                ),
              ],
            ),
          ),
      ],
    );
  }

  Widget _buildOtaHubTab() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            const Text(
              'Firmware & OTA Hub',
              style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.w700),
            ),
            Text(
              '${_firmwareList.length} artifacts',
              style: const TextStyle(color: Color(0xFF94A3B8), fontSize: 12),
            ),
          ],
        ),
        const SizedBox(height: 4),
        const Text(
          'Push over-the-air binary updates to ESP32 fleet machines with verification.',
          style: TextStyle(color: Color(0xFF94A3B8), fontSize: 12),
        ),
        const SizedBox(height: 14),

        if (_firmwareList.isEmpty)
          Container(
            padding: const EdgeInsets.all(20),
            decoration: BoxDecoration(color: const Color(0xFF131B2E), borderRadius: BorderRadius.circular(14)),
            child: const Center(
              child: Text('No compiled firmware binaries found in library', style: TextStyle(color: Colors.white54)),
            ),
          )
        else
          ListView.separated(
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            itemCount: _firmwareList.length,
            separatorBuilder: (_, __) => const SizedBox(height: 10),
            itemBuilder: (context, idx) {
              final fw = _firmwareList[idx];
              return Container(
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: const Color(0xFF131B2E),
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(color: Colors.white.withValues(alpha: 0.08)),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Text('Firmware ${fw.version}', style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 15)),
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                          decoration: BoxDecoration(color: const Color(0xFF0284C7).withValues(alpha: 0.2), borderRadius: BorderRadius.circular(6)),
                          child: Text(fw.deviceTypeCode, style: const TextStyle(color: Color(0xFF38BDF8), fontSize: 10, fontWeight: FontWeight.w700)),
                        ),
                      ],
                    ),
                    const SizedBox(height: 6),
                    Text('${fw.filename} (${(fw.fileSizeBytes / 1024).toStringAsFixed(1)} KB)', style: const TextStyle(color: Color(0xFF94A3B8), fontSize: 12)),
                    const SizedBox(height: 12),
                    Row(
                      children: [
                        const Text('Target Machine: ', style: TextStyle(color: Colors.white70, fontSize: 12)),
                        const Spacer(),
                        ElevatedButton.icon(
                          style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF10B981)),
                          onPressed: () {
                            if (_devices.isEmpty) return;
                            _showSelectDeviceDeployDialog(fw);
                          },
                          icon: const Icon(Icons.rocket_launch, size: 14),
                          label: const Text('Deploy OTA', style: TextStyle(fontSize: 12)),
                        ),
                      ],
                    ),
                  ],
                ),
              );
            },
          ),

        if (_otaDeployments.isNotEmpty) ...[
          const SizedBox(height: 24),
          const Text(
            'Recent OTA Deployments',
            style: TextStyle(color: Colors.white, fontSize: 14, fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: 8),
          ListView.separated(
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            itemCount: _otaDeployments.length,
            separatorBuilder: (_, __) => const SizedBox(height: 6),
            itemBuilder: (context, idx) {
              final dep = _otaDeployments[idx];
              return Container(
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                decoration: BoxDecoration(
                  color: const Color(0xFF131B2E),
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: Colors.white.withValues(alpha: 0.05)),
                ),
                child: Row(
                  children: [
                    const Icon(Icons.history, color: Color(0xFF38BDF8), size: 16),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        '${dep.deviceId} -> ${dep.targetVersion} [${dep.status}]',
                        style: const TextStyle(color: Colors.white70, fontSize: 12),
                      ),
                    ),
                    Text(
                      '${dep.progressPercent}%',
                      style: const TextStyle(color: Color(0xFF10B981), fontSize: 12, fontWeight: FontWeight.w700),
                    ),
                  ],
                ),
              );
            },
          ),
        ],
      ],
    );
  }

  void _showSelectDeviceDeployDialog(FirmwareModel fw) {
    if (_devices.isEmpty) return;
    String selectedDevId = _devices.first.deviceId;

    showDialog(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDialogState) {
          final effectiveDevId = _devices.any((d) => d.deviceId == selectedDevId)
              ? selectedDevId
              : _devices.first.deviceId;

          return AlertDialog(
            backgroundColor: const Color(0xFF131B2E),
            title: Text('Deploy Firmware ${fw.version}', style: const TextStyle(color: Colors.white)),
            content: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('Select target fleet machine:', style: TextStyle(color: Colors.white70)),
                const SizedBox(height: 10),
                DropdownButton<String>(
                  isExpanded: true,
                  dropdownColor: const Color(0xFF131B2E),
                  value: effectiveDevId,
                  items: _devices.map((d) => DropdownMenuItem<String>(
                    value: d.deviceId,
                    child: Text('${d.deviceId} (${d.firmwareVersion})', style: const TextStyle(color: Colors.white)),
                  )).toList(),
                  onChanged: (id) {
                    if (id != null) setDialogState(() => selectedDevId = id);
                  },
                ),
              ],
            ),
            actions: [
              TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel', style: TextStyle(color: Colors.white54))),
              ElevatedButton(
                style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFF10B981)),
                onPressed: () {
                  Navigator.pop(ctx);
                  _deployOta(effectiveDevId, fw.id);
                },
                child: const Text('Push OTA Now'),
              ),
            ],
          );
        },
      ),
    );
  }

  Widget _buildDiscoveryTab() {
    if (_discoveryQueue.isEmpty) {
      return const Center(
        child: Padding(
          padding: EdgeInsets.all(40),
          child: Column(
            children: [
              Icon(Icons.radar, color: Colors.white24, size: 48),
              SizedBox(height: 12),
              Text('No new hardware waiting in queue', style: TextStyle(color: Colors.white54)),
              SizedBox(height: 4),
              Text('Powered-on ESP32 nodes will appear here instantly', style: TextStyle(color: Colors.white24, fontSize: 12)),
            ],
          ),
        ),
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'Hardware Discovery Queue (Live Broadcasting)',
          style: TextStyle(color: Colors.white, fontSize: 15, fontWeight: FontWeight.w700),
        ),
        const SizedBox(height: 12),
        ListView.separated(
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          itemCount: _discoveryQueue.length,
          separatorBuilder: (_, __) => const SizedBox(height: 10),
          itemBuilder: (context, idx) {
            final disc = _discoveryQueue[idx];
            return Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: const Color(0xFF131B2E),
                borderRadius: BorderRadius.circular(14),
                border: Border.all(color: const Color(0xFFF59E0B).withValues(alpha: 0.4)),
              ),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          disc.tempId,
                          style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 13),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                        const SizedBox(height: 4),
                        Text(
                          'MAC: ${disc.macAddress ?? 'N/A'}',
                          style: const TextStyle(color: Color(0xFF94A3B8), fontSize: 11, fontFamily: 'monospace'),
                        ),
                        if (disc.ipAddress != null)
                          Text(
                            'IP: ${disc.ipAddress}',
                            style: const TextStyle(color: Color(0xFF64748B), fontSize: 10),
                          ),
                      ],
                    ),
                  ),
                  const SizedBox(width: 8),
                  ElevatedButton.icon(
                    style: ElevatedButton.styleFrom(
                      backgroundColor: const Color(0xFF0284C7),
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                    ),
                    onPressed: () => _showAssignDialog(disc),
                    icon: const Icon(Icons.assignment_turned_in, size: 14),
                    label: const Text('Assign ID', style: TextStyle(fontSize: 12)),
                  ),
                ],
              ),
            );
          },
        ),
      ],
    );
  }

  Widget _buildClientsTab() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            const Text('Client Tenant Vendors', style: TextStyle(color: Colors.white, fontSize: 15, fontWeight: FontWeight.w700)),
            ElevatedButton.icon(
              style: ElevatedButton.styleFrom(
                backgroundColor: const Color(0xFF6366F1),
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
              ),
              onPressed: _showCreateVendorDialog,
              icon: const Icon(Icons.person_add, size: 14),
              label: const Text('+ Create Vendor', style: TextStyle(fontSize: 12)),
            ),
          ],
        ),
        const SizedBox(height: 12),
        if (_clients.isEmpty)
          Container(
            padding: const EdgeInsets.all(30),
            decoration: BoxDecoration(color: const Color(0xFF131B2E), borderRadius: BorderRadius.circular(14)),
            child: const Center(
              child: Text('No vendor clients created yet', style: TextStyle(color: Colors.white54)),
            ),
          )
        else
          ListView.separated(
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            itemCount: _clients.length,
            separatorBuilder: (_, __) => const SizedBox(height: 10),
            itemBuilder: (context, idx) {
              final c = _clients[idx];
              return Container(
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: const Color(0xFF131B2E),
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(color: Colors.white.withValues(alpha: 0.08)),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Expanded(
                          child: Text(
                            c.name,
                            style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w700, fontSize: 15),
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                          decoration: BoxDecoration(
                            color: const Color(0xFF6366F1).withValues(alpha: 0.2),
                            borderRadius: BorderRadius.circular(6),
                          ),
                          child: Text(
                            '${c.allocatedDevices} Machines',
                            style: const TextStyle(color: Color(0xFFA5B4FC), fontSize: 11, fontWeight: FontWeight.w700),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 6),
                    Text(
                      'Tenant Code: ${c.code}  •  Email: ${c.contactEmail}',
                      style: const TextStyle(color: Color(0xFF94A3B8), fontSize: 12),
                    ),
                    const SizedBox(height: 10),
                    Row(
                      mainAxisAlignment: MainAxisAlignment.end,
                      children: [
                        OutlinedButton.icon(
                          style: OutlinedButton.styleFrom(
                            foregroundColor: const Color(0xFF38BDF8),
                            side: const BorderSide(color: Color(0xFF0284C7)),
                            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                          ),
                          onPressed: () => _showResetVendorPasswordDialog(c),
                          icon: const Icon(Icons.key, size: 14),
                          label: const Text('Reset Password', style: TextStyle(fontSize: 11)),
                        ),
                      ],
                    ),
                  ],
                ),
              );
            },
          ),
      ],
    );
  }
}
