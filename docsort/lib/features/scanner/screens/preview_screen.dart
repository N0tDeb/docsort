import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_text_styles.dart';
import '../providers/scanner_provider.dart';
import '../widgets/scan_preview_image.dart';
import '../../upload/presentation/providers/upload_provider.dart';

class PreviewScreen extends ConsumerWidget {
  const PreviewScreen({super.key});

  void _onUpload(BuildContext context, WidgetRef ref, String imagePath) async {
    // Show some loading indicator if immediately required
    final success = await ref
        .read(uploadProvider.notifier)
        .uploadDocument(imagePath);
    if (success && context.mounted) {
      final jobId = ref.read(uploadProvider).jobId;
      if (jobId != null && jobId.isNotEmpty) {
        context.go('/processing?job=${Uri.encodeQueryComponent(jobId)}');
      }
    } else if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Failed to start upload. Please try again.'),
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final scanState = ref.watch(scannerProvider);

    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppBar(
        title: const Text(
          'Review Scan',
          style: TextStyle(color: AppColors.textPrimary),
        ),
        backgroundColor: Colors.transparent,
        elevation: 0,
        iconTheme: const IconThemeData(color: AppColors.textPrimary),
      ),
      body: scanState.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (_, _) => const Center(
          child: Text(
            'Could not load the scan preview. Please try again.',
            textAlign: TextAlign.center,
          ),
        ),
        data: (result) {
          if (result == null || result.imagePaths.isEmpty) {
            return Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  const Icon(
                    Icons.error_outline_rounded,
                    size: 64,
                    color: AppColors.error,
                  ),
                  const SizedBox(height: 16),
                  Text('No document captured.', style: AppTextStyles.h2),
                  const SizedBox(height: 24),
                  ElevatedButton(
                    onPressed: () => context.pushReplacement('/scan'),
                    child: const Text('Try Again'),
                  ),
                ],
              ),
            );
          }

          final imagePath = result.imagePaths.first;

          return Column(
            children: [
              Expanded(
                child: Container(
                  margin: const EdgeInsets.all(24),
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(24),
                    boxShadow: [
                      BoxShadow(
                        color: Colors.black.withValues(alpha: 0.1),
                        blurRadius: 20,
                        offset: const Offset(0, 10),
                      ),
                    ],
                  ),
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(24),
                    child: ScanPreviewImage(imagePath: imagePath),
                  ),
                ),
              ),
              Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: 24,
                  vertical: 32,
                ),
                decoration: const BoxDecoration(
                  color: AppColors.surfaceLowest,
                  borderRadius: BorderRadius.vertical(top: Radius.circular(32)),
                  boxShadow: [
                    BoxShadow(
                      color: Colors.black12,
                      blurRadius: 10,
                      offset: Offset(0, -4),
                    ),
                  ],
                ),
                child: SafeArea(
                  child: Column(
                    children: [
                      Row(
                        children: [
                          Expanded(
                            child: OutlinedButton.icon(
                              onPressed: () => context.pushReplacement('/scan'),
                              icon: const Icon(Icons.refresh_rounded),
                              label: const Text('Retake'),
                              style: OutlinedButton.styleFrom(
                                foregroundColor: AppColors.primary,
                                padding: const EdgeInsets.symmetric(
                                  vertical: 16,
                                ),
                                shape: RoundedRectangleBorder(
                                  borderRadius: BorderRadius.circular(16),
                                ),
                                side: const BorderSide(
                                  color: AppColors.primary,
                                ),
                              ),
                            ),
                          ),
                          const SizedBox(width: 16),
                          Expanded(
                            flex: 2,
                            child: ElevatedButton.icon(
                              onPressed: () =>
                                  _onUpload(context, ref, imagePath),
                              icon: const Icon(Icons.cloud_upload_rounded),
                              label: const Text('Confirm & Upload'),
                              style: ElevatedButton.styleFrom(
                                backgroundColor: AppColors.primary,
                                foregroundColor: Colors.white,
                                padding: const EdgeInsets.symmetric(
                                  vertical: 16,
                                ),
                                shape: RoundedRectangleBorder(
                                  borderRadius: BorderRadius.circular(16),
                                ),
                                elevation: 0,
                              ),
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
            ],
          );
        },
      ),
    );
  }
}
