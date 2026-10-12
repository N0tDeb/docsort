import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../../core/network/dio_client.dart';
import '../../../../core/services/file_export_service.dart';
import '../../../../core/widgets/app_snackbar.dart';
import '../../../../core/theme/app_colors.dart';
import '../../../../core/theme/app_text_styles.dart';

const _folderPageSize = 100;
typedef FolderPageRequest = ({String folderId, int page});

final folderDocumentsProvider = FutureProvider.autoDispose
    .family<List<Map<String, dynamic>>, FolderPageRequest>((
      ref,
      request,
    ) async {
      final dio = ref.watch(dioProvider);
      final response = await dio.get(
        '/cabinet/${request.folderId}/documents',
        queryParameters: {
          'limit': _folderPageSize,
          'offset': request.page * _folderPageSize,
        },
      );
      return List<Map<String, dynamic>>.from(response.data ?? []);
    });

class CabinetDetailScreen extends ConsumerStatefulWidget {
  final String folderId;

  const CabinetDetailScreen({super.key, required this.folderId});

  @override
  ConsumerState<CabinetDetailScreen> createState() =>
      _CabinetDetailScreenState();
}

class _CabinetDetailScreenState extends ConsumerState<CabinetDetailScreen> {
  int _page = 0;

  FolderPageRequest get _request => (folderId: widget.folderId, page: _page);

  String get _title {
    if (widget.folderId.startsWith('personal_')) {
      return widget.folderId.substring(9);
    }
    if (widget.folderId == 'unassigned') return 'My Uploads';
    return 'Documents';
  }

  Future<void> _exportFolder(String format) async {
    try {
      await ref
          .read(fileExportServiceProvider)
          .download(
            dio: ref.read(dioProvider),
            path: '/export/folder/${widget.folderId}',
            fallbackFileName: 'folder-export.$format',
            queryParameters: {'format': format},
          );

      if (mounted) {
        AppSnackbar.showSuccess(context, 'Folder export started.');
      }
    } catch (_) {
      if (mounted) {
        AppSnackbar.showError(context, 'Could not export folder.');
      }
    }
  }

  Future<void> _showExportDialog() async {
    final format = await showDialog<String>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Export Folder'),
        content: const Text('Choose an export format.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext),
            child: const Text('Cancel'),
          ),
          OutlinedButton(
            onPressed: () => Navigator.pop(dialogContext, 'csv'),
            child: const Text('CSV'),
          ),
          ElevatedButton(
            onPressed: () => Navigator.pop(dialogContext, 'zip'),
            child: const Text('ZIP'),
          ),
        ],
      ),
    );

    if (format != null) {
      await _exportFolder(format);
    }
  }

  Future<void> _refresh() async {
    ref.invalidate(folderDocumentsProvider(_request));
  }

  @override
  Widget build(BuildContext context) {
    final docsAsync = ref.watch(folderDocumentsProvider(_request));

    return Scaffold(
      backgroundColor: AppColors.background,
      appBar: AppBar(
        title: Text(
          _title,
          style: const TextStyle(fontWeight: FontWeight.bold),
        ),
        backgroundColor: AppColors.background,
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_rounded),
          onPressed: () =>
              context.canPop() ? context.pop() : context.go('/cabinet'),
        ),
        actions: [
          if (!widget.folderId.startsWith('personal_') &&
              widget.folderId != 'unassigned')
            IconButton(
              tooltip: 'Export Folder',
              icon: const Icon(
                Icons.download_rounded,
                color: AppColors.primary,
              ),
              onPressed: _showExportDialog,
            ),
          IconButton(
            icon: const Icon(Icons.refresh_rounded, color: AppColors.primary),
            onPressed: () => ref.invalidate(folderDocumentsProvider(_request)),
          ),
        ],
      ),
      body: Hero(
        tag: 'folder_${widget.folderId}',
        child: Material(
          color: Colors.transparent,
          child: docsAsync.when(
            loading: () => const Center(
              child: CircularProgressIndicator(color: AppColors.primary),
            ),
            error: (_, _) => _ErrorState(
              onRetry: () => ref.invalidate(folderDocumentsProvider(_request)),
            ),
            data: (docs) => Column(
              children: [
                Expanded(
                  child: RefreshIndicator(
                    onRefresh: _refresh,
                    child: docs.isEmpty
                        ? _EmptyFolder(onUpload: () => context.push('/upload'))
                        : ListView.separated(
                            padding: const EdgeInsets.all(16),
                            itemCount: docs.length,
                            separatorBuilder: (_, _) =>
                                const SizedBox(height: 10),
                            itemBuilder: (context, index) =>
                                _buildDocumentCard(context, docs[index]),
                          ),
                  ),
                ),
                if (_page > 0 || docs.length == _folderPageSize)
                  _PaginationBar(
                    page: _page,
                    canGoNext: docs.length == _folderPageSize,
                    onPrevious: _page == 0
                        ? null
                        : () => setState(() => _page -= 1),
                    onNext: docs.length == _folderPageSize
                        ? () => setState(() => _page += 1)
                        : null,
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildDocumentCard(BuildContext context, Map<String, dynamic> doc) {
    final isTampered = doc['is_tampered'] == true;
    final confidence = (doc['ocr_confidence'] as num?)?.toDouble() ?? 0.0;
    final uploadedBy = doc['users']?['name'] ?? 'Unknown';
    final createdAt = doc['created_at']?.toString() ?? '';
    final shortDate = createdAt.length >= 10 ? createdAt.substring(0, 10) : '';
    final fields = List<Map<String, dynamic>>.from(
      doc['document_fields'] ?? [],
    );
    final reviewStatus = doc['review_status'] as String? ?? 'needs_review';
    final docId = doc['id']?.toString();

    return Container(
      decoration: BoxDecoration(
        color: AppColors.surfaceLowest,
        borderRadius: BorderRadius.circular(14),
        border: isTampered
            ? Border.all(
                color: AppColors.error.withValues(alpha: 0.5),
                width: 1.5,
              )
            : null,
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.04),
            blurRadius: 10,
            offset: const Offset(0, 3),
          ),
        ],
      ),
      child: Dismissible(
        key: Key(docId ?? 'missing-document-id'),
        direction: DismissDirection.endToStart,
        background: Container(
          alignment: Alignment.centerRight,
          padding: const EdgeInsets.only(right: 20),
          decoration: BoxDecoration(
            color: AppColors.error,
            borderRadius: BorderRadius.circular(14),
          ),
          child: const Icon(Icons.delete_outline_rounded, color: Colors.white),
        ),
        confirmDismiss: (_) async => showDialog<bool>(
          context: context,
          builder: (dialogContext) => AlertDialog(
            title: const Text('Delete Document'),
            content: const Text(
              'Are you sure you want to delete this document?',
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(dialogContext, false),
                child: const Text('Cancel'),
              ),
              TextButton(
                onPressed: () => Navigator.pop(dialogContext, true),
                child: const Text(
                  'Delete',
                  style: TextStyle(color: AppColors.error),
                ),
              ),
            ],
          ),
        ),
        onDismissed: (_) async {
          if (docId == null) return;
          try {
            final dio = ref.read(dioProvider);
            await dio.delete('/cabinet/documents/$docId');
            ref.invalidate(folderDocumentsProvider(_request));
          } catch (_) {
            if (!context.mounted) return;
            ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(content: Text('Failed to delete document')),
            );
            ref.invalidate(folderDocumentsProvider(_request));
          }
        },
        child: Material(
          color: Colors.transparent,
          borderRadius: BorderRadius.circular(14),
          child: ListTile(
            contentPadding: const EdgeInsets.symmetric(
              horizontal: 16,
              vertical: 10,
            ),
            leading: Container(
              width: 46,
              height: 46,
              decoration: BoxDecoration(
                color: isTampered
                    ? AppColors.error.withValues(alpha: 0.1)
                    : AppColors.secondaryContainer,
                borderRadius: BorderRadius.circular(12),
              ),
              child: Icon(
                isTampered
                    ? Icons.warning_amber_rounded
                    : Icons.description_rounded,
                color: isTampered ? AppColors.error : AppColors.primary,
              ),
            ),
            title: Text(
              doc['filename']?.toString() ?? 'Document',
              style: AppTextStyles.bodyMd.copyWith(fontWeight: FontWeight.w700),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
            subtitle: Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Wrap(
                    spacing: 6,
                    runSpacing: 4,
                    children: [
                      _Tag(
                        doc['doc_type']?.toString() ?? 'Unknown',
                        AppColors.primary,
                      ),
                      _Tag(
                        'OCR ${(confidence * 100).toInt()}%',
                        confidence > 0.85
                            ? AppColors.success
                            : AppColors.warning,
                      ),
                      _Tag(
                        reviewStatus == 'verified'
                            ? 'Verified'
                            : 'Needs Review',
                        reviewStatus == 'verified'
                            ? AppColors.success
                            : AppColors.warning,
                      ),
                      if (isTampered) _Tag('Tampered', AppColors.error),
                    ],
                  ),
                  if (fields.isNotEmpty) ...[
                    const SizedBox(height: 4),
                    Text(
                      fields
                          .take(2)
                          .map(
                            (field) => '${field['label']}: ${field['value']}',
                          )
                          .join('  •  '),
                      style: AppTextStyles.bodySm,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ],
                  const SizedBox(height: 2),
                  Text(
                    'By $uploadedBy  •  $shortDate',
                    style: AppTextStyles.bodySm,
                  ),
                ],
              ),
            ),
            trailing: const Icon(
              Icons.chevron_right_rounded,
              color: AppColors.textSecondary,
            ),
            onTap: docId == null
                ? null
                : () => context
                      .go('/result/$docId?from=${Uri.encodeComponent("/cabinet/${widget.folderId}")}'),
          ),
        ),
      ),
    );
  }
}

class _ErrorState extends StatelessWidget {
  final VoidCallback onRetry;

  const _ErrorState({required this.onRetry});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(
              Icons.error_outline_rounded,
              size: 60,
              color: AppColors.error,
            ),
            const SizedBox(height: 16),
            Text(
              'Could not load these documents. Please try again.',
              textAlign: TextAlign.center,
              style: AppTextStyles.bodyMd.copyWith(color: AppColors.error),
            ),
            const SizedBox(height: 16),
            ElevatedButton.icon(
              onPressed: onRetry,
              icon: const Icon(Icons.refresh),
              label: const Text('Retry'),
            ),
          ],
        ),
      ),
    );
  }
}

class _EmptyFolder extends StatelessWidget {
  final VoidCallback onUpload;

  const _EmptyFolder({required this.onUpload});

  @override
  Widget build(BuildContext context) {
    return CustomScrollView(
      physics: const AlwaysScrollableScrollPhysics(),
      slivers: [
        SliverFillRemaining(
          child: Center(
            child: Padding(
              padding: const EdgeInsets.all(40),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(
                    Icons.folder_open_rounded,
                    size: 72,
                    color: AppColors.outlineVariant,
                  ),
                  const SizedBox(height: 16),
                  Text('This folder is empty', style: AppTextStyles.h2),
                  const SizedBox(height: 8),
                  Text(
                    'Upload a document to populate this folder.',
                    style: AppTextStyles.bodyMd.copyWith(
                      color: AppColors.textSecondary,
                    ),
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 24),
                  ElevatedButton.icon(
                    onPressed: onUpload,
                    icon: const Icon(Icons.upload_file_rounded),
                    label: const Text('Upload Document'),
                  ),
                ],
              ),
            ),
          ),
        ),
      ],
    );
  }
}

class _PaginationBar extends StatelessWidget {
  final int page;
  final bool canGoNext;
  final VoidCallback? onPrevious;
  final VoidCallback? onNext;

  const _PaginationBar({
    required this.page,
    required this.canGoNext,
    this.onPrevious,
    this.onNext,
  });

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
        child: Row(
          children: [
            if (onPrevious != null)
              OutlinedButton.icon(
                onPressed: onPrevious,
                icon: const Icon(Icons.chevron_left_rounded),
                label: const Text('Previous'),
              ),
            const Spacer(),
            Text('Page ${page + 1}', style: AppTextStyles.bodySm),
            const Spacer(),
            if (canGoNext)
              ElevatedButton.icon(
                onPressed: onNext,
                icon: const Icon(Icons.chevron_right_rounded),
                label: const Text('Next'),
              ),
          ],
        ),
      ),
    );
  }
}

class _Tag extends StatelessWidget {
  final String label;
  final Color color;

  const _Tag(this.label, this.color);

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(
        label,
        style: TextStyle(
          fontSize: 10,
          fontWeight: FontWeight.w600,
          color: color,
        ),
      ),
    );
  }
}
