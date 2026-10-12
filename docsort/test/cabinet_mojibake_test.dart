import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('cabinet detail contains clean user-visible metadata strings', () {
    final source = File(
      'lib/features/cabinet/presentation/screens/cabinet_detail_screen.dart',
    ).readAsStringSync();

    expect(source, isNot(contains('Ã¢Å¡Â Tampered')));
    expect(source, isNot(contains('Ã¢â‚¬Â¢')));

    expect(source, contains("_Tag('Tampered', AppColors.error)"));
    expect(source, contains(".join('  •  ')"));
    expect(source, contains("'By \$uploadedBy  •  \$shortDate'"));
  });
}
