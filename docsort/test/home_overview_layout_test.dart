import 'package:dio/dio.dart';
import 'package:docsort/core/network/dio_client.dart';
import 'package:docsort/core/network/session_store.dart';
import 'package:docsort/features/home/presentation/screens/home_screen.dart';
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

Dio _homeDio() {
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
  testWidgets('home overview cards stay bounded on a desktop viewport', (
    tester,
  ) async {
    await tester.binding.setSurfaceSize(const Size(1600, 900));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          sessionStoreProvider.overrideWithValue(MemorySessionStore()),
          dioProvider.overrideWithValue(_homeDio()),
        ],
        child: const MaterialApp(home: HomeScreen()),
      ),
    );

    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
    await tester.pump(const Duration(milliseconds: 1500));

    expect(find.text('Total Scans'), findsOneWidget);

    final overviewGrid = find.byType(GridView).first;
    final gridHeight = tester.getSize(overviewGrid).height;

    expect(
      gridHeight,
      lessThanOrEqualTo(420),
      reason: 'Desktop Overview metrics must not consume multiple viewport rows.',
    );
  });
}

