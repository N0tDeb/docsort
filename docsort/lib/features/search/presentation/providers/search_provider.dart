import 'dart:async';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../../../core/network/dio_client.dart';

class SearchSnippetSegment {
  final String text;
  final bool highlighted;

  const SearchSnippetSegment({required this.text, required this.highlighted});
}

List<SearchSnippetSegment> parseSearchSnippet(String snippet) {
  final parts = snippet.split('^^');

  return [
    for (var i = 0; i < parts.length; i++)
      if (parts[i].isNotEmpty)
        SearchSnippetSegment(text: parts[i], highlighted: i.isOdd),
  ];
}

class SearchResult {
  final String id;
  final String title;
  final String snippet;
  final String type;
  final double ocrConfidence;
  final String reviewStatus;

  SearchResult({
    required this.id,
    required this.title,
    required this.snippet,
    required this.type,
    required this.ocrConfidence,
    required this.reviewStatus,
  });

  factory SearchResult.fromJson(Map<String, dynamic> json) {
    String snippet = '';
    final highlights = json['match_highlights'];
    if (highlights is List && highlights.isNotEmpty) {
      snippet = highlights[0]['snippet'] ?? '';
    }

    return SearchResult(
      id: json['id'] ?? '',
      title: json['filename'] ?? 'Unknown',
      snippet: snippet.isNotEmpty ? snippet : 'No preview available',
      type: json['doc_type'] ?? 'Document',
      ocrConfidence: (json['ocr_confidence'] as num?)?.toDouble() ?? 0.0,
      reviewStatus: json['review_status'] as String? ?? 'needs_review',
    );
  }
}

final searchQueryProvider = NotifierProvider<SearchQueryNotifier, String>(
  SearchQueryNotifier.new,
);

class SearchQueryNotifier extends Notifier<String> {
  @override
  String build() => '';
  void setQuery(String q) => state = q;
}

final searchResultsProvider =
    NotifierProvider<SearchNotifier, AsyncValue<List<SearchResult>>>(
      SearchNotifier.new,
    );

class SearchNotifier extends Notifier<AsyncValue<List<SearchResult>>> {
  Timer? _debounce;

  @override
  AsyncValue<List<SearchResult>> build() {
    ref.onDispose(() => _debounce?.cancel());
    return const AsyncValue.data([]);
  }

  void onQueryChanged(String query) {
    final normalizedQuery = query.trim();
    ref.read(searchQueryProvider.notifier).setQuery(normalizedQuery);
    if (_debounce?.isActive ?? false) _debounce?.cancel();

    if (normalizedQuery.isEmpty) {
      state = const AsyncValue.data([]);
      return;
    }

    state = const AsyncValue.loading();
    _debounce = Timer(const Duration(milliseconds: 500), () {
      _executeSearch(normalizedQuery);
    });
  }

  Future<void> _executeSearch(String query) async {
    state = const AsyncValue.loading();
    try {
      final dio = ref.read(dioProvider);
      final response = await dio.get('/search', queryParameters: {'q': query});
      final results = (response.data as List)
          .map((e) => SearchResult.fromJson(e))
          .toList();
      state = AsyncValue.data(results);
    } catch (e) {
      state = AsyncValue.error(e, StackTrace.current);
    }
  }
}
