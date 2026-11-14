# G-TECH IoT Fleet - iOS Setup & Deployment Guide

This document explains how to run the G-TECH IoT Fleet Platform on Apple iOS devices (iPhone & iPad).

---

## Method 1: Instant Home Screen App (PWA - Recommended for Immediate Field Deployment)

iOS Safari natively supports Progressive Web Apps (PWAs). This provides a full-screen, native application experience without requiring Xcode, a Mac, or an Apple Developer Account.

### Step-by-Step Instructions for iPhone / iPad Users:

1. **Open Safari** on your iPhone or iPad.
2. Navigate to your server's mobile portal URL:
   - Default AWS Server: `http://35.154.219.82:8000/mobile/index.html`
   - Or direct portals:
     - Operations Portal: `http://35.154.219.82:8000/portal/`
     - Vendor Portal: `http://35.154.219.82:8000/client-portal/`
3. Tap the **Share Button** (the square icon with an upward-pointing arrow at the bottom of Safari).
4. Scroll down in the share sheet and tap **"Add to Home Screen"** (`[+]`).
5. Change or keep the title as **"G-TECH Fleet"** and tap **Add** in the top-right corner.
6. The G-TECH icon will appear directly on your iOS home screen!

### What You Get:
- **Standalone App Experience:** Opens without Safari's browser URL bar or bottom navigation tabs (`viewport-fit=cover`, `black-translucent` status bar).
- **Fast Performance:** Loads instantly using cached assets.
- **Dynamic Server Switching:** Configure or switch server IPs in the app settings anytime.

---

## Method 2: Native iOS App via Xcode & Capacitor (For App Store & TestFlight)

If you require a native `.ipa` file distributed through Apple TestFlight or the App Store:

### Prerequisites:
- A macOS machine with **Xcode 15+** installed.
- **Node.js** (v18+) and **npm** installed on Mac.
- Apple Developer Account (if publishing to TestFlight/App Store).

### Steps to Build on Mac:

1. **Clone the repository on your Mac:**
   ```bash
   git clone https://github.com/sathiyan92/Aws.git
   cd Aws
   ```

2. **Install Capacitor CLI and iOS platform dependencies:**
   ```bash
   npm install -g @capacitor/cli
   npm install @capacitor/core @capacitor/ios
   ```

3. **Initialize the iOS Native Project:**
   ```bash
   npx cap add ios
   ```
   *(This uses the pre-configured `capacitor.config.json` already present in the repository).*

4. **Sync Web Assets & Config:**
   ```bash
   npx cap sync ios
   ```

5. **Open Project in Xcode:**
   ```bash
   npx cap open ios
   ```

6. **Configure Permissions in `Info.plist`:**
   Ensure the following entries are set in Xcode target settings:
   - `NSCameraUsageDescription`: *"Camera access is required for scanning machine QR codes."*
   - `NSAppTransportSecurity` -> `NSAllowsArbitraryLoads`: `YES` (required for HTTP communication with AWS Lightsail IP `35.154.219.82`).

7. **Run on iOS Device or Simulator:**
   - Connect your iPhone via USB, select your phone in Xcode's device dropdown, and click the **Run (Play)** button.
   - For TestFlight: Select **Product -> Archive** and distribute through App Store Connect.

