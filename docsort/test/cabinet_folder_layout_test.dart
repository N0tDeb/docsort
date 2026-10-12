import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('Cabinet folder grid keeps compact desktop card height', () {
    final source = File(
      'lib/features/cabinet/presentation/screens/cabinet_list_screen.dart',
    ).readAsStringSync();

    expect(source, contains('mainAxisExtent: 150'));
    expect(source, isNot(contains('childAspectRatio: 0.9')));
  });
}
