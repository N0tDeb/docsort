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

Dio _dio() {
  final dio = Dio(BaseOptions(baseUrl: 'https://docsort.test'));

  dio.interceptors.add(
    InterceptorsWrapper(
      onRequest: (options, handler) {
        final dynamic data = switch (options.path) {
          '/analytics/department' => <String, dynamic>{
              'total_documents': 3,
              'active_users_24h': 1,
              'tamper_flagged_count': 0,
              'cabinets_count': 2,
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
  testWidgets('Home Scan tab updates the browser route to upload', (tester) async {
    final router = GoRouter(
      initialLocation: '/home',
      routes: [
        GoRoute(path: '/home', builder: (_, _) => const HomeScreen()),
        GoRoute(
          path: '/upload',
          builder: (_, _) => const Scaffold(
            body: Center(child: Text('Upload Test Screen')),
          ),
        ),
      ],
    );

    addTearDown(router.dispose);

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          sessionStoreProvider.overrideWithValue(MemorySessionStore()),
          dioProvider.overrideWithValue(_dio()),
        ],
        child: MaterialApp.router(routerConfig: router),
      ),
    );

    await tester.pump();
    await tester.pump(const Duration(milliseconds: 1500));

    final scanTab = find.descendant(
      of: find.byType(NavigationBar),
      matching: find.text('Scan'),
    );

    expect(scanTab, findsOneWidget);

    await tester.tap(scanTab);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 200));

    expect(find.text('Upload Test Screen'), findsOneWidget);
    expect(router.routerDelegate.currentConfiguration.uri.path, '/upload');
  });
}
