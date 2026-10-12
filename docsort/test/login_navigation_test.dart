import 'package:dio/dio.dart';
import 'package:docsort/core/network/dio_client.dart';
import 'package:docsort/core/network/session_store.dart';
import 'package:docsort/features/auth/presentation/screens/login_screen.dart';
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

void main() {
  testWidgets('register button navigates to the register URL', (tester) async {
    final dio = Dio(BaseOptions(baseUrl: 'https://docsort.test'));

    final router = GoRouter(
      initialLocation: '/login',
      routes: [
        GoRoute(path: '/login', builder: (_, _) => const LoginScreen()),
        GoRoute(
          path: '/register',
          builder: (_, _) => const Scaffold(
            body: Center(child: Text('Registration Test Screen')),
          ),
        ),
      ],
    );

    addTearDown(router.dispose);

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          sessionStoreProvider.overrideWithValue(MemorySessionStore()),
          dioProvider.overrideWithValue(dio),
        ],
        child: MaterialApp.router(routerConfig: router),
      ),
    );

    await tester.pumpAndSettle();

    await tester.tap(find.text('Register new account'));
    await tester.pumpAndSettle();

    expect(find.text('Registration Test Screen'), findsOneWidget);
    expect(router.routerDelegate.currentConfiguration.uri.path, '/register');
  });
}
