import 'dart:async';

import 'package:docsort/core/network/session_store.dart';
import 'package:docsort/main.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

class DelayedSessionStore implements SessionStore {
  final tokenCompleter = Completer<String?>();

  @override
  Future<String?> read(String key) {
    if (key == 'auth_token') {
      return tokenCompleter.future;
    }
    return Future.value(null);
  }

  @override
  Future<void> write(String key, String value) async {}

  @override
  Future<void> delete(String key) async {}
}

void main() {
  testWidgets(
    'saved-session restore hides login and accepts a protected initial route',
    (tester) async {
      tester.binding.platformDispatcher.defaultRouteNameTestValue = '/home';
      addTearDown(
        tester.binding.platformDispatcher.clearDefaultRouteNameTestValue,
      );

      final store = DelayedSessionStore();

      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            sessionStoreProvider.overrideWithValue(store),
          ],
          child: const DocSortApp(),
        ),
      );

      await tester.pump();

      expect(find.text('Welcome Back'), findsNothing);
      expect(find.byType(CircularProgressIndicator), findsOneWidget);

      expect(
        find.byType(Navigator),
        findsNothing,
        reason:
            'Auth restoration must not create a temporary Navigator that can consume the browser deep link.',
      );

      final startupException = tester.takeException();
      expect(
        startupException,
        isNull,
        reason: 'Restoring auth must accept the browser initial route.',
      );

      store.tokenCompleter.complete(null);

      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      expect(find.text('Welcome Back'), findsOneWidget);
    },
  );
}
