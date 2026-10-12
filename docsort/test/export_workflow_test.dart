import 'package:dio/dio.dart';
import 'package:docsort/core/network/dio_client.dart';
import 'package:docsort/features/cabinet/presentation/screens/cabinet_detail_screen.dart';
import 'package:docsort/features/upload/presentation/screens/result_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

Dio _documentDio() {
  final dio = Dio(BaseOptions(baseUrl: 'https://docsort.test'));
  dio.interceptors.add(
    InterceptorsWrapper(
      onRequest: (options, handler) {
        handler.resolve(
          Response<dynamic>(
            requestOptions: options,
            statusCode: 200,
            data: const {
              'id': 'doc-1',
              'filename': 'invoice.pdf',
              'doc_type': 'Invoice',
              'review_status': 'verified',
              'ocr_confidence': 0.95,
              'document_fields': <dynamic>[],
            },
          ),
        );
      },
    ),
  );
  return dio;
}

Dio _folderDio() {
  final dio = Dio(BaseOptions(baseUrl: 'https://docsort.test'));
  dio.interceptors.add(
    InterceptorsWrapper(
      onRequest: (options, handler) {
        handler.resolve(
          Response<dynamic>(
            requestOptions: options,
            statusCode: 200,
            data: const <dynamic>[],
          ),
        );
      },
    ),
  );
  return dio;
}

void main() {
  testWidgets('verified document exposes download action', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [dioProvider.overrideWithValue(_documentDio())],
        child: const MaterialApp(home: ResultScreen(docId: 'doc-1')),
      ),
    );

    await tester.pumpAndSettle();

    expect(find.text('Download Original'), findsOneWidget);
  });

  testWidgets('department folder exposes export action', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [dioProvider.overrideWithValue(_folderDio())],
        child: const MaterialApp(
          home: CabinetDetailScreen(folderId: 'folder-1'),
        ),
      ),
    );

    await tester.pumpAndSettle();

    expect(find.byTooltip('Export Folder'), findsOneWidget);
  });
}
