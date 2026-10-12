import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:docsort/core/network/dio_client.dart';
import 'package:docsort/core/network/session_store.dart';
import 'package:docsort/core/router/app_router.dart';
import 'package:docsort/main.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

class MemorySessionStore implements SessionStore {
  final Map<String, String> values;

  MemorySessionStore(this.values);

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

String _token() {
  String encode(Map<String, dynamic> value) =>
      base64Url.encode(utf8.encode(jsonEncode(value))).replaceAll('=', '');

  final header = encode({'alg': 'none', 'typ': 'JWT'});
  final payload = encode({
    'sub': 'member-1',
    'exp': 4102444800,
  });

  return '$header.$payload.signature';
}

Dio _dio() {
  final dio = Dio(BaseOptions(baseUrl: 'https://docsort.test'));

  dio.interceptors.add(
    InterceptorsWrapper(
      onRequest: (options, handler) {
        final dynamic data = switch (options.path) {
          '/auth/me' => <String, dynamic>{
              'id': 'member-1',
              'role': 'user',
            },
          '/cabinet/documents/doc-123' => <String, dynamic>{
              'id': 'doc-123',
              'filename': 'fixture.png',
              'doc_type': 'Invoice',
              'ocr_confidence': 0.95,
              'review_status': 'needs_review',
              'document_fields': <dynamic>[
                <String, dynamic>{
                  'id': 'field-1',
                  'label': 'Invoice Number',
                  'value': '12345',
                },
              ],
            },
          '/analytics/department' => <String, dynamic>{
              'total_documents': 1,
              'active_users_24h': 1,
              'tamper_flagged_count': 0,
              'cabinets_count': 1,
            },
          '/cabinet/documents' => <dynamic>[],
          '/upload/jobs/active' => <dynamic>[],
          _ => <String, dynamic>{},
        };

        handler.resolve(
          Response<dynamic>(
            requestOptions: options,
            statusCode: 200,
            data: data,
          ),
        );
      },
    ),
  );

  return dio;
}

void main() {
  testWidgets(
    'authenticated review deep link survives saved-session restoration',
    (tester) async {
      tester.binding.platformDispatcher.defaultRouteNameTestValue =
          '/review/doc-123?dup=true';

      addTearDown(
        tester.binding.platformDispatcher.clearDefaultRouteNameTestValue,
      );

      final container = ProviderContainer(
        overrides: [
          sessionStoreProvider.overrideWithValue(
            MemorySessionStore({
              'auth_token': _token(),
              'auth_role': 'user',
              'auth_user_id': 'member-1',
            }),
          ),
          dioProvider.overrideWithValue(_dio()),
        ],
      );

      addTearDown(container.dispose);

      await tester.pumpWidget(
        UncontrolledProviderScope(
          container: container,
          child: const DocSortApp(),
        ),
      );

      for (var i = 0; i < 15; i++) {
        await tester.pump(const Duration(milliseconds: 100));
      }

      final router = container.read(routerProvider);
      final uri = router.routerDelegate.currentConfiguration.uri;

      expect(uri.path, '/review/doc-123');
      expect(uri.queryParameters['dup'], 'true');
      expect(find.text('Review Extracted Data'), findsOneWidget);
    },
  );
}
