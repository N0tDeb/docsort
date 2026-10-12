import 'package:dio/dio.dart';
import 'package:docsort/core/network/dio_client.dart';
import 'package:docsort/core/network/session_store.dart';
import 'package:docsort/features/home/presentation/screens/home_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

class MemorySessionStore implements SessionStore {
  @override
  Future<void> delete(String key) async {}

  @override
  Future<String?> read(String key) async => null;

  @override
  Future<void> write(String key, String value) async {}
}

Dio testDio() {
  final dio = Dio(BaseOptions(baseUrl: 'https://docsort.test'));

  dio.interceptors.add(
    InterceptorsWrapper(
      onRequest: (options, handler) {
        final dynamic data = switch (options.path) {
          '/analytics/department' => <String, dynamic>{
            'total_documents': 1,
            'active_users_24h': 1,
            'tamper_flagged_count': 0,
            'cabinets_count': 1,
          },
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
  testWidgets('Recent document updates route to review URL', (tester) async {
    await tester.binding.setSurfaceSize(const Size(1200, 1800));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final router = GoRouter(
      initialLocation: '/home',
      routes: [
        GoRoute(path: '/home', builder: (_, _) => const HomeScreen()),
        GoRoute(
          path: '/review/:id',
          builder: (_, state) =>
              Scaffold(body: Text('Review ${state.pathParameters['id']}')),
        ),
      ],
    );

    addTearDown(router.dispose);

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          sessionStoreProvider.overrideWithValue(MemorySessionStore()),
          dioProvider.overrideWithValue(testDio()),
          recentDocsProvider.overrideWith(
            (ref) async => <Map<String, dynamic>>[
              {
                'id': 'test-doc-123',
                'filename': 'Recent Test.pdf',
                'doc_type': 'PDF',
                'review_status': 'pending',
              },
            ],
          ),
        ],
        child: MaterialApp.router(routerConfig: router),
      ),
    );

    await tester.pump();
    await tester.pump(const Duration(milliseconds: 1500));

    await tester.scrollUntilVisible(
      find.text('Recent Test.pdf'),
      500,
      scrollable: find.byType(Scrollable).first,
    );

    expect(find.text('Recent Test.pdf'), findsOneWidget);

    await tester.tap(find.text('Recent Test.pdf'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 200));

    expect(
      router.routerDelegate.currentConfiguration.uri.path,
      '/review/test-doc-123',
    );
  });
}
