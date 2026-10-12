import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:docsort/core/network/dio_client.dart';
import 'package:docsort/core/network/session_store.dart';
import 'package:docsort/features/auth/presentation/providers/auth_provider.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

class MemorySessionStore implements SessionStore {
  final Map<String, String> values;

  MemorySessionStore([Map<String, String>? initial])
      : values = Map<String, String>.from(initial ?? const {});

  @override
  Future<void> delete(String key) async {
    values.remove(key);
  }

  @override
  Future<String?> read(String key) async => values[key];

  @override
  Future<void> write(String key, String value) async {
    values[key] = value;
  }
}

String _jwt({required String sub, required int expiresAt}) {
  String encode(Map<String, dynamic> value) =>
      base64Url.encode(utf8.encode(jsonEncode(value))).replaceAll('=', '');

  return '${encode({'alg': 'none', 'typ': 'JWT'})}.'
      '${encode({'sub': sub, 'exp': expiresAt})}.signature';
}

Dio _dio(void Function(RequestOptions, RequestInterceptorHandler) onRequest) {
  final dio = Dio(BaseOptions(baseUrl: 'https://docsort.test'));
  dio.interceptors.add(InterceptorsWrapper(onRequest: onRequest));
  return dio;
}

Future<void> _settleUntil(bool Function() condition) async {
  for (var i = 0; i < 30; i++) {
    if (condition()) return;
    await Future<void>.delayed(Duration.zero);
  }
  fail('Provider state did not settle in time');
}

void main() {
  test('restores a valid saved session using live backend role and user id', () async {
    final token = _jwt(
      sub: 'jwt-user',
      expiresAt: DateTime.now().add(const Duration(hours: 1)).millisecondsSinceEpoch ~/ 1000,
    );
    final store = MemorySessionStore({'auth_token': token, 'auth_role': 'user'});
    final dio = _dio((options, handler) {
      expect(options.path, '/auth/me');
      handler.resolve(Response<dynamic>(
        requestOptions: options,
        statusCode: 200,
        data: {'id': 'live-user', 'role': 'admin'},
      ));
    });

    final container = ProviderContainer.test(overrides: [
      sessionStoreProvider.overrideWithValue(store),
      dioProvider.overrideWithValue(dio),
    ]);

    container.read(authProvider);
    await _settleUntil(
      () => container.read(authProvider).status == AuthStatus.authenticated,
    );

    final state = container.read(authProvider);
    expect(state.role, 'admin');
    expect(state.isAdmin, isTrue);
    expect(store.values['auth_role'], 'admin');
    expect(store.values['auth_user_id'], 'live-user');
  });

  test('expired saved session is cleared without calling the backend', () async {
    final token = _jwt(
      sub: 'expired-user',
      expiresAt: DateTime.now().subtract(const Duration(hours: 1)).millisecondsSinceEpoch ~/ 1000,
    );
    final store = MemorySessionStore({
      'auth_token': token,
      'auth_role': 'admin',
      'auth_user_id': 'expired-user',
    });
    var backendCalls = 0;
    final dio = _dio((options, handler) {
      backendCalls++;
      handler.resolve(Response<dynamic>(
        requestOptions: options,
        statusCode: 200,
        data: const <String, dynamic>{},
      ));
    });

    final container = ProviderContainer.test(overrides: [
      sessionStoreProvider.overrideWithValue(store),
      dioProvider.overrideWithValue(dio),
    ]);

    container.read(authProvider);
    await _settleUntil(() => store.values.isEmpty);

    expect(container.read(authProvider).status, AuthStatus.initial);
    expect(store.values, isEmpty);
    expect(backendCalls, 0);
  });

  test('malformed saved token is cleared instead of breaking restoration', () async {
    final store = MemorySessionStore({
      'auth_token': 'not-a-jwt',
      'auth_role': 'admin',
      'auth_user_id': 'stale-user',
    });
    var backendCalls = 0;
    final dio = _dio((options, handler) {
      backendCalls++;
      handler.resolve(Response<dynamic>(
        requestOptions: options,
        statusCode: 200,
        data: const <String, dynamic>{},
      ));
    });
    final container = ProviderContainer.test(overrides: [
      sessionStoreProvider.overrideWithValue(store),
      dioProvider.overrideWithValue(dio),
    ]);

    container.read(authProvider);
    await _settleUntil(() => store.values.isEmpty);

    expect(container.read(authProvider).status, AuthStatus.initial);
    expect(backendCalls, 0);
  });

  test('login persists token role and JWT subject', () async {
    final token = _jwt(
      sub: 'user-123',
      expiresAt: DateTime.now().add(const Duration(hours: 1)).millisecondsSinceEpoch ~/ 1000,
    );
    final store = MemorySessionStore();
    final dio = _dio((options, handler) {
      expect(options.path, '/auth/login');
      expect(options.data, {'email': 'student@example.com', 'password': 'secret'});
      handler.resolve(Response<dynamic>(
        requestOptions: options,
        statusCode: 200,
        data: {'access_token': token, 'role': 'user'},
      ));
    });

    final container = ProviderContainer.test(overrides: [
      sessionStoreProvider.overrideWithValue(store),
      dioProvider.overrideWithValue(dio),
    ]);

    final ok = await container
        .read(authProvider.notifier)
        .login('student@example.com', 'secret', 'ignored');

    expect(ok, isTrue);
    expect(container.read(authProvider).status, AuthStatus.authenticated);
    expect(store.values['auth_token'], token);
    expect(store.values['auth_role'], 'user');
    expect(store.values['auth_user_id'], 'user-123');
  });

  test('registration trims optional department code and returns to initial state', () async {
    final store = MemorySessionStore();
    Map<String, dynamic>? sent;
    final dio = _dio((options, handler) {
      expect(options.path, '/auth/signup');
      sent = Map<String, dynamic>.from(options.data as Map);
      handler.resolve(Response<dynamic>(
        requestOptions: options,
        statusCode: 201,
        data: const {'message': 'Registration request received.'},
      ));
    });

    final container = ProviderContainer.test(overrides: [
      sessionStoreProvider.overrideWithValue(store),
      dioProvider.overrideWithValue(dio),
    ]);

    final ok = await container.read(authProvider.notifier).register(
          'Student User',
          'student@example.com',
          'secret',
          '  IT  ',
        );

    expect(ok, isTrue);
    expect(sent?['department_code'], 'IT');
    expect(container.read(authProvider).status, AuthStatus.initial);
  });

  test('logout clears every stored session key', () async {
    final store = MemorySessionStore();
    final dio = _dio((options, handler) {
      handler.resolve(Response<dynamic>(
        requestOptions: options,
        statusCode: 200,
      ));
    });
    final container = ProviderContainer.test(overrides: [
      sessionStoreProvider.overrideWithValue(store),
      dioProvider.overrideWithValue(dio),
    ]);

    final notifier = container.read(authProvider.notifier);
    await Future<void>.delayed(Duration.zero);
    store.values.addAll({
      'auth_token': 'token',
      'auth_role': 'admin',
      'auth_user_id': 'user-1',
    });
    await notifier.logout();

    expect(store.values, isEmpty);
    expect(container.read(authProvider).status, AuthStatus.initial);
  });
}
