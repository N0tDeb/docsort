import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:dio/dio.dart';
import '../../../../core/network/dio_client.dart';
import 'package:jwt_decoder/jwt_decoder.dart';
import '../../../../core/network/session_store.dart';

final authProvider = NotifierProvider<AuthNotifier, AuthState>(
  AuthNotifier.new,
);

/// Exposes the stored user id (set after successful login)
final userIdProvider = FutureProvider<String?>((ref) {
  return ref.read(sessionStoreProvider).read('auth_user_id');
});

enum AuthStatus { restoring, initial, loading, authenticated, error }

String _authErrorMessage(dynamic data, String fallback) {
  if (data is! Map) return fallback;

  final detail = data['detail'];

  if (detail is String && detail.trim().isNotEmpty) {
    return detail;
  }

  if (detail is List) {
    final messages = detail
        .map((item) {
          if (item is Map) {
            final message = item['msg'];
            if (message is String && message.trim().isNotEmpty) {
              return message;
            }
          }
          return null;
        })
        .whereType<String>()
        .toList();

    if (messages.isNotEmpty) {
      return messages.join(' ');
    }
  }

  return fallback;
}

class AuthState {
  final AuthStatus status;
  final String? errorMessage;
  final String role; // 'user' or 'admin'

  AuthState({required this.status, this.errorMessage, this.role = 'user'});

  factory AuthState.restoring() => AuthState(status: AuthStatus.restoring);
  factory AuthState.initial() => AuthState(status: AuthStatus.initial);
  factory AuthState.loading() => AuthState(status: AuthStatus.loading);
  factory AuthState.authenticated(String role) =>
      AuthState(status: AuthStatus.authenticated, role: role);
  factory AuthState.error(String msg) =>
      AuthState(status: AuthStatus.error, errorMessage: msg);

  bool get isAdmin => role == 'admin';
}

class AuthNotifier extends Notifier<AuthState> {
  SessionStore get _storage => ref.read(sessionStoreProvider);

  @override
  AuthState build() {
    _init();
    return AuthState.restoring();
  }

  Future<void> _init() async {
    final token = await _storage.read('auth_token');
    if (token == null) {
      state = AuthState.initial();
      return;
    }

    try {
      if (JwtDecoder.isExpired(token)) {
        await _clearStoredSession();
        state = AuthState.initial();
        return;
      }
    } catch (_) {
      // Corrupt or non-JWT secure-storage data is not a valid session.
      await _clearStoredSession();
      state = AuthState.initial();
      return;
    }

    try {
      final dio = ref.read(dioProvider);
      final response = await dio.get('/auth/me');
      final liveRole = response.data['role']?.toString() ?? 'user';
      await _storage.write('auth_role', liveRole);
      final liveUserId = response.data['id']?.toString();
      if (liveUserId != null) {
        await _storage.write('auth_user_id', liveUserId);
      }
      state = AuthState.authenticated(liveRole);
    } on DioException catch (e) {
      if (e.response?.statusCode == 401 || e.response?.statusCode == 403) {
        await _clearStoredSession();
        state = AuthState.initial();
      } else {
        state = AuthState.error(
          'Could not validate the saved session. Check the backend connection.',
        );
      }
    } catch (_) {
      state = AuthState.error('Could not validate the saved session.');
    }
  }

  Future<void> _clearStoredSession() async {
    await _storage.delete('auth_token');
    await _storage.delete('auth_role');
    await _storage.delete('auth_user_id');
  }

  Future<bool> login(String email, String password, String deptCode) async {
    state = AuthState.loading();
    try {
      final dio = ref.read(dioProvider);
      final response = await dio.post(
        '/auth/login',
        data: {'email': email, 'password': password},
      );

      final token = response.data['access_token'];
      if (token != null) {
        final role = response.data['role']?.toString() ?? 'user';

        // Decode the JWT to get the user ID (stored in 'sub')
        String? userId;
        try {
          final decodedToken = JwtDecoder.decode(token);
          userId = decodedToken['sub'] as String?;
        } catch (_) {}

        await _storage.write('auth_token', token);
        await _storage.write('auth_role', role.toString());
        if (userId != null) {
          await _storage.write('auth_user_id', userId);
        }
        state = AuthState.authenticated(role);
        return true;
      }
      state = AuthState.error('Invalid credentials');
      return false;
    } on DioException catch (e) {
      final msg = _authErrorMessage(
        e.response?.data,
        'Network Error: Could not connect to backend',
      );
      state = AuthState.error(msg);
      return false;
    } catch (e) {
      state = AuthState.error('An unexpected error occurred.');
      return false;
    }
  }

  Future<bool> register(
    String name,
    String email,
    String password,
    String departmentCode,
  ) async {
    state = AuthState.loading();
    try {
      final dio = ref.read(dioProvider);

      final Map<String, dynamic> data = {
        'name': name,
        'email': email,
        'password': password,
      };

      final normalizedDepartmentCode = departmentCode.trim();
      if (normalizedDepartmentCode.isNotEmpty) {
        data['department_code'] = normalizedDepartmentCode;
      }

      await dio.post('/auth/signup', data: data);

      state = AuthState.initial();
      return true;
    } on DioException catch (e) {
      final msg = _authErrorMessage(
        e.response?.data,
        'Registration could not be completed.',
      );
      state = AuthState.error(msg);
      return false;
    } catch (e) {
      state = AuthState.error('Unexpected error occurred.');
      return false;
    }
  }

  Future<void> logout() async {
    await _clearStoredSession();
    state = AuthState.initial();
  }
}
