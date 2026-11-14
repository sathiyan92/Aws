import 'package:flutter/material.dart';
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

  // QR Manager Tab state
  DeviceModel? _selectedQrDevice;
  QrConfigModel? _currentQrConfig;
  bool _isLoadingQr = false;
  final _qrUpiLinkCtrl = TextEditingController();
  final _qrPriceCtrl = TextEditingController();
  final _qrProductCtrl = TextEditingController();

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

        if (_devices.isNotEmpty && _selectedQrDevice == null) {
          _selectedQrDevice = _devices.firstWhere(
            (d) => d.deviceId == 'VM-000001',
            orElse: () => _devices.first,
          );
          _loadDeviceQrConfig(_selectedQrDevice!.deviceId);
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
      });
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Failed to load QR: $e'), backgroundColor: Colors.red),
        );
      }
    } finally {
      if (mounted) setState(() => _isLoadingQr = false);
    }
  }

  Future<void> _saveQrConfig() async {
    if (_selectedQrDevice == null) return;
    final price = double.tryParse(_qrPriceCtrl.text.trim()) ?? 5.0;
    final link = _qrUpiLinkCtrl.text.trim();
    final prod = _qrProductCtrl.text.trim();

    try {
      final ok = await ApiService().updateQrConfig(
        _selectedQrDevice!.deviceId,
        price: price,
        standeeUpiLink: link,
        productName: prod,
      );
      if (!mounted) return;
      if (ok) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('✓ Synchronized QR settings to ${_selectedQrDevice!.deviceId}!'),
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

  Future<void> _deployOta(String deviceId, String firmwareId) async {
    try {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Deploying OTA to $deviceId...')),
      );
      final ok = await ApiService().deployOtaUpdate(deviceId, firmwareId);
      if (!mounted) return;
      if (ok) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('✓ OTA command queued for $deviceId!'), backgroundColor: const Color(0xFF10B981)),
        );
        _loadAllData();
      }
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('OTA deploy failed: $e'), backgroundColor: Colors.red),
      );
    }
  }

  Future<void> _triggerTestDispense(DeviceModel device) async {
    try {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Testing vend pulse on ${device.deviceId}...')),
      );
      final res = await ApiService().triggerDispense(device.deviceId);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(res['message'] ?? 'Dispense command executed!'),
          backgroundColor: const Color(0xFF10B981),
        ),
      );
      _loadAllData();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Dispense failed: $e'), backgroundColor: Colors.red),
      );
    }
  }

  void _showAssignDialog(DiscoveryDeviceModel disc) {
    final cleanMac = disc.macAddress ?? '';
    final deviceIdCtrl = TextEditingController(text: 'VM-${cleanMac.replaceAll(":", "").substring(cleanMac.length > 6 ? cleanMac.length - 6 : 0)}');
    String? selectedClientId = _clients.isNotEmpty ? _clients.first.id : null;

    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF131B2E),
        title: const Text('Assign Machine ID', style: TextStyle(color: Colors.white)),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Discovered MAC: ${disc.macAddress}', style: const TextStyle(color: Color(0xFF38BDF8), fontSize: 13)),
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
              value: selectedClientId,
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
        onTap: (index) => setState(() => _currentTabIndex = index),
        items: [
          const BottomNavigationBarItem(icon: Icon(Icons.apps), label: 'Fleet'),
          const BottomNavigationBarItem(icon: Icon(Icons.qr_code_2), label: 'QR & UPI'),
          const BottomNavigationBarItem(icon: Icon(Icons.system_update_alt), label: 'OTA Hub'),
          BottomNavigationBarItem(
            icon: Badge(
              isLabelVisible: _discoveryQueue.isNotEmpty,
              label: Text('${_discoveryQueue.length}'),
              child: const Icon(Icons.cell_tower),
            ),
            label: 'Discovery',
          ),
          const BottomNavigationBarItem(icon: Icon(Icons.people_outline), label: 'Vendors'),
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
          border: Border.all(color: Colors.white.withOpacity(0.06)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, color: color, size: 18),
            const SizedBox(height: 6),
            Text(val, style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.w800)),
            Text(title, style: const TextStyle(color: Color(0xFF94A3B8), fontSize: 10)),
          ],
        ),
      ),
    );
  }

  Widget _buildDevicesTab() {
    if (_devices.isEmpty) {
      return const Center(
        child: Padding(
          padding: EdgeInsets.all(40),
          child: Column(
            children: [
              Icon(Icons.inventory_2_outlined, color: Colors.white24, size: 48),
              SizedBox(height: 12),
              Text('No devices registered in fleet yet', style: TextStyle(color: Colors.white54)),
            ],
          ),
        ),
      );
    }
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
            Text(
              '${_devices.length} machines',
              style: const TextStyle(color: Color(0xFF94A3B8), fontSize: 12),
            ),
          ],
        ),
        const SizedBox(height: 12),
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
                  color: d.isOnline ? const Color(0xFF10B981).withOpacity(0.4) : Colors.white.withOpacity(0.08),
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
                              'FW v${d.firmwareVersion}',
                              style: const TextStyle(color: Color(0xFF94A3B8), fontSize: 10),
                            ),
                          ),
                        ],
                      ),
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                        decoration: BoxDecoration(
                          color: (d.isOnline ? const Color(0xFF10B981) : Colors.grey).withOpacity(0.15),
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
                      Text('Stock: ${d.currentStock}/${d.maxStock}', style: const TextStyle(color: Colors.white70, fontSize: 12)),
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
                            _selectedQrDevice = d;
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
          'UPI QR Code & Price Manager',
          style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.w700),
        ),
        const SizedBox(height: 4),
        const Text(
          'Changes made here are pushed live to the machine and standee QR in real-time.',
          style: TextStyle(color: Color(0xFF94A3B8), fontSize: 12),
        ),
        const SizedBox(height: 14),

        // Device Selector Dropdown
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 4),
          decoration: BoxDecoration(
            color: const Color(0xFF131B2E),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: Colors.white.withOpacity(0.08)),
          ),
          child: DropdownButtonHideUnderline(
            child: DropdownButton<DeviceModel>(
              isExpanded: true,
              dropdownColor: const Color(0xFF131B2E),
              value: _selectedQrDevice,
              items: _devices.map((d) => DropdownMenuItem(
                value: d,
                child: Text('${d.deviceId} (${d.isOnline ? "ONLINE" : "OFFLINE"}) - ${d.clientName ?? "Unassigned"}', style: const TextStyle(color: Colors.white)),
              )).toList(),
              onChanged: (d) {
                if (d != null) {
                  setState(() => _selectedQrDevice = d);
                  _loadDeviceQrConfig(d.deviceId);
                }
              },
            ),
          ),
        ),
        const SizedBox(height: 16),

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
                if (_currentQrConfig != null)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: Container(
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                      decoration: BoxDecoration(
                        color: const Color(0xFF10B981).withValues(alpha: 0.15),
                        borderRadius: BorderRadius.circular(6),
                      ),
                      child: Text(
                        'Active Config: ${_currentQrConfig!.productName} (₹${_currentQrConfig!.amountRupees.toStringAsFixed(0)})',
                        style: const TextStyle(color: Color(0xFF10B981), fontSize: 11, fontWeight: FontWeight.w600),
                      ),
                    ),
                  ),

                // Product Name
                TextField(
                  controller: _qrProductCtrl,
                  style: const TextStyle(color: Colors.white),
                  decoration: const InputDecoration(
                    labelText: 'Product Name',
                    labelStyle: TextStyle(color: Colors.white70),
                  ),
                ),
                const SizedBox(height: 12),

                // Amount
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
                  style: const TextStyle(color: Colors.white, fontFamily: 'monospace', fontSize: 12),
                  decoration: const InputDecoration(
                    labelText: 'Standee UPI Link / Razorpay QR Payload',
                    labelStyle: TextStyle(color: Color(0xFFF59E0B)),
                  ),
                ),
                const SizedBox(height: 18),

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
        const Text(
          'Firmware Artifacts & OTA Distribution Hub',
          style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.w700),
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
                  border: Border.all(color: Colors.white.withOpacity(0.08)),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Text('Firmware v${fw.version}', style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 15)),
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                          decoration: BoxDecoration(color: const Color(0xFF0284C7).withOpacity(0.2), borderRadius: BorderRadius.circular(6)),
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
                        '${dep.deviceId} -> v${dep.targetVersion} [${dep.status}]',
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
    DeviceModel selectedDev = _devices.first;

    showDialog(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDialogState) => AlertDialog(
          backgroundColor: const Color(0xFF131B2E),
          title: Text('Deploy Firmware v${fw.version}', style: const TextStyle(color: Colors.white)),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('Select target fleet machine:', style: TextStyle(color: Colors.white70)),
              const SizedBox(height: 10),
              DropdownButton<DeviceModel>(
                isExpanded: true,
                dropdownColor: const Color(0xFF131B2E),
                value: selectedDev,
                items: _devices.map((d) => DropdownMenuItem(value: d, child: Text('${d.deviceId} (v${d.firmwareVersion})', style: const TextStyle(color: Colors.white)))).toList(),
                onChanged: (d) {
                  if (d != null) setDialogState(() => selectedDev = d);
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
                _deployOta(selectedDev.deviceId, fw.id);
              },
              child: const Text('Push OTA Now'),
            ),
          ],
        ),
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
                border: Border.all(color: const Color(0xFFF59E0B).withOpacity(0.4)),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text(disc.tempId, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w800, fontSize: 14)),
                      ElevatedButton.icon(
                        style: ElevatedButton.styleFrom(
                          backgroundColor: const Color(0xFF0284C7),
                          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                        ),
                        onPressed: () => _showAssignDialog(disc),
                        icon: const Icon(Icons.assignment_turned_in, size: 14),
                        label: const Text('Assign ID', style: TextStyle(fontSize: 12)),
                      ),
                    ],
                  ),
                  const SizedBox(height: 4),
                  Text('MAC: ${disc.macAddress ?? 'N/A'}  •  IP: ${disc.ipAddress ?? 'N/A'}', style: const TextStyle(color: Color(0xFF94A3B8), fontSize: 11)),
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
        const Text('Client Tenant Vendors', style: TextStyle(color: Colors.white, fontSize: 15, fontWeight: FontWeight.w700)),
        const SizedBox(height: 12),
        ListView.separated(
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          itemCount: _clients.length,
          separatorBuilder: (_, __) => const SizedBox(height: 8),
          itemBuilder: (context, idx) {
            final c = _clients[idx];
            return Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: const Color(0xFF131B2E),
                borderRadius: BorderRadius.circular(12),
              ),
              child: ListTile(
                title: Text(c.name, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w700)),
                subtitle: Text('Code: ${c.code}  •  ${c.allocatedDevices} Machines', style: const TextStyle(color: Color(0xFF94A3B8), fontSize: 12)),
                trailing: const Icon(Icons.arrow_forward_ios, color: Colors.white24, size: 14),
              ),
            );
          },
        ),
      ],
    );
  }
}
