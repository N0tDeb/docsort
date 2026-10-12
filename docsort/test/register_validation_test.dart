import 'package:dio/dio.dart';
import 'package:docsort/core/network/dio_client.dart';
import 'package:docsort/core/network/session_store.dart';
import 'package:docsort/features/auth/presentation/screens/register_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

class MemorySessionStore implements SessionStore {
  @override
  Future<void> delete(String key) async {}

  @override
  Future<String?> read(String key) async => null;

  @override
  Future<void> write(String key, String value) async {}
}

void main() {
  testWidgets(
    'empty registration is rejected locally without calling backend',
    (tester) async {
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
          child: const MaterialApp(home: RegisterScreen()),
        ),
      );

      await tester.pumpAndSettle();

      final registerButton = find.text('Register Account');
      await tester.ensureVisible(registerButton);
      await tester.pumpAndSettle();
      await tester.tap(registerButton);
      await tester.pumpAndSettle();

      expect(
        backendCalls,
        0,
        reason: 'An empty registration form must not call the backend.',
      );

      expect(find.text('Full name is required.'), findsOneWidget);
      expect(find.text('Email address is required.'), findsOneWidget);
      expect(find.text('Password is required.'), findsOneWidget);

      // Department Code is intentionally optional.
      expect(find.text('Department code is required.'), findsNothing);
    },
  );
}
