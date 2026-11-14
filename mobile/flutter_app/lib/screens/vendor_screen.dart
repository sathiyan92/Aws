import 'package:flutter/material.dart';
import '../models/models.dart';
import '../services/api_service.dart';
import 'login_screen.dart';

class VendorScreen extends StatefulWidget {
  const VendorScreen({super.key});

  @override
  State<VendorScreen> createState() => _VendorScreenState();
}

class _VendorScreenState extends State<VendorScreen> {
  bool _isLoading = false;
  List<DeviceModel> _devices = [];

  @override
  void initState() {
    super.initState();
    _loadVendorData();
  }

  Future<void> _loadVendorData() async {
    setState(() => _isLoading = true);
    try {
      final user = ApiService().currentUser;
      final devs = await ApiService().getDevices(clientId: user?.clientId);
      if (!mounted) return;
      setState(() {
        _devices = devs;
      });
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Load error: $e'), backgroundColor: Colors.red),
        );
      }
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  Future<void> _triggerVend(DeviceModel dev) async {
    try {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Testing vend on ${dev.deviceId}...')),
      );
      final res = await ApiService().triggerDispense(dev.deviceId);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(res['message'] ?? 'Dispense pulse sent successfully!'),
          backgroundColor: const Color(0xFF10B981),
        ),
      );
      _loadVendorData();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Vend failed: $e'), backgroundColor: Colors.red),
      );
    }
  }

  void _showEditStockPriceModal(DeviceModel dev) {
    final stockCtrl = TextEditingController(text: '${dev.currentStock}');
    final upiPriceCtrl = TextEditingController(text: dev.upiPrice.toStringAsFixed(0));
    final coinPriceCtrl = TextEditingController(text: dev.coinPrice.toStringAsFixed(0));
    String selectedMode = dev.paymentMode;

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: const Color(0xFF131B2E),
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setModalState) => Padding(
          padding: EdgeInsets.only(
            left: 20,
            right: 20,
            top: 20,
            bottom: MediaQuery.of(ctx).viewInsets.bottom + 20,
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                'Configure ${dev.deviceId}',
                style: const TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.w800),
              ),
              const SizedBox(height: 16),
              TextField(
                controller: stockCtrl,
                keyboardType: TextInputType.number,
                style: const TextStyle(color: Colors.white),
                decoration: InputDecoration(
                  labelText: 'Current Stock (Max: ${dev.maxStock})',
                  labelStyle: const TextStyle(color: Colors.white70),
                  filled: true,
                  fillColor: const Color(0xFF0B0F19),
                  border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
                ),
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: upiPriceCtrl,
                      keyboardType: TextInputType.number,
                      style: const TextStyle(color: Colors.white),
                      decoration: InputDecoration(
                        labelText: 'UPI Price (₹)',
                        labelStyle: const TextStyle(color: Color(0xFF38BDF8)),
                        filled: true,
                        fillColor: const Color(0xFF0B0F19),
                        border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
                      ),
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: TextField(
                      controller: coinPriceCtrl,
                      keyboardType: TextInputType.number,
                      style: const TextStyle(color: Colors.white),
                      decoration: InputDecoration(
                        labelText: 'Coin Price (₹)',
                        labelStyle: const TextStyle(color: Color(0xFFF59E0B)),
                        filled: true,
                        fillColor: const Color(0xFF0B0F19),
                        border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 14),
              DropdownButtonFormField<String>(
                value: ['BOTH', 'QR_ONLY', 'COIN_ONLY'].contains(selectedMode) ? selectedMode : 'BOTH',
                dropdownColor: const Color(0xFF131B2E),
                style: const TextStyle(color: Colors.white),
                decoration: InputDecoration(
                  labelText: 'Payment Mode',
                  labelStyle: const TextStyle(color: Colors.white70),
                  filled: true,
                  fillColor: const Color(0xFF0B0F19),
                  border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
                ),
                items: const [
                  DropdownMenuItem(value: 'BOTH', child: Text('Both UPI QR & Coin Acceptor')),
                  DropdownMenuItem(value: 'QR_ONLY', child: Text('UPI QR Standee Only')),
                  DropdownMenuItem(value: 'COIN_ONLY', child: Text('Coin Acceptor Only')),
                ],
                onChanged: (val) {
                  if (val != null) setModalState(() => selectedMode = val);
                },
              ),
              const SizedBox(height: 18),
              ElevatedButton(
                style: ElevatedButton.styleFrom(
                  backgroundColor: const Color(0xFF0284C7),
                  padding: const EdgeInsets.symmetric(vertical: 14),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                ),
                onPressed: () async {
                  Navigator.pop(ctx);
                  final ok = await ApiService().updateDeviceConfig(
                    dev.deviceId,
                    currentStock: int.tryParse(stockCtrl.text.trim()),
                    upiPrice: double.tryParse(upiPriceCtrl.text.trim()),
                    coinPrice: double.tryParse(coinPriceCtrl.text.trim()),
                    paymentMode: selectedMode,
                  );
                  if (ok) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(content: Text('Updated ${dev.deviceId} settings!'), backgroundColor: const Color(0xFF10B981)),
                    );
                    _loadVendorData();
                  }
                },
                child: const Text('Save Machine Settings', style: TextStyle(fontWeight: FontWeight.w700)),
              ),
            ],
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final user = ApiService().currentUser;

    return Scaffold(
      backgroundColor: const Color(0xFF0B0F19),
      appBar: AppBar(
        backgroundColor: const Color(0xFF131B2E),
        elevation: 0,
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Vendor Vending Portal',
              style: TextStyle(fontSize: 17, fontWeight: FontWeight.w800, color: Colors.white),
            ),
            Text(
              '${user?.username ?? 'Vendor'} • Merchant Partner',
              style: const TextStyle(fontSize: 11, color: Color(0xFF10B981)),
            ),
          ],
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh, color: Colors.white70),
            onPressed: _isLoading ? null : _loadVendorData,
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
          ? const Center(child: CircularProgressIndicator(color: Color(0xFF10B981)))
          : RefreshIndicator(
              onRefresh: _loadVendorData,
              color: const Color(0xFF10B981),
              child: ListView(
                padding: const EdgeInsets.all(16),
                children: [
                  // Greeting & Summary
                  Container(
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(
                      gradient: const LinearGradient(
                        colors: [Color(0xFF064E3B), Color(0xFF065F46)],
                        begin: Alignment.topLeft,
                        end: Alignment.bottomRight,
                      ),
                      borderRadius: BorderRadius.circular(16),
                    ),
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text(
                              'Active Machines',
                              style: TextStyle(color: Colors.white70, fontSize: 12),
                            ),
                            const SizedBox(height: 4),
                            Text(
                              '${_devices.length} Assigned',
                              style: const TextStyle(color: Colors.white, fontSize: 20, fontWeight: FontWeight.w800),
                            ),
                          ],
                        ),
                        Column(
                          crossAxisAlignment: CrossAxisAlignment.end,
                          children: [
                            const Text(
                              'Online Status',
                              style: TextStyle(color: Colors.white70, fontSize: 12),
                            ),
                            const SizedBox(height: 4),
                            Text(
                              '${_devices.where((d) => d.isOnline).length} Active',
                              style: const TextStyle(color: Color(0xFF34D399), fontSize: 20, fontWeight: FontWeight.w800),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 20),

                  const Text(
                    'My Assigned Machines',
                    style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.w700),
                  ),
                  const SizedBox(height: 12),

                  if (_devices.isEmpty)
                    const Center(
                      child: Padding(
                        padding: EdgeInsets.all(40),
                        child: Text('No machines assigned to this vendor yet', style: TextStyle(color: Colors.white54)),
                      ),
                    )
                  else
                    ListView.separated(
                      shrinkWrap: true,
                      physics: const NeverScrollableScrollPhysics(),
                      itemCount: _devices.length,
                      separatorBuilder: (_, __) => const SizedBox(height: 12),
                      itemBuilder: (context, idx) {
                        final d = _devices[idx];
                        final stockPercent = d.maxStock > 0 ? (d.currentStock / d.maxStock).clamp(0.0, 1.0) : 0.0;

                        return Container(
                          padding: const EdgeInsets.all(16),
                          decoration: BoxDecoration(
                            color: const Color(0xFF131B2E),
                            borderRadius: BorderRadius.circular(16),
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
                                  Text(
                                    d.deviceId,
                                    style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.w800),
                                  ),
                                  Container(
                                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                                    decoration: BoxDecoration(
                                      color: (d.isOnline ? const Color(0xFF10B981) : Colors.grey).withOpacity(0.2),
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
                              const SizedBox(height: 12),

                              // Stock bar
                              Row(
                                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                                children: [
                                  Text(
                                    'Stock: ${d.currentStock} / ${d.maxStock} items',
                                    style: const TextStyle(color: Colors.white70, fontSize: 12),
                                  ),
                                  Text(
                                    '${(stockPercent * 100).toInt()}%',
                                    style: TextStyle(
                                      color: stockPercent < 0.2 ? Colors.redAccent : const Color(0xFF38BDF8),
                                      fontWeight: FontWeight.w700,
                                      fontSize: 12,
                                    ),
                                  ),
                                ],
                              ),
                              const SizedBox(height: 6),
                              ClipRRect(
                                borderRadius: BorderRadius.circular(4),
                                child: LinearProgressIndicator(
                                  value: stockPercent,
                                  minHeight: 6,
                                  backgroundColor: const Color(0xFF0B0F19),
                                  valueColor: AlwaysStoppedAnimation(
                                    stockPercent < 0.2 ? Colors.redAccent : const Color(0xFF0284C7),
                                  ),
                                ),
                              ),
                              const SizedBox(height: 12),

                              // Prices
                              Row(
                                children: [
                                  Text('UPI Price: ₹${d.upiPrice.toStringAsFixed(0)}', style: const TextStyle(color: Color(0xFF38BDF8), fontWeight: FontWeight.w600)),
                                  const SizedBox(width: 16),
                                  Text('Coin Price: ₹${d.coinPrice.toStringAsFixed(0)}', style: const TextStyle(color: Color(0xFFF59E0B), fontWeight: FontWeight.w600)),
                                ],
                              ),
                              const SizedBox(height: 14),

                              // Action buttons
                              Row(
                                children: [
                                  Expanded(
                                    child: ElevatedButton.icon(
                                      style: ElevatedButton.styleFrom(
                                        backgroundColor: const Color(0xFF10B981),
                                        foregroundColor: Colors.white,
                                      ),
                                      onPressed: () => _triggerVend(d),
                                      icon: const Icon(Icons.touch_app, size: 16),
                                      label: const Text('Test Vend'),
                                    ),
                                  ),
                                  const SizedBox(width: 8),
                                  Expanded(
                                    child: OutlinedButton.icon(
                                      style: OutlinedButton.styleFrom(
                                        foregroundColor: Colors.white70,
                                        side: BorderSide(color: Colors.white.withOpacity(0.2)),
                                      ),
                                      onPressed: () => _showEditStockPriceModal(d),
                                      icon: const Icon(Icons.edit, size: 16),
                                      label: const Text('Edit Stock/Price'),
                                    ),
                                  ),
                                ],
                              ),
                            ],
                          ),
                        );
                      },
                    ),
                ],
              ),
            ),
    );
  }
}

