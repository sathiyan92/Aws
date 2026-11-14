class ApiConfig {
  static const String defaultBaseUrl = 'http://35.154.219.82:8000/api/v1';
  static const String prefsServerKey = 'iot_fleet_server_url';
  static const String prefsTokenKey = 'iot_fleet_auth_token';
  static const String prefsUserKey = 'iot_fleet_auth_user';

  // Auth endpoints
  static const String login = '/auth/login';
  static const String me = '/auth/me';

  // Fleet & Platform Stats endpoints
  static const String platformStats = '/manufacturer/platform-stats';
  static const String devices = '/devices';
  static const String clients = '/clients';
  static const String discoveryQueue = '/devices/discovery-queue';
  static const String discoveryClaim = '/devices/discovery-queue/claim';

  // Dynamic QR & Price Manager endpoints
  static String qrConfig(String deviceId) => '/orders/qr-config/$deviceId';
  static const String decodeQr = '/vending/decode-qr';

  // Client & Vendor Management
  static const String createClient = '/clients';
  static String clientUsers(String clientId) => '/clients/$clientId/users';

  // Device Provisioning
  static const String registerDevice = '/devices';

  // OTA Firmware & Deployment endpoints
  static const String firmwareList = '/ota/firmware';
  static const String firmwareUpload = '/ota/firmware/upload';
  static const String otaDeploy = '/ota/deploy';
  static const String otaDeployments = '/ota/deployments';

  // Test Dispense
  static String deviceDispense(String deviceId) => '/devices/$deviceId/dispense';
  static String deviceConfig(String deviceId) => '/devices/$deviceId/config';
}
