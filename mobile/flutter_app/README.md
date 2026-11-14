# G-TECH IoT Fleet - Dedicated Flutter Native App (Android & iOS)

A pure native cross-platform mobile application built with **Flutter 3.38 & Dart 3.10** for managing G-TECH commercial IoT vending machine fleets.

---

## 🚀 Features

### 1. Operations Mode (SuperAdmin / Manufacturer)
- **Fleet Command Center:** Real-time metrics (Total Fleet, Online Nodes, Unpaired Machines, Active Modules).
- **Connected Hardware Fleet:** Live machine list with online/offline status, stock levels, UPI/Coin pricing, and IP telemetry.
- **Hardware Discovery Queue:** Auto-detects newly powered ESP32 nodes broadcasting online and enables **1-tap Machine ID assignment** (e.g. `VM-000001`) and tenant pairing.
- **Client Tenants Directory:** View vendors and their allocated machine counts.
- **Instant Test Vend:** Trigger dispense pulses directly from the app over REST API / MQTT.

### 2. Vendor / Merchant Mode (Client Admin)
- **Assigned Machines:** Card view of all vending machines assigned to the vendor.
- **Live Stock Progress:** Color-coded inventory progress bars with low-stock alerts.
- **Price & Mode Editor:** Adjust UPI Standee Price (₹), Coin Price (₹), and Payment Mode (`BOTH`, `QR_ONLY`, `COIN_ONLY`) directly from mobile.
- **Test Dispense:** Trigger a 1-unit test vend to confirm motor/solenoid operation.

### 3. Dynamic Server Configuration
- Connects to AWS Lightsail by default: `http://35.154.219.82:8000/api/v1`.
- Built-in **Server Settings** screen with live connection ping test to switch between cloud, staging, or local development environments at any time.

---

## 🛠️ How to Run & Build

### Running with Flutter CLI:

```bash
cd mobile/flutter_app

# Run on connected Android phone or emulator:
flutter run

# Run in release mode:
flutter run --release
```

### Building Standalone Android APK:

```bash
cd mobile/flutter_app

# Build optimized release APK:
flutter build apk --release
```
The compiled APK will be generated at:
```
mobile/flutter_app/build/app/outputs/flutter-apk/app-release.apk
```

### Opening in Android Studio:

1. Open **Android Studio**.
2. Select **File ➡️ Open...** and choose:
   ```
   C:\Projects\iot-fleet-platform\mobile\flutter_app\android
   ```
3. Android Studio will automatically sync the Gradle build and allow running/debugging with the green **Run (▶)** button!

### Building for iOS (Mac / Xcode):

```bash
cd mobile/flutter_app

# Install iOS pods:
cd ios && pod install && cd ..

# Build iOS release bundle:
flutter build ipa --release
```
Or open `mobile/flutter_app/ios/Runner.xcworkspace` in **Xcode** and click **Product ➡️ Archive** to distribute to TestFlight or the App Store.

---

## 📁 Architecture Overview

```
mobile/flutter_app/
├── lib/
│   ├── main.dart                      # Entry point, dark modern theme & role routing
│   ├── config/
│   │   └── api_config.dart            # REST API endpoints & SharedPreferences keys
│   ├── models/
│   │   └── models.dart                # UserModel, DeviceModel, DiscoveryDeviceModel, ClientModel
│   ├── services/
│   │   └── api_service.dart           # HTTP client with Bearer JWT auth & error handling
│   └── screens/
│       ├── login_screen.dart          # Secure login & server settings shortcut
│       ├── operations_screen.dart     # Operations Fleet Command Center & Discovery
│       ├── vendor_screen.dart         # Merchant dashboard, live stock & pricing
│       └── settings_screen.dart       # Live server IP endpoint configuration & ping test
├── android/                           # Native Android project (cleartext HTTP enabled)
├── ios/                               # Native iOS project
└── assets/                            # High-res G-TECH icons & logos
```
