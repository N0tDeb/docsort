import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Caches the full document map fetched just before navigating to ReviewScreen.
/// This eliminates the duplicate API call ReviewScreen would otherwise make.
final reviewDocCacheProvider = NotifierProvider<ReviewCacheNotifier, Map<String, dynamic>?>(ReviewCacheNotifier.new);

class ReviewCacheNotifier extends Notifier<Map<String, dynamic>?> {
  @override
  Map<String, dynamic>? build() => null;

  void setDoc(Map<String, dynamic>? data) {
    state = data;
  }
}
