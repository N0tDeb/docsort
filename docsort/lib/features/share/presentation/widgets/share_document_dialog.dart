import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../../core/network/dio_client.dart';

class ShareDocumentDialog extends ConsumerStatefulWidget {
  final String documentId;

  const ShareDocumentDialog({super.key, required this.documentId});

  @override
  ConsumerState<ShareDocumentDialog> createState() =>
      _ShareDocumentDialogState();
}

class _ShareDocumentDialogState extends ConsumerState<ShareDocumentDialog> {
  final _passwordController = TextEditingController();

  List<Map<String, dynamic>> _links = const [];
  int _expiresInHours = 24;
  bool _loading = true;
  bool _creating = false;
  String? _revokingId;
  String? _error;
  String? _createdUrl;
  String? _createdShareId;
  String? _copyMessage;

  @override
  void initState() {
    super.initState();
    _loadLinks();
  }

  @override
  void dispose() {
    _passwordController.dispose();
    super.dispose();
  }

  String _errorMessage(Object error) {
    if (error is DioException) {
      final data = error.response?.data;
      if (data is Map && data['detail'] != null) {
        return data['detail'].toString();
      }
    }
    return 'The sharing request failed. Please try again.';
  }

  String _formatExpiry(Object? raw) {
    if (raw == null) return 'Unknown expiry';
    final parsed = DateTime.tryParse(raw.toString());
    if (parsed == null) return raw.toString();

    final local = parsed.toLocal();
    String two(int value) => value.toString().padLeft(2, '0');

    return '${local.year}-${two(local.month)}-${two(local.day)} '
        '${two(local.hour)}:${two(local.minute)}';
  }

  Future<void> _loadLinks() async {
    if (mounted) {
      setState(() {
        _loading = true;
        _error = null;
      });
    }

    try {
      final dio = ref.read(dioProvider);
      final response = await dio.get('/share/links/${widget.documentId}');
      final data = response.data;

      final links = data is List
          ? data
                .whereType<Map>()
                .map((item) => Map<String, dynamic>.from(item))
                .toList()
          : <Map<String, dynamic>>[];

      if (!mounted) return;
      setState(() {
        _links = links;
        _loading = false;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = _errorMessage(error);
      });
    }
  }

  Future<void> _createLink() async {
    final password = _passwordController.text.trim();

    if (password.isNotEmpty && password.length < 6) {
      setState(() {
        _error = 'Share-link passwords must contain at least 6 characters.';
      });
      return;
    }

    setState(() {
      _creating = true;
      _error = null;
    });

    try {
      final dio = ref.read(dioProvider);
      final response = await dio.post(
        '/share/link',
        data: {
          'document_id': widget.documentId,
          'expires_in_hours': _expiresInHours,
          if (password.isNotEmpty) 'password': password,
        },
      );

      final data = Map<String, dynamic>.from(response.data as Map);
      final path = data['url']?.toString();

      if (path == null || path.isEmpty) {
        throw StateError('Share URL was not returned.');
      }

      final absoluteUrl = Uri.parse(
        dio.options.baseUrl,
      ).resolve(path).toString();

      if (!mounted) return;
      setState(() {
        _createdUrl = absoluteUrl;
        _createdShareId = data['share_id']?.toString();
        _creating = false;
        _passwordController.clear();
      });

      await _loadLinks();
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _creating = false;
        _error = _errorMessage(error);
      });
    }
  }

  Future<void> _copyCreatedLink() async {
    final value = _createdUrl;
    if (value == null) return;

    await Clipboard.setData(ClipboardData(text: value));

    if (!mounted) return;
    setState(() {
      _copyMessage = 'Share link copied to clipboard.';
    });
  }

  Future<void> _revokeLink(String shareId) async {
    setState(() {
      _revokingId = shareId;
      _error = null;
    });

    try {
      final dio = ref.read(dioProvider);
      await dio.delete('/share/link/$shareId');

      if (!mounted) return;
      setState(() {
        if (_createdShareId == shareId) {
          _createdShareId = null;
          _createdUrl = null;
        }
        _revokingId = null;
      });

      await _loadLinks();
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _revokingId = null;
        _error = _errorMessage(error);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Share Document'),
      content: SizedBox(
        width: 520,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'Create a secure, time-limited public link. '
                'A password is optional.',
              ),
              const SizedBox(height: 16),
              DropdownButtonFormField<int>(
                initialValue: _expiresInHours,
                decoration: const InputDecoration(
                  labelText: 'Link lifetime',
                  border: OutlineInputBorder(),
                ),
                items: const [
                  DropdownMenuItem(value: 1, child: Text('1 hour')),
                  DropdownMenuItem(value: 24, child: Text('24 hours')),
                  DropdownMenuItem(value: 72, child: Text('3 days')),
                  DropdownMenuItem(value: 168, child: Text('7 days')),
                ],
                onChanged: _creating
                    ? null
                    : (value) {
                        if (value != null) {
                          setState(() => _expiresInHours = value);
                        }
                      },
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _passwordController,
                obscureText: true,
                enabled: !_creating,
                decoration: const InputDecoration(
                  labelText: 'Password (optional)',
                  helperText: 'Minimum 6 characters when used',
                  border: OutlineInputBorder(),
                ),
              ),
              if (_error != null) ...[
                const SizedBox(height: 12),
                Text(
                  _error!,
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
              ],
              const SizedBox(height: 12),
              SizedBox(
                width: double.infinity,
                child: ElevatedButton.icon(
                  onPressed: _creating ? null : _createLink,
                  icon: _creating
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.link_rounded),
                  label: Text(_creating ? 'Creating...' : 'Create Link'),
                ),
              ),
              if (_createdUrl != null) ...[
                const SizedBox(height: 16),
                const Text(
                  'New share link',
                  style: TextStyle(fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 6),
                SelectableText(_createdUrl!),
                const SizedBox(height: 8),
                OutlinedButton.icon(
                  onPressed: _copyCreatedLink,
                  icon: const Icon(Icons.copy_rounded),
                  label: const Text('Copy Link'),
                ),
                if (_copyMessage != null) ...[
                  const SizedBox(height: 8),
                  Text(_copyMessage!),
                ],
              ],
              const SizedBox(height: 20),
              const Divider(),
              const SizedBox(height: 8),
              const Text(
                'Existing Links',
                style: TextStyle(fontWeight: FontWeight.w700),
              ),
              const SizedBox(height: 8),
              if (_loading)
                const Center(child: CircularProgressIndicator())
              else if (_links.isEmpty)
                const Text(
                  'No share links have been created for this document.',
                )
              else
                ..._links.map((link) {
                  final shareId = link['share_id']?.toString() ?? '';
                  final active = link['is_active'] == true;
                  final protected = link['password_protected'] == true;

                  return ListTile(
                    contentPadding: EdgeInsets.zero,
                    leading: Icon(
                      protected
                          ? Icons.lock_outline_rounded
                          : Icons.link_rounded,
                    ),
                    title: Text(active ? 'Active link' : 'Revoked link'),
                    subtitle: Text(
                      'Expires ${_formatExpiry(link['expires_at'])}'
                      '${protected ? ' - Password protected' : ''}',
                    ),
                    trailing: active
                        ? TextButton(
                            onPressed: _revokingId == shareId
                                ? null
                                : () => _revokeLink(shareId),
                            child: _revokingId == shareId
                                ? const SizedBox(
                                    width: 16,
                                    height: 16,
                                    child: CircularProgressIndicator(
                                      strokeWidth: 2,
                                    ),
                                  )
                                : const Text('Revoke'),
                          )
                        : null,
                  );
                }),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Close'),
        ),
      ],
    );
  }
}
