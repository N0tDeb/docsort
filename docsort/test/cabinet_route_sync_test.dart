import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('cabinet folder tap uses URL-synchronizing navigation', () {
    final source = File(
      'lib/features/cabinet/presentation/screens/cabinet_list_screen.dart',
    ).readAsStringSync();

    expect(
      source,
      isNot(contains("context.push('/cabinet/\${folder.id}')")),
    );

    expect(
      source,
      contains("context.go('/cabinet/\${folder.id}')"),
    );
  });
}
