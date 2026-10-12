import 'package:docsort/features/analytics/presentation/screens/analytics_screen.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('analytics weekday labels are derived from returned ISO dates', () {
    expect(analyticsWeekdayLabel('2026-09-10'), 'Thu');
    expect(analyticsWeekdayLabel('2026-09-13'), 'Sun');
    expect(analyticsWeekdayLabel('2026-09-16'), 'Wed');
    expect(analyticsWeekdayLabel('not-a-date'), '');
  });
}
