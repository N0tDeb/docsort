import 'package:dio/dio.dart';
import 'package:docsort/core/network/dio_client.dart';
import 'package:docsort/features/analytics/presentation/screens/analytics_screen.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

Dio _failingDio() {
  final dio = Dio(BaseOptions(baseUrl: 'https://docsort.test'));
  dio.interceptors.add(
    InterceptorsWrapper(
      onRequest: (options, handler) {
        handler.reject(
          DioException(
            requestOptions: options,
            type: DioExceptionType.connectionError,
            error: 'backend unavailable',
          ),
        );
      },
    ),
  );
  return dio;
}

Dio _successfulDio() {
  final dio = Dio(BaseOptions(baseUrl: 'https://docsort.test'));
  dio.interceptors.add(
    InterceptorsWrapper(
      onRequest: (options, handler) {
        final data = options.path == '/analytics/global'
            ? <String, dynamic>{
                'total_documents': 0,
                'tamper_flagged_count': 0,
                'uploaded_today': 0,
                'active_users_24h': 0,
              }
            : <String, dynamic>{
                'doc_type_distribution': <String, dynamic>{},
                'daily_uploads': <dynamic>[],
                'avg_ocr_confidence': 0.0,
              };
        handler.resolve(
          Response<dynamic>(
            requestOptions: options,
            statusCode: 200,
            data: data,
          ),
        );
      },
    ),
  );
  return dio;
}

void main() {
  test('department analytics preserves backend failures as provider errors', () async {
    final container = ProviderContainer.test(
      overrides: [dioProvider.overrideWithValue(_failingDio())],
      retry: (_, _) => null,
    );

    await expectLater(
      container.read(analyticsDeptProvider.future),
      throwsA(isA<DioException>()),
    );
  });

  test('global analytics preserves backend failures as provider errors', () async {
    final container = ProviderContainer.test(
      overrides: [dioProvider.overrideWithValue(_failingDio())],
      retry: (_, _) => null,
    );

    await expectLater(
      container.read(analyticsGlobalProvider.future),
      throwsA(isA<DioException>()),
    );
  });

  test('legitimate zero analytics remains successful data', () async {
    final container = ProviderContainer.test(
      overrides: [dioProvider.overrideWithValue(_successfulDio())],
      retry: (_, _) => null,
    );

    final global = await container.read(analyticsGlobalProvider.future);
    final department = await container.read(analyticsDeptProvider.future);

    expect(global['total_documents'], 0);
    expect(department['doc_type_distribution'], isEmpty);
    expect(department['daily_uploads'], isEmpty);
  });
}
