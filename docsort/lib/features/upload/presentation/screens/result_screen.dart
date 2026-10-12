import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../../core/theme/app_colors.dart';
import '../../../../core/theme/app_text_styles.dart';
import '../../../../core/network/dio_client.dart';
import '../../../../core/services/file_export_service.dart';
import '../../../../core/widgets/app_button.dart';
import '../../../../core/widgets/app_snackbar.dart';
import '../../../share/presentation/widgets/share_document_dialog.dart';

// Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬ Provider Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
final documentDetailProvider = FutureProvider.autoDispose
    .family<Map<String, dynamic>, String>((ref, docId) async {
      final dio = ref.watch(dioProvider);
      // docId is the actual document_id passed from processing screen
      final docResp = await dio.get('/cabinet/documents/$docId');
      return Map<String, dynamic>.from(docResp.data);
    });

class ResultScreen extends ConsumerWidget {
  final String docId;
  final String? returnLocation;

  const ResultScreen({super.key, required this.docId, this.returnLocation});

  String _reviewRoute(String documentId) {
    final resultRoute = returnLocation == null
        ? '/result/$documentId'
        : '/result/$documentId?from=${Uri.encodeComponent(returnLocation!)}';

    return '/review/$documentId?from=${Uri.encodeComponent(resultRoute)}';
  }

  Future<void> _downloadOriginal(
    BuildContext context,
    WidgetRef ref,
    String documentId,
    String filename,
  ) async {
    try {
      await ref
          .read(fileExportServiceProvider)
          .download(
            dio: ref.read(dioProvider),
            path: '/export/document/$documentId',
            fallbackFileName: filename,
          );

      if (context.mounted) {
        AppSnackbar.showSuccess(context, 'Document download started.');
      }
    } catch (_) {
      if (context.mounted) {
        AppSnackbar.showError(context, 'Could not download document.');
      }
    }
  }

  void _openCabinet(BuildContext context) {
    // The document is already durable in the backend at this stage.
    AppSnackbar.showSuccess(context, 'Document saved to Cabinet');
    context.go('/cabinet');
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(documentDetailProvider(docId));

    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppBar(
        title: const Text(
          'Analysis Result',
          style: TextStyle(fontWeight: FontWeight.bold),
        ),
        backgroundColor: AppColors.background,
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_rounded),
          onPressed: () {
            if (context.canPop()) {
              context.pop();
            } else {
              context.go(returnLocation ?? '/home');
            }
          },
        ),
      ),
      body: async.when(
        loading: () => const Center(
          child: CircularProgressIndicator(color: AppColors.primary),
        ),
        error: (_, _) => Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(
                  Icons.error_outline_rounded,
                  size: 64,
                  color: AppColors.error,
                ),
                const SizedBox(height: 16),
                Text(
                  'Could not load this document',
                  style: AppTextStyles.headlineSm,
                ),
                const SizedBox(height: 8),
                Text(
                  'Please check your connection and try again.',
                  textAlign: TextAlign.center,
                  style: AppTextStyles.bodySm,
                ),
                const SizedBox(height: 16),
                ElevatedButton.icon(
                  onPressed: () =>
                      ref.invalidate(documentDetailProvider(docId)),
                  icon: const Icon(Icons.refresh_rounded),
                  label: const Text('Retry'),
                ),
              ],
            ),
          ),
        ),
        data: (doc) {
          final confidence = (doc['ocr_confidence'] as num?)?.toDouble() ?? 0.0;
          final docType = doc['doc_type'] ?? 'Document';
          final isTampered = doc['is_tampered'] == true;
          final tamperFlags = List<String>.from(doc['tamper_flags'] ?? []);
          final fields = List<Map<String, dynamic>>.from(
            doc['document_fields'] ?? [],
          );
          final documentId = doc['id'] ?? docId;
          final reviewStatus =
              doc['review_status'] as String? ?? 'needs_review';

          return SingleChildScrollView(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Status Banner
                _buildStatusBanner(reviewStatus, isTampered, tamperFlags),
                const SizedBox(height: 16),

                // Confidence Card
                _buildConfidenceCard(confidence, docType),
                const SizedBox(height: 16),

                // Extracted Fields
                if (fields.isNotEmpty) ...[
                  Text('Extracted Fields', style: AppTextStyles.headlineSm),
                  const SizedBox(height: 12),
                  _buildFieldsTable(fields),
                  const SizedBox(height: 24),
                ] else ...[
                  _buildFieldsTableFallback(doc),
                  const SizedBox(height: 24),
                ],

                // Smart Suggestion
                _buildSmartSuggestion(docType),
                const SizedBox(height: 32),

                // Action Buttons
                AppButton(
                  text: reviewStatus == 'verified'
                      ? 'View in Cabinet'
                      : 'Review & Verify',
                  onPressed: () => reviewStatus == 'verified'
                      ? _openCabinet(context)
                      : context.push(_reviewRoute(documentId)),
                ),
                if (reviewStatus == 'verified') ...[
                  const SizedBox(height: 12),
                  OutlinedButton.icon(
                    onPressed: () => showDialog<void>(
                      context: context,
                      builder: (_) => ShareDocumentDialog(
                        documentId: documentId.toString(),
                      ),
                    ),
                    icon: const Icon(Icons.share_rounded),
                    label: const Text('Share Document'),
                    style: OutlinedButton.styleFrom(
                      foregroundColor: AppColors.primary,
                      minimumSize: const Size(double.infinity, 50),
                      side: const BorderSide(color: AppColors.primary),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(12),
                      ),
                    ),
                  ),
                ],
                const SizedBox(height: 12),
                OutlinedButton.icon(
                  onPressed: () => _downloadOriginal(
                    context,
                    ref,
                    documentId.toString(),
                    doc['filename']?.toString() ?? 'document',
                  ),
                  icon: const Icon(Icons.download_rounded),
                  label: const Text('Download Original'),
                  style: OutlinedButton.styleFrom(
                    foregroundColor: AppColors.primary,
                    minimumSize: const Size(double.infinity, 50),
                    side: const BorderSide(color: AppColors.primary),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12),
                    ),
                  ),
                ),
                const SizedBox(height: 12),
                OutlinedButton.icon(
                  onPressed: () => context.go('/upload'),
                  icon: const Icon(Icons.document_scanner_rounded),
                  label: const Text('Scan Another Document'),
                  style: OutlinedButton.styleFrom(
                    foregroundColor: AppColors.primary,
                    minimumSize: const Size(double.infinity, 50),
                    side: const BorderSide(color: AppColors.primary),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12),
                    ),
                  ),
                ),
                const SizedBox(height: 24),
              ],
            ),
          );
        },
      ),
    );
  }

  Widget _buildStatusBanner(
    String reviewStatus,
    bool isTampered,
    List<String> flags,
  ) {
    final isVerified = reviewStatus == 'verified';
    final color = isVerified ? AppColors.success : AppColors.warning;
    final title = isVerified ? 'Verified' : 'Needs Review';
    final subtitle = isVerified
        ? 'Human review completed.'
        : 'AI extraction is ready for human verification.';

    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: color.withValues(alpha: 0.4)),
      ),
      child: Row(
        children: [
          Icon(
            isVerified ? Icons.verified_rounded : Icons.rate_review_rounded,
            color: color,
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: AppTextStyles.bodyMd.copyWith(
                    fontWeight: FontWeight.w700,
                    color: color,
                  ),
                ),
                Text(subtitle, style: AppTextStyles.bodySm),
                if (isTampered) ...[
                  const SizedBox(height: 4),
                  Text(
                    flags.isEmpty
                        ? 'Anomaly flag requires attention.'
                        : 'Anomaly: ${flags.join(' \u2022 ')}',
                    style: AppTextStyles.bodySm.copyWith(
                      color: AppColors.error,
                    ),
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildConfidenceCard(double confidence, String docType) {
    final confPercent = (confidence * 100).toInt();
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.surfaceLowest,
        borderRadius: BorderRadius.circular(16),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.04),
            blurRadius: 12,
            offset: const Offset(0, 4),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('OCR Confidence', style: AppTextStyles.bodySm),
                  Text(
                    '$confPercent%',
                    style: AppTextStyles.stat.copyWith(fontSize: 36),
                  ),
                ],
              ),
              Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: 14,
                  vertical: 8,
                ),
                decoration: BoxDecoration(
                  color: AppColors.secondaryContainer,
                  borderRadius: BorderRadius.circular(20),
                ),
                child: Text(
                  docType,
                  style: AppTextStyles.bodyMd.copyWith(
                    color: AppColors.primary,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          ClipRRect(
            borderRadius: BorderRadius.circular(8),
            child: LinearProgressIndicator(
              value: confidence,
              minHeight: 8,
              backgroundColor: AppColors.surfaceHigh,
              color: confidence > 0.85
                  ? AppColors.success
                  : confidence > 0.6
                  ? AppColors.warning
                  : AppColors.error,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildFieldsTable(List<Map<String, dynamic>> fields) {
    return Container(
      decoration: BoxDecoration(
        color: AppColors.surfaceLowest,
        borderRadius: BorderRadius.circular(16),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.04),
            blurRadius: 12,
            offset: const Offset(0, 4),
          ),
        ],
      ),
      child: Column(
        children: fields.asMap().entries.map((e) {
          final isLast = e.key == fields.length - 1;
          final field = e.value;
          final conf = (field['confidence'] as num?)?.toDouble() ?? 1.0;
          return Column(
            children: [
              Padding(
                padding: const EdgeInsets.symmetric(
                  horizontal: 16,
                  vertical: 12,
                ),
                child: Row(
                  children: [
                    Expanded(
                      flex: 2,
                      child: Text(
                        field['label'] ?? '',
                        style: AppTextStyles.bodySm.copyWith(
                          color: AppColors.textSecondary,
                        ),
                      ),
                    ),
                    Expanded(
                      flex: 3,
                      child: Text(
                        field['value'] ?? '\u2014',
                        style: AppTextStyles.bodyMd.copyWith(
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                    Container(
                      width: 40,
                      alignment: Alignment.centerRight,
                      child: Text(
                        '${(conf * 100).toInt()}%',
                        style: AppTextStyles.labelMd.copyWith(
                          color: conf > 0.85
                              ? AppColors.success
                              : AppColors.warning,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              if (!isLast)
                const Divider(
                  color: AppColors.divider,
                  height: 1,
                  indent: 16,
                  endIndent: 16,
                ),
            ],
          );
        }).toList(),
      ),
    );
  }

  Widget _buildFieldsTableFallback(Map<String, dynamic> doc) {
    // Show top-level document fields as fallback
    final entries = {
      'File Name': doc['filename'],
      'Document Type': doc['doc_type'],
      'Language': doc['language'],
      'Status': doc['status'],
    }.entries.where((e) => e.value != null).toList();

    if (entries.isEmpty) return const SizedBox.shrink();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Document Info', style: AppTextStyles.headlineSm),
        const SizedBox(height: 12),
        Container(
          decoration: BoxDecoration(
            color: AppColors.surfaceLowest,
            borderRadius: BorderRadius.circular(16),
          ),
          child: Column(
            children: entries.asMap().entries.map((e) {
              final isLast = e.key == entries.length - 1;
              return Column(
                children: [
                  Padding(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 16,
                      vertical: 12,
                    ),
                    child: Row(
                      children: [
                        Expanded(
                          flex: 2,
                          child: Text(
                            e.value.key,
                            style: AppTextStyles.bodySm.copyWith(
                              color: AppColors.textSecondary,
                            ),
                          ),
                        ),
                        Expanded(
                          flex: 3,
                          child: Text(
                            e.value.value.toString(),
                            style: AppTextStyles.bodyMd.copyWith(
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                  if (!isLast)
                    const Divider(
                      color: AppColors.divider,
                      height: 1,
                      indent: 16,
                      endIndent: 16,
                    ),
                ],
              );
            }).toList(),
          ),
        ),
      ],
    );
  }

  Widget _buildSmartSuggestion(String docType) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.secondaryContainer.withValues(alpha: 0.5),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: AppColors.primary.withValues(alpha: 0.2)),
      ),
      child: Row(
        children: [
          const Icon(Icons.auto_awesome_rounded, color: AppColors.primary),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Smart Suggestion',
                  style: AppTextStyles.labelMd.copyWith(
                    color: AppColors.primary,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  'AI will auto-file this under the $docType folder',
                  style: AppTextStyles.bodyMd.copyWith(
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
