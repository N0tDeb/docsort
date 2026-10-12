class AppConstants {
  static const String appName = 'DocSort';

  // D4: API base URL is supplied through build configuration.
  // Override at build/run time, e.g.:
  //   flutter run --dart-define=API_BASE_URL=http://192.168.1.5:8000
  // Default keeps the ADB USB port-forwarding setup (phone forwards
  // 127.0.0.1 over the USB cable to the laptop, so no Wi-Fi IP needed).
  static const String apiBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://127.0.0.1:8000',
  );
}
