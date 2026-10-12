import 'package:docsort/features/upload/presentation/screens/upload_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';

void main() {
  testWidgets('Upload Scan Document updates the browser route to scan', (
    tester,
  ) async {
    final router = GoRouter(
      initialLocation: '/upload',
      routes: [
        GoRoute(
          path: '/upload',
          builder: (_, _) => const UploadScreen(),
        ),
        GoRoute(
          path: '/scan',
          builder: (_, _) => const Scaffold(
            body: Center(child: Text('Scanner Test Screen')),
          ),
        ),
      ],
    );

    addTearDown(router.dispose);

    await tester.pumpWidget(
      ProviderScope(
        child: MaterialApp.router(routerConfig: router),
      ),
    );

    await tester.pump();

    expect(find.text('Scan Document'), findsOneWidget);

    await tester.tap(find.text('Scan Document'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 200));

    expect(find.text('Scanner Test Screen'), findsOneWidget);
    expect(router.routerDelegate.currentConfiguration.uri.path, '/scan');
  });
}
