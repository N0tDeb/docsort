import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Minimal session-storage boundary used by authentication and request signing.
///
/// Keeping the platform-backed secure-storage implementation behind this
/// interface makes critical authentication workflows deterministic in tests
/// without changing the production storage mechanism.
abstract class SessionStore {
  Future<String?> read(String key);
  Future<void> write(String key, String value);
  Future<void> delete(String key);
}

class SecureSessionStore implements SessionStore {
  final FlutterSecureStorage storage;

  const SecureSessionStore({
    this.storage = const FlutterSecureStorage(),
  });

  @override
  Future<String?> read(String key) => storage.read(key: key);

  @override
  Future<void> write(String key, String value) =>
      storage.write(key: key, value: value);

  @override
  Future<void> delete(String key) => storage.delete(key: key);
}

final sessionStoreProvider = Provider<SessionStore>((ref) {
  return const SecureSessionStore();
});
