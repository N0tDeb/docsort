import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../../../core/network/dio_client.dart';

class HomeMetrics {
  final int totalDocs;
  final int active24h;
  final int tamperAlerts;
  final int cabinets;

  HomeMetrics({
    this.totalDocs = 0,
    this.active24h = 0,
    this.tamperAlerts = 0,
    this.cabinets = 0,
  });

  factory HomeMetrics.fromJson(Map<String, dynamic> json) {
    return HomeMetrics(
      totalDocs: json['total_documents'] ?? 0,
      active24h: json['active_users_24h'] ?? json['active_users_today'] ?? 0,
      tamperAlerts: json['tamper_flagged_count'] ?? 0,
      cabinets: json['cabinets_count'] ?? 0,
    );
  }
}

final homeProvider = NotifierProvider<HomeNotifier, AsyncValue<HomeMetrics>>(HomeNotifier.new);

class HomeNotifier extends Notifier<AsyncValue<HomeMetrics>> {
  @override
  AsyncValue<HomeMetrics> build() {
    fetchMetrics();
    return const AsyncValue.loading();
  }

  Future<void> fetchMetrics() async {
    state = const AsyncValue.loading();
    try {
      final dio = ref.read(dioProvider);
      final response = await dio.get('/analytics/department');
      state = AsyncValue.data(HomeMetrics.fromJson(response.data));
    } catch (e, st) {
      state = AsyncValue.error(e, st);
    }
  }
}
