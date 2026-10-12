import 'package:dio/dio.dart';
import 'package:docsort/core/network/dio_client.dart';
import 'package:docsort/features/search/presentation/providers/search_provider.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

Dio _searchDio({
  required void Function(String query) onQuery,
  bool fail = false,
}) {
  final dio = Dio(BaseOptions(baseUrl: 'https://docsort.test'));
  dio.interceptors.add(
    InterceptorsWrapper(
      onRequest: (options, handler) {
        final query = options.queryParameters['q']?.toString() ?? '';
        onQuery(query);
        if (fail) {
          handler.reject(
            DioException(
              requestOptions: options,
              type: DioExceptionType.connectionError,
              error: 'offline',
            ),
          );
          return;
        }
        handler.resolve(
          Response<dynamic>(
            requestOptions: options,
            statusCode: 200,
            data: [
              {
                'id': 'doc-1',
                'filename': 'marksheet.pdf',
                'doc_type': 'Certificate',
                'ocr_confidence': 0.94,
                'review_status': 'verified',
                'match_highlights': [
                  {'snippet': 'BTech marksheet'},
                ],
              },
            ],
          ),
        );
      },
    ),
  );
  return dio;
}

void main() {
  test('search result parsing keeps backend highlight and confidence', () {
    final result = SearchResult.fromJson({
      'id': 'doc-1',
      'filename': 'marksheet.pdf',
      'doc_type': 'Certificate',
      'ocr_confidence': 0.94,
      'review_status': 'verified',
      'match_highlights': [
        {'snippet': 'BTech marksheet'},
      ],
    });

    expect(result.title, 'marksheet.pdf');
    expect(result.snippet, 'BTech marksheet');
    expect(result.ocrConfidence, closeTo(0.94, 0.0001));
  });

  test('search highlight markers are parsed without leaking markers', () {
    final segments = parseSearchSnippet('^^TEST^^-1001 by ^^Example^^ Person');

    expect(
      segments.map((segment) => segment.text).join(),
      'TEST-1001 by Example Person',
    );

    expect(
      segments
          .where((segment) => segment.highlighted)
          .map((segment) => segment.text),
      ['TEST', 'Example'],
    );
  });

  test('debounce sends only the latest normalized query', () async {
    final queries = <String>[];
    final container = ProviderContainer.test(
      overrides: [
        dioProvider.overrideWithValue(_searchDio(onQuery: queries.add)),
      ],
    );
    final notifier = container.read(searchResultsProvider.notifier);

    notifier.onQueryChanged(' first ');
    await Future<void>.delayed(const Duration(milliseconds: 100));
    notifier.onQueryChanged('  second  ');
    await Future<void>.delayed(const Duration(milliseconds: 550));

    expect(queries, ['second']);
    final results = container.read(searchResultsProvider).requireValue;
    expect(results, hasLength(1));
    expect(container.read(searchQueryProvider), 'second');
  });

  test('non-empty query enters loading state during debounce', () {
    final queries = <String>[];
    final container = ProviderContainer.test(
      overrides: [
        dioProvider.overrideWithValue(_searchDio(onQuery: queries.add)),
      ],
    );

    container.read(searchResultsProvider.notifier).onQueryChanged('finance');

    expect(container.read(searchQueryProvider), 'finance');
    expect(container.read(searchResultsProvider).isLoading, isTrue);
    expect(queries, isEmpty);

    container.dispose();
  });
  test('blank query cancels pending search and clears results', () async {
    final queries = <String>[];
    final container = ProviderContainer.test(
      overrides: [
        dioProvider.overrideWithValue(_searchDio(onQuery: queries.add)),
      ],
    );
    final notifier = container.read(searchResultsProvider.notifier);

    notifier.onQueryChanged('pending');
    await Future<void>.delayed(const Duration(milliseconds: 100));
    notifier.onQueryChanged('   ');
    await Future<void>.delayed(const Duration(milliseconds: 550));

    expect(queries, isEmpty);
    expect(container.read(searchQueryProvider), '');
    expect(container.read(searchResultsProvider).requireValue, isEmpty);
  });

  test('backend search failure remains an error state', () async {
    final queries = <String>[];
    final container = ProviderContainer.test(
      overrides: [
        dioProvider.overrideWithValue(
          _searchDio(onQuery: queries.add, fail: true),
        ),
      ],
      retry: (_, _) => null,
    );

    container.read(searchResultsProvider.notifier).onQueryChanged('invoice');
    await Future<void>.delayed(const Duration(milliseconds: 550));
    await Future<void>.delayed(Duration.zero);

    expect(queries, ['invoice']);
    expect(container.read(searchResultsProvider).hasError, isTrue);
  });

  test(
    'disposing provider container cancels a pending debounce timer',
    () async {
      final queries = <String>[];
      final container = ProviderContainer.test(
        overrides: [
          dioProvider.overrideWithValue(_searchDio(onQuery: queries.add)),
        ],
      );

      container
          .read(searchResultsProvider.notifier)
          .onQueryChanged('never-run');
      container.dispose();
      await Future<void>.delayed(const Duration(milliseconds: 550));

      expect(queries, isEmpty);
    },
  );
}
