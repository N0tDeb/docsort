import 'dart:io';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:docsort/core/network/dio_client.dart';
import 'package:docsort/features/upload/presentation/providers/upload_provider.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:file_picker/file_picker.dart';
import 'package:flutter_test/flutter_test.dart';

class UploadBackend {
  Map<String, dynamic> statusPayload = {
    'status': 'processing',
    'step': 2,
    'progress_pct': 0.4,
  };
  bool failPoll = false;
  String? uploadErrorDetail;
  bool failUploadConnection = false;

  Dio createDio() {
    final dio = Dio(BaseOptions(baseUrl: 'https://docsort.test'));
    dio.interceptors.add(InterceptorsWrapper(onRequest: (options, handler) {
      if (options.path == '/upload') {
        if (failUploadConnection) {
          handler.reject(DioException(
            requestOptions: options,
            type: DioExceptionType.connectionError,
            error: 'socket details should not reach UI',
          ));
          return;
        }
        if (uploadErrorDetail != null) {
          handler.reject(DioException(
            requestOptions: options,
            response: Response<dynamic>(
              requestOptions: options,
              statusCode: 400,
              data: {'detail': uploadErrorDetail},
            ),
            type: DioExceptionType.badResponse,
          ));
          return;
        }
        handler.resolve(Response<dynamic>(
          requestOptions: options,
          statusCode: 202,
          data: const {'job_id': 'job-1'},
        ));
        return;
      }

      if (options.path == '/upload/status/job-1') {
        if (failPoll) {
          handler.reject(DioException(
            requestOptions: options,
            type: DioExceptionType.connectionError,
            error: 'temporary outage',
          ));
          return;
        }
        handler.resolve(Response<dynamic>(
          requestOptions: options,
          statusCode: 200,
          data: statusPayload,
        ));
        return;
      }

      fail('Unexpected request path: ${options.path}');
    }));
    return dio;
  }
}

Future<File> _temporaryDocument() async {
  final directory = await Directory.systemTemp.createTemp('docsort-upload-test-');
  final file = File('${directory.path}/sample.pdf');
  await file.writeAsBytes(const [0x25, 0x50, 0x44, 0x46]);
  addTearDown(() async {
    if (await directory.exists()) {
      await directory.delete(recursive: true);
    }
  });
  return file;
}

void main() {
  test('byte-backed picked file is admitted without a filesystem path', () async {
    final backend = UploadBackend();
    final container = ProviderContainer.test(overrides: [
      dioProvider.overrideWithValue(backend.createDio()),
    ]);

    final picked = PlatformFile(
      name: 'browser-sample.pdf',
      size: 4,
      bytes: Uint8List.fromList(const [0x25, 0x50, 0x44, 0x46]),
    );

    final admitted =
        await container.read(uploadProvider.notifier).uploadPickedFile(picked);

    expect(admitted, isTrue);
    final state = container.read(uploadProvider);
    expect(state.status, UploadStatus.processing);
    expect(state.jobId, 'job-1');
    expect(state.sourceFilePath, isNull);
  });

  test('upload admission then completed poll produces done state', () async {
    final backend = UploadBackend();
    final file = await _temporaryDocument();
    final container = ProviderContainer.test(overrides: [
      dioProvider.overrideWithValue(backend.createDio()),
    ]);
    final notifier = container.read(uploadProvider.notifier);

    final admitted = await notifier.uploadDocument(file.path);
    expect(admitted, isTrue);
    expect(container.read(uploadProvider).status, UploadStatus.processing);
    expect(container.read(uploadProvider).jobId, 'job-1');

    backend.statusPayload = {
      'status': 'done',
      'document_id': 'doc-1',
      'step': 5,
      'progress_pct': 1.0,
      'extracted_data': {
        'document': {'id': 'doc-1'}
      },
    };
    await notifier.pollStatus();

    final state = container.read(uploadProvider);
    expect(state.status, UploadStatus.done);
    expect(state.documentId, 'doc-1');
    expect(state.progress, 1.0);
    expect(state.extractedData, isNotNull);
  });


  test('upload admission keeps intentionally public backend validation detail', () async {
    final backend = UploadBackend()
      ..uploadErrorDetail = 'Unsupported file type';
    final file = await _temporaryDocument();
    final container = ProviderContainer.test(overrides: [
      dioProvider.overrideWithValue(backend.createDio()),
    ]);

    final admitted = await container.read(uploadProvider.notifier).uploadDocument(file.path);

    expect(admitted, isFalse);
    final state = container.read(uploadProvider);
    expect(state.status, UploadStatus.error);
    expect(state.errorMessage, 'Unsupported file type');
  });

  test('upload transport failures use generic user-facing copy', () async {
    final backend = UploadBackend()..failUploadConnection = true;
    final file = await _temporaryDocument();
    final container = ProviderContainer.test(overrides: [
      dioProvider.overrideWithValue(backend.createDio()),
    ]);

    final admitted = await container.read(uploadProvider.notifier).uploadDocument(file.path);

    expect(admitted, isFalse);
    final state = container.read(uploadProvider);
    expect(state.status, UploadStatus.error);
    expect(state.errorMessage, 'Upload failed. Please check your connection and try again.');
    expect(state.errorMessage, isNot(contains('socket details')));
  });

  test('failed backend job becomes visible processing error', () async {
    final backend = UploadBackend();
    final file = await _temporaryDocument();
    final container = ProviderContainer.test(overrides: [
      dioProvider.overrideWithValue(backend.createDio()),
    ]);
    final notifier = container.read(uploadProvider.notifier);

    await notifier.uploadDocument(file.path);
    backend.statusPayload = {
      'status': 'failed',
      'error_message': 'Document could not be processed',
    };
    await notifier.pollStatus();

    final state = container.read(uploadProvider);
    expect(state.status, UploadStatus.error);
    expect(state.errorMessage, 'Document could not be processed');
    expect(state.sourceFilePath, file.path);
  });

  test('one transient poll failure keeps processing state for retry', () async {
    final backend = UploadBackend();
    final file = await _temporaryDocument();
    final container = ProviderContainer.test(overrides: [
      dioProvider.overrideWithValue(backend.createDio()),
    ]);
    final notifier = container.read(uploadProvider.notifier);

    await notifier.uploadDocument(file.path);
    backend.failPoll = true;
    await notifier.pollStatus();

    final state = container.read(uploadProvider);
    expect(state.status, UploadStatus.processing);
    expect(state.jobId, 'job-1');
  });

  test('reset clears accepted-job UI state', () async {
    final backend = UploadBackend();
    final file = await _temporaryDocument();
    final container = ProviderContainer.test(overrides: [
      dioProvider.overrideWithValue(backend.createDio()),
    ]);
    final notifier = container.read(uploadProvider.notifier);

    await notifier.uploadDocument(file.path);
    notifier.reset();

    final state = container.read(uploadProvider);
    expect(state.status, UploadStatus.idle);
    expect(state.jobId, isNull);
    expect(state.documentId, isNull);
    expect(state.progress, 0.0);
  });
}
