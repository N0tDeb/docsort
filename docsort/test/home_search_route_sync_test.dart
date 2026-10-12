import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('Home Search navigation uses URL-synchronizing navigation', () {
    final source = File(
      'lib/features/home/presentation/screens/home_screen.dart',
    ).readAsStringSync();

    expect(
      source,
      isNot(contains("context.push('/search')")),
    );

    expect(
      source,
      contains("context.go('/search')"),
    );
  });
}
