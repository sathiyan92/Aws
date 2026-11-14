import 'package:flutter/material.dart';
import 'services/api_service.dart';
import 'screens/login_screen.dart';
import 'screens/operations_screen.dart';
import 'screens/vendor_screen.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await ApiService().init();
  final hasValidSession = await ApiService().validateSession();
  runApp(GTechIoTFleetApp(hasValidSession: hasValidSession));
}

class GTechIoTFleetApp extends StatelessWidget {
  final bool hasValidSession;
  const GTechIoTFleetApp({super.key, this.hasValidSession = false});

  @override
  Widget build(BuildContext context) {
    final api = ApiService();
    Widget initialHome;

    if (hasValidSession && api.currentUser != null) {
      if (api.currentUser!.isManufacturerAdmin) {
        initialHome = const OperationsScreen();
      } else {
        initialHome = const VendorScreen();
      }
    } else {
      initialHome = LoginScreen(sessionExpired: api.token != null);
    }

    return MaterialApp(
      navigatorKey: ApiService.navigatorKey,
      title: 'G-TECH Fleet',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        scaffoldBackgroundColor: const Color(0xFF0B0F19),
        primaryColor: const Color(0xFF0284C7),
        colorScheme: const ColorScheme.dark(
          primary: Color(0xFF0284C7),
          onPrimary: Colors.white,
          secondary: Color(0xFF10B981),
          onSecondary: Colors.white,
          surface: Color(0xFF131B2E),
          onSurface: Colors.white,
        ),
        elevatedButtonTheme: ElevatedButtonThemeData(
          style: ElevatedButton.styleFrom(
            foregroundColor: Colors.white,
            textStyle: const TextStyle(fontWeight: FontWeight.w700),
          ),
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
