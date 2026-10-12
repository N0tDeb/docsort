import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/scan_result_model.dart';
import '../services/scanner_service.dart';

final scannerServiceProvider = Provider((ref) => ScannerService());

final scannerProvider = NotifierProvider<ScannerNotifier, AsyncValue<ScanResultModel?>>(ScannerNotifier.new);

class ScannerNotifier extends Notifier<AsyncValue<ScanResultModel?>> {
  @override
  AsyncValue<ScanResultModel?> build() => const AsyncData(null);

  Future<bool> startScan() async {
    state = const AsyncLoading();
    try {
      final scannerService = ref.read(scannerServiceProvider);
      final pictures = await scannerService.scanDocument();

      if (pictures != null && pictures.isNotEmpty) {
        state = AsyncData(ScanResultModel(imagePaths: pictures));
        return true;
      } else {
        // User cancelled or no pictures taken
        state = const AsyncData(null);
        return false;
      }
    } catch (e, st) {
      state = AsyncError(e, st);
      return false;
    }
  }

  void clearScan() {
    state = const AsyncData(null);
  }
}
