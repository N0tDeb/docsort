import 'package:dio/dio.dart';
import 'package:docsort/core/network/dio_client.dart';
import 'package:docsort/features/upload/presentation/providers/upload_provider.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('processing job can be restored after refresh', () async {
    final dio = Dio(BaseOptions(baseUrl: 'https://docsort.test'));

    dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) {
          expect(options.path, '/upload/status/job-123');

          handler.resolve(
            Response<dynamic>(
              requestOptions: options,
              statusCode: 200,
              data: <String, dynamic>{
                'status': 'done',
                'document_id': 'doc-456',
                'step': 5,
                'progress_pct': 1.0,
              },
            ),
          );
        },
      ),
    );

    final container = ProviderContainer(
      overrides: [dioProvider.overrideWithValue(dio)],
    );
    addTearDown(container.dispose);

    final notifier = container.read(uploadProvider.notifier);

    notifier.resumeJob('job-123');

    expect(container.read(uploadProvider).jobId, 'job-123');
    expect(container.read(uploadProvider).status, UploadStatus.processing);

    await notifier.pollStatus();

    final state = container.read(uploadProvider);
    expect(state.status, UploadStatus.done);
    expect(state.documentId, 'doc-456');
  });
}
