import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('Search result tap uses URL-synchronizing Result navigation', () {
    final source = File(
      'lib/features/search/presentation/screens/search_screen.dart',
    ).readAsStringSync();

    expect(
      source,
      isNot(contains("context.push('/result/\${item.id}')")),
    );

    expect(
      source,
      contains("context.go('/result/\${item.id}')"),
    );
  });
}
