import 'package:dio/dio.dart';
import 'package:docsort/core/network/dio_client.dart';
import 'package:docsort/core/network/session_store.dart';
import 'package:docsort/features/auth/presentation/screens/login_screen.dart';
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
  testWidgets('login title stays above form card on narrow desktop viewport', (
    tester,
  ) async {
    await tester.binding.setSurfaceSize(const Size(764, 723));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    final dio = Dio(BaseOptions(baseUrl: 'https://docsort.test'));

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

    final titleRect = tester.getRect(find.text('DocSort'));
    final formRect = tester.getRect(find.byType(Form));

    // The Form sits inside the login Container's 24 px padding.
    final cardTop = formRect.top - 24;

    expect(
      titleRect.bottom,
      lessThanOrEqualTo(cardTop - 8),
      reason: 'The DocSort title must not be covered by the login card.',
    );
  });
}
