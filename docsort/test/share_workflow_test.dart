import 'package:dio/dio.dart';
import 'package:docsort/core/network/dio_client.dart';
import 'package:docsort/features/share/presentation/widgets/share_document_dialog.dart';
import 'package:docsort/features/upload/presentation/screens/result_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

Dio _resultScreenDio() {
  final dio = Dio(BaseOptions(baseUrl: 'https://docsort.test'));

  dio.interceptors.add(
    InterceptorsWrapper(
      onRequest: (options, handler) {
        expect(options.method, 'GET');
        expect(options.path, '/cabinet/documents/doc-1');

        handler.resolve(
          Response<dynamic>(
            requestOptions: options,
            statusCode: 200,
            data: const {
              'id': 'doc-1',
              'filename': 'finance_department_test.pdf',
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

class _ShareApiState {
  int createCalls = 0;
  int revokeCalls = 0;
  bool created = false;
  bool revoked = false;
}

Dio _shareDialogDio(_ShareApiState state) {
  final dio = Dio(BaseOptions(baseUrl: 'https://docsort.test'));

  dio.interceptors.add(
    InterceptorsWrapper(
      onRequest: (options, handler) {
        if (options.method == 'GET' && options.path == '/share/links/doc-1') {
          final links = state.created && !state.revoked
              ? <Map<String, dynamic>>[
                  {
                    'share_id': 'share-1',
                    'expires_at': '2026-10-02T00:00:00Z',
                    'is_active': true,
                  },
                ]
              : <Map<String, dynamic>>[];

          handler.resolve(
            Response<dynamic>(
              requestOptions: options,
              statusCode: 200,
              data: links,
            ),
          );
          return;
        }

        if (options.method == 'POST' && options.path == '/share/link') {
          final body = Map<String, dynamic>.from(options.data as Map);

          expect(body['document_id'], 'doc-1');
          expect(body['expires_in_hours'], 24);
          expect(body['password'], 'Secret123');

          state.createCalls += 1;
          state.created = true;

          handler.resolve(
            Response<dynamic>(
              requestOptions: options,
              statusCode: 200,
              data: const {
                'share_id': 'share-1',
                'url': '/share/access/token-1',
                'expires_at': '2026-10-02T00:00:00Z',
              },
            ),
          );
          return;
        }

        if (options.method == 'DELETE' &&
            options.path == '/share/link/share-1') {
          state.revokeCalls += 1;
          state.revoked = true;

          handler.resolve(
            Response<dynamic>(
              requestOptions: options,
              statusCode: 200,
              data: const {'share_id': 'share-1', 'is_active': false},
            ),
          );
          return;
        }

        handler.reject(
          DioException(
            requestOptions: options,
            response: Response<dynamic>(
              requestOptions: options,
              statusCode: 500,
              data: {
                'detail':
                    'Unexpected test request: ${options.method} ${options.path}',
              },
            ),
          ),
        );
      },
    ),
  );

  return dio;
}

void main() {
  testWidgets('verified document exposes secure sharing controls', (
    tester,
  ) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [dioProvider.overrideWithValue(_resultScreenDio())],
        child: const MaterialApp(home: ResultScreen(docId: 'doc-1')),
      ),
    );

    await tester.pumpAndSettle();

    expect(find.text('Share Document'), findsOneWidget);
  });

  testWidgets('share dialog creates and revokes a protected link', (
    tester,
  ) async {
    final state = _ShareApiState();

    await tester.pumpWidget(
      ProviderScope(
        overrides: [dioProvider.overrideWithValue(_shareDialogDio(state))],
        child: const MaterialApp(
          home: Scaffold(body: ShareDocumentDialog(documentId: 'doc-1')),
        ),
      ),
    );

    await tester.pumpAndSettle();

    expect(
      find.text('No share links have been created for this document.'),
      findsOneWidget,
    );

    await tester.enterText(find.byType(TextField), 'Secret123');
    await tester.tap(find.text('Create Link'));
    await tester.pumpAndSettle();

    expect(state.createCalls, 1);
    expect(find.text('New share link'), findsOneWidget);
    expect(
      find.text('https://docsort.test/share/access/token-1'),
      findsOneWidget,
    );
    expect(find.text('Active link'), findsOneWidget);
    expect(find.text('Revoke'), findsOneWidget);

    final revokeButton = find.text('Revoke');
    await tester.ensureVisible(revokeButton);
    await tester.pumpAndSettle();
    await tester.tap(revokeButton);
    await tester.pumpAndSettle();

    expect(state.revokeCalls, 1);
    expect(
      find.text('No share links have been created for this document.'),
      findsOneWidget,
    );
  });
}
