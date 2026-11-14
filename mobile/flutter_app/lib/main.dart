import 'package:flutter/material.dart';
import 'services/api_service.dart';
import 'screens/login_screen.dart';
import 'screens/operations_screen.dart';
import 'screens/vendor_screen.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await ApiService().init();
  runApp(const GTechIoTFleetApp());
}

class GTechIoTFleetApp extends StatelessWidget {
  const GTechIoTFleetApp({super.key});

  @override
  Widget build(BuildContext context) {
    final api = ApiService();
    Widget initialHome;

    if (api.isAuthenticated && api.currentUser != null) {
      if (api.currentUser!.isManufacturerAdmin) {
        initialHome = const OperationsScreen();
      } else {
        initialHome = const VendorScreen();
      }
    } else {
      initialHome = const LoginScreen();
    }

    return MaterialApp(
      title: 'G-TECH Fleet',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        scaffoldBackgroundColor: const Color(0xFF0B0F19),
        primaryColor: const Color(0xFF0284C7),
        colorScheme: const ColorScheme.dark(
          primary: Color(0xFF0284C7),
          secondary: Color(0xFF10B981),
          surface: Color(0xFF131B2E),
        ),
        appBarTheme: const AppBarTheme(
          backgroundColor: Color(0xFF131B2E),
          elevation: 0,
          titleTextStyle: TextStyle(
            fontSize: 18,
            fontWeight: FontWeight.w700,
            color: Colors.white,
          ),
        ),
        cardTheme: CardThemeData(
          color: const Color(0xFF131B2E),
          elevation: 0,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(14),
            side: BorderSide(color: Colors.white.withValues(alpha: 0.06)),
          ),
        ),
      ),
      home: initialHome,
    );
  }
}
