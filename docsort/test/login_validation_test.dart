import 'package:dio/dio.dart';
import 'package:docsort/core/network/dio_client.dart';
import 'package:docsort/core/network/session_store.dart';
import 'package:docsort/features/auth/presentation/screens/login_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

class MemorySessionStore implements SessionStore {
  final Map<String, String> values = {};

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

void main() {
  testWidgets('empty login is rejected locally without calling backend', (
    tester,
  ) async {
    var backendCalls = 0;

    final dio = Dio(BaseOptions(baseUrl: 'https://docsort.test'));
    dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) {
          backendCalls++;
          handler.reject(
            DioException(
              requestOptions: options,
              type: DioExceptionType.badResponse,
              response: Response<dynamic>(
                requestOptions: options,
                statusCode: 422,
                data: const {'detail': 'Invalid request'},
              ),
            ),
          );
        },
      ),
    );

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          sessionStoreProvider.overrideWithValue(MemorySessionStore()),
          dioProvider.overrideWithValue(dio),
        ],
        child: const MaterialApp(home: LoginScreen()),
      ),
    );

    await tester.pumpAndSettle();

    await tester.tap(find.text('Login Securely'));
    await tester.pumpAndSettle();

    expect(
      backendCalls,
      0,
      reason: 'An empty form must not send an authentication request.',
    );
    expect(find.text('Email address is required.'), findsOneWidget);
  });
}
