import 'dart:convert';

const int maxAuthEmailLength = 320;
const int maxAuthPasswordLength = 128;
const int maxBcryptPasswordBytes = 72;
const int maxFullNameLength = 120;
const int maxDepartmentCodeLength = 64;

String? validateAuthEmail(String? value) {
  final email = (value ?? '').trim();
  if (email.isEmpty) return 'Email address is required.';
  if (email.length > maxAuthEmailLength) {
    return 'Email address is too long.';
  }

  final atIndex = email.indexOf('@');
  final hasSingleAt = atIndex > 0 &&
      atIndex == email.lastIndexOf('@') &&
      atIndex < email.length - 1;
  final hasWhitespace = RegExp(r'\s').hasMatch(email);
  if (!hasSingleAt || hasWhitespace) {
    return 'Enter a valid email address.';
  }
  return null;
}

String? validateLoginPassword(String? value) {
  final password = value ?? '';
  if (password.isEmpty) return 'Password is required.';
  return _validatePasswordUpperBounds(password);
}

String? validateRegistrationPassword(String? value) {
  final password = value ?? '';
  if (password.isEmpty) return 'Password is required.';
  if (password.length < 8) {
    return 'Password must be at least 8 characters.';
  }
  return _validatePasswordUpperBounds(password);
}

String? _validatePasswordUpperBounds(String password) {
  if (password.length > maxAuthPasswordLength) {
    return 'Password must be at most $maxAuthPasswordLength characters.';
  }
  if (utf8.encode(password).length > maxBcryptPasswordBytes) {
    return 'Password must be at most $maxBcryptPasswordBytes UTF-8 bytes.';
  }
  return null;
}

String? validateFullName(String? value) {
  final name = (value ?? '').trim();
  if (name.isEmpty) return 'Full name is required.';
  if (name.length > maxFullNameLength) {
    return 'Full name must be at most $maxFullNameLength characters.';
  }
  return null;
}

String? validateDepartmentCode(String? value) {
  final code = (value ?? '').trim();
  if (code.length > maxDepartmentCodeLength) {
    return 'Department code must be at most $maxDepartmentCodeLength characters.';
  }
  return null;
}
