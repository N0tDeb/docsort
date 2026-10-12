import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../../../core/network/dio_client.dart';
import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:file_picker/file_picker.dart';

enum UploadStatus { idle, uploading, processing, done, error }

class UploadState {
  final UploadStatus status;
  final String? jobId;
  final String? documentId;
  final String? errorMessage;
  final double progress;
  final int currentStep;
  final Map<String, dynamic>? extractedData; // Full doc+fields from backend
  final String? sourceFilePath;

  UploadState({
    required this.status,
    this.jobId,
    this.documentId,
    this.errorMessage,
    this.progress = 0.0,
    this.currentStep = 0,
    this.extractedData,
    this.sourceFilePath,
  });

  factory UploadState.initial() => UploadState(status: UploadStatus.idle);
}

final uploadProvider = NotifierProvider<UploadNotifier, UploadState>(
  UploadNotifier.new,
);

String _uploadErrorMessage(DioException error) {
  final data = error.response?.data;
  if (data is Map) {
    final detail = data['detail'];
    if (detail is String && detail.trim().isNotEmpty) {
      return detail.trim();
    }
  }
  return 'Upload failed. Please check your connection and try again.';
}

class UploadNotifier extends Notifier<UploadState> {
  CancelToken? _cancelToken;
  int _consecutivePollFailures = 0;

  @override
  UploadState build() => UploadState.initial();

  void resumeJob(String jobId) {
    final id = jobId.trim();
    if (id.isEmpty) return;

    _cancelToken?.cancel('Replacing processing job');
    _cancelToken = CancelToken();
    _consecutivePollFailures = 0;

    state = UploadState(
      status: UploadStatus.processing,
      jobId: id,
      progress: 0.15,
      currentStep: 1,
    );
  }

  Future<bool> uploadDocument(String filePath) async {
    try {
      final multipart = await MultipartFile.fromFile(filePath);
      return await _uploadMultipart(multipart, sourceFilePath: filePath);
    } catch (_) {
      state = UploadState(
        status: UploadStatus.error,
        errorMessage:
            'The selected file could not be read. Please choose it again.',
        sourceFilePath: filePath,
      );
      return false;
    }
  }

  /// Uploads a file selected with file_picker. On Web, [PlatformFile.path]
  /// is not a filesystem path, so the picker is configured to provide bytes
  /// and this method sends them directly. Native platforms keep the existing
  /// path-based behavior when bytes are not populated.
  Future<bool> uploadPickedFile(PlatformFile file) async {
    final bytes = file.bytes;
    if (bytes != null) {
      return _uploadMultipart(
        MultipartFile.fromBytes(bytes, filename: file.name),
        sourceFilePath: kIsWeb ? null : file.path,
      );
    }

    final path = file.path;
    if (path == null || path.trim().isEmpty) {
      state = UploadState(
        status: UploadStatus.error,
        errorMessage:
            'The selected file could not be read. Please choose it again.',
      );
      return false;
    }

    try {
      return await _uploadMultipart(
        await MultipartFile.fromFile(path, filename: file.name),
        sourceFilePath: path,
      );
    } catch (_) {
      state = UploadState(
        status: UploadStatus.error,
        errorMessage:
            'The selected file could not be read. Please choose it again.',
        sourceFilePath: path,
      );
      return false;
    }
  }

  Future<bool> _uploadMultipart(
    MultipartFile multipart, {
    String? sourceFilePath,
  }) async {
    // Reset any previous token.
    _cancelToken?.cancel('Cancelled by user');
    _cancelToken = CancelToken();
    _consecutivePollFailures = 0;

    state = UploadState(
      status: UploadStatus.uploading,
      progress: 0.0,
      sourceFilePath: sourceFilePath,
    );
    try {
      final dio = ref.read(dioProvider);
      final formData = FormData.fromMap({'file': multipart});

      final response = await dio.post(
        '/upload',
        data: formData,
        cancelToken: _cancelToken,
        onSendProgress: (count, total) {
          if (total > 0 && (_cancelToken?.isCancelled == false)) {
            final fileProgress = count / total;
            // Cap upload progress at 15% of the total UI progress bar
            // so processing starts at 15%.
            state = UploadState(
              status: UploadStatus.uploading,
              progress: fileProgress * 0.15,
              currentStep: 0,
              sourceFilePath: sourceFilePath,
            );
          }
        },
      );

      final jobId = response.data['job_id'] ?? response.data['id'];

      // Start processing phase.
      state = UploadState(
        status: UploadStatus.processing,
        jobId: jobId,
        progress: 0.15,
        currentStep: 1,
        sourceFilePath: sourceFilePath,
      );
      return true;
    } on DioException catch (e) {
      if (CancelToken.isCancel(e)) {
        // User cancelled, don't show an error state.
        state = UploadState.initial();
        return false;
      }
      state = UploadState(
        status: UploadStatus.error,
        errorMessage: _uploadErrorMessage(e),
        sourceFilePath: sourceFilePath,
      );
      return false;
    } catch (_) {
      state = UploadState(
        status: UploadStatus.error,
        errorMessage: 'Upload failed. Please try again.',
        sourceFilePath: sourceFilePath,
      );
      return false;
    }
  }

  Future<void> pollStatus() async {
    if (state.jobId == null || _cancelToken?.isCancelled == true) return;
    try {
      final dio = ref.read(dioProvider);
      final response = await dio.get(
        '/upload/status/${state.jobId}',
        cancelToken: _cancelToken,
      );
      _consecutivePollFailures = 0;
      final data = response.data as Map<String, dynamic>;

      final remoteStatus = data['status'] as String? ?? 'processing';
      final docId = data['document_id'] as String?;
      final step = (data['step'] as num?)?.toInt() ?? state.currentStep;
      final progressPct =
          (data['progress_pct'] as num?)?.toDouble() ?? (step / 5.0);
      final extractedData = data['extracted_data'] as Map<String, dynamic>?;

      if (remoteStatus == 'done') {
        state = UploadState(
          status: UploadStatus.done,
          jobId: state.jobId,
          documentId: docId,
          progress: 1.0,
          currentStep: 5,
          extractedData: extractedData,
          errorMessage: data['error_message'],
          sourceFilePath: state.sourceFilePath,
        );
      } else if (remoteStatus == 'failed') {
        state = UploadState(
          status: UploadStatus.error,
          errorMessage: data['error_message'] ?? 'Processing failed',
          sourceFilePath: state.sourceFilePath,
        );
      } else {
        state = UploadState(
          status: UploadStatus.processing,
          jobId: state.jobId,
          currentStep: step.clamp(0, 5),
          progress: progressPct.clamp(0.0, 1.0),
          sourceFilePath: state.sourceFilePath,
        );
      }
    } on DioException catch (e) {
      if (CancelToken.isCancel(e)) return;

      _consecutivePollFailures++;
      if (_consecutivePollFailures >= 3) {
        state = UploadState(
          status: UploadStatus.error,
          jobId: state.jobId,
          errorMessage:
              'Connection lost while checking processing status. Please try again.',
          sourceFilePath: state.sourceFilePath,
        );
      }
    } catch (_) {
      _consecutivePollFailures++;
      if (_consecutivePollFailures >= 3) {
        state = UploadState(
          status: UploadStatus.error,
          jobId: state.jobId,
          errorMessage: 'Processing status could not be recovered.',
          sourceFilePath: state.sourceFilePath,
        );
      }
    }
  }

  void reset() {
    _cancelToken?.cancel('Cancelled by user');
    _consecutivePollFailures = 0;
    state = UploadState.initial();
  }

  Future<void> uploadMultipleDocuments(List<String> filePaths) async {
    final dio = ref.read(dioProvider);
    // Execute sequentially in the background.
    for (final path in filePaths) {
      try {
        final formData = FormData.fromMap({
          'file': await MultipartFile.fromFile(path),
        });
        await dio.post('/upload', data: formData);
      } catch (_) {
        // Suppress errors for background batch uploads. They can be tracked in
        // backend logs or a future bulk error view.
        if (kDebugMode) debugPrint('Background batch upload failed.');
      }
    }
  }

  Future<void> uploadMultiplePickedDocuments(List<PlatformFile> files) async {
    final dio = ref.read(dioProvider);
    // Execute sequentially in the background and preserve each original name.
    for (final file in files) {
      try {
        MultipartFile multipart;
        if (file.bytes != null) {
          multipart = MultipartFile.fromBytes(file.bytes!, filename: file.name);
        } else if (file.path != null && file.path!.trim().isNotEmpty) {
          multipart = await MultipartFile.fromFile(
            file.path!,
            filename: file.name,
          );
        } else {
          if (kDebugMode) {
            debugPrint('Skipped unreadable picked file: ${file.name}');
          }
          continue;
        }
        await dio.post('/upload', data: FormData.fromMap({'file': multipart}));
      } catch (_) {
        if (kDebugMode) debugPrint('Background batch upload failed.');
      }
    }
  }
}
