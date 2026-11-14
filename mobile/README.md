# G-TECH IoT Fleet - Mobile Applications (Android & iOS)

This folder contains the complete mobile solutions for managing G-TECH IoT Vending Fleet platforms on mobile devices.

---

## 📱 Architecture Overview

1. **Native Android App (`mobile/android/`)**:
   - Ready-to-build Android Studio project with zero external CLI dependencies.
   - Features WebView hardware acceleration, dark theme, Swipe-to-Refresh, camera QR scanning permissions, file uploads (standee photos, firmware), and cleartext network security for AWS IP `35.154.219.82`.
2. **Instant iOS PWA & Capacitor Config (`capacitor.config.json` / `mobile/IOS_SETUP_GUIDE.md`)**:
   - 1-tap installation on iPhone/iPad via Safari "Add to Home Screen".
   - Ready for native Xcode compilation via Capacitor for App Store distribution.
3. **Unified Mobile Launcher (`frontend/mobile/index.html`)**:
   - Mobile-first dashboard for quick switching between Operations Portal and Vendor / Client Portal with live server health indicator and editable endpoint configuration.

---

## 🚀 How to Build & Run on Android

### Option A: Open Directly in Android Studio (Recommended)

Android Studio is already installed on your PC at:
`C:\Program Files\Android\Android Studio`

1. Open **Android Studio**.
2. Click **File -> Open...** (or "Open Project" on welcome screen).
3. Navigate to:
   ```
   C:\Projects\iot-fleet-platform\mobile\android
   ```
4. Click **OK**. Android Studio will automatically index the project and sync Gradle dependencies.
5. Connect your Android phone via USB (with **USB Debugging** enabled in Developer Options) or start an Android Emulator.
6. Click the green **Run (▶)** button in Android Studio. The app will install and open immediately on your phone!

### Option B: Build APK from Android Studio Menu

1. In Android Studio, go to **Build -> Build Bundle(s) / APK(s) -> Build APK(s)**.
2. Android Studio will compile `app-debug.apk`.
3. Click the notification link **locate** to open the folder with the APK file.
4. Transfer the `.apk` file to any Android phone via WhatsApp, USB, or Google Drive, and tap to install!

### Option C: Install via ADB command line

You already have `adb` installed at `C:\platform-tools-latest-windows\platform-tools\adb.exe`.
Once built, you can run:
```powershell
adb install -r mobile\android\app\build\outputs\apk\debug\app-debug.apk
```

---

## 🍏 How to Run on iOS (iPhone / iPad)

See the detailed guide in [IOS_SETUP_GUIDE.md](IOS_SETUP_GUIDE.md).

**Quick Method (Immediate):**
1. Open **Safari** on your iPhone.
2. Visit `http://35.154.219.82:8000/mobile/index.html` (or `http://35.154.219.82:8000/portal/`).
3. Tap the **Share** button ➡️ Tap **"Add to Home Screen"** ➡️ Tap **Add**.
4. The G-TECH app icon will appear on your phone screen as a standalone full-screen app.

---

## 🌐 Dynamic Backend Server Settings

The mobile launcher allows changing the backend server endpoint at any time directly in the app UI:
- Open G-TECH Fleet app
- Tap **⚙️ Cloud Server Connection**
- Enter your new domain or IP (e.g., `https://gtechinfo.in` or `http://35.154.219.82:8000`)
- Tap **Save**
- The app will instantly point all Operations and Vendor requests to the new server.
