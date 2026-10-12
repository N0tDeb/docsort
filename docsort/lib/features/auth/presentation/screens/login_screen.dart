import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'dart:math' as math;

import '../../../../core/theme/app_colors.dart';
import '../../../../core/theme/app_text_styles.dart';
import '../../../../core/widgets/app_button.dart';
import '../../../../core/widgets/app_text_field.dart';
import '../../../../core/widgets/app_snackbar.dart';
import '../providers/auth_provider.dart';

class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen>
    with TickerProviderStateMixin {
  late AnimationController _slideCtrl;
  late AnimationController _flipCtrl;
  late AnimationController _shakeCtrl;

  final TextEditingController _emailCtrl = TextEditingController();
  final TextEditingController _passCtrl = TextEditingController();
  final GlobalKey<FormState> _formKey = GlobalKey<FormState>();

  bool _isFlipped = false;

  @override
  void initState() {
    super.initState();
    _slideCtrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 600),
    );
    _flipCtrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 600),
    );
    _shakeCtrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 400),
    );

    // Slide up on focus
    _slideCtrl.forward();
  }

  @override
  void dispose() {
    _slideCtrl.dispose();
    _flipCtrl.dispose();
    _shakeCtrl.dispose();
    _emailCtrl.dispose();
    _passCtrl.dispose();
    super.dispose();
  }

  void _handleLogin() async {
    if (!(_formKey.currentState?.validate() ?? false)) {
      return;
    }

    final success = await ref
        .read(authProvider.notifier)
        .login(_emailCtrl.text, _passCtrl.text, '');

    if (!mounted) return;

    if (success) {
      setState(() => _isFlipped = true);
      await _flipCtrl.forward();

      if (!mounted) return;

      // Password + JWT are the application's authentication boundary.
      // Successful authentication routes directly according to the server-backed role.
      final authState = ref.read(authProvider);
      context.go(authState.isAdmin ? '/admin' : '/home');
    } else {
      _shakeCtrl.forward(from: 0.0);
      final err = ref.read(authProvider).errorMessage ?? 'Login Failed';
      if (mounted) AppSnackbar.showError(context, err);
    }
  }

  Widget _buildLoginForm() {
    final state = ref.watch(authProvider);

    return Container(
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        color: AppColors.surfaceLowest,
        borderRadius: BorderRadius.circular(24),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.05),
            blurRadius: 24,
            offset: const Offset(0, 8),
          ),
        ],
      ),
      child: Form(
        key: _formKey,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text('Welcome Back', style: AppTextStyles.headlineSm),
            const SizedBox(height: 8),
            Text('Login to your dashboard', style: AppTextStyles.bodyMd),
            const SizedBox(height: 32),
            AppTextField(
              label: 'Email Address',
              controller: _emailCtrl,
              keyboardType: TextInputType.emailAddress,
              validator: (value) {
                if ((value ?? '').trim().isEmpty) {
                  return 'Email address is required.';
                }
                return null;
              },
            ),
            const SizedBox(height: 16),
            AppTextField(
              label: 'Password',
              controller: _passCtrl,
              isPassword: true,
              validator: (value) {
                if ((value ?? '').isEmpty) {
                  return 'Password is required.';
                }
                return null;
              },
            ),
            const SizedBox(height: 32),
            AppButton(
              text: 'Login Securely',
              isLoading: state.status == AuthStatus.loading,
              onPressed: _handleLogin,
            ),
            const SizedBox(height: 16),
            TextButton(
              onPressed: () => context.go('/register'),
              child: Text(
                'Register new account',
                style: AppTextStyles.bodyMd.copyWith(color: AppColors.primary),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildSuccessCard() {
    return Transform(
      alignment: Alignment.center,
      transform: Matrix4.identity()..rotateY(math.pi),
      child: Container(
        height: 400,
        width: double.infinity,
        decoration: BoxDecoration(
          gradient: const LinearGradient(
            colors: [AppColors.primary, AppColors.primaryContainer],
          ),
          borderRadius: BorderRadius.circular(24),
        ),
        child: const Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.check_circle_outline, color: Colors.white, size: 80),
              SizedBox(height: 16),
              Text(
                'Secure Login Successful',
                style: TextStyle(
                  color: Colors.white,
                  fontSize: 20,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.background,
      body: Stack(
        children: [
          // Top Navy Header
          Positioned(
            top: 0,
            left: 0,
            right: 0,
            height: math.max(220.0, MediaQuery.sizeOf(context).height * 0.4),
            child: Container(
              color: AppColors.primary,
              child: SafeArea(
                child: Padding(
                  padding: const EdgeInsets.only(top: 40.0),
                  child: Column(
                    children: [
                      Image.asset(
                        'assets/docsort_logo.png',
                        height: 80,
                        width: 80,
                        fit: BoxFit.contain,
                      ),
                      const SizedBox(height: 16),
                      Text(
                        'DocSort',
                        style: AppTextStyles.displayMd.copyWith(
                          color: Colors.white,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
          // Form Card
          SafeArea(
            child: SingleChildScrollView(
              padding: const EdgeInsets.fromLTRB(24, 220, 24, 24),
              child: SlideTransition(
                position:
                    Tween<Offset>(
                      begin: const Offset(0, 0.5),
                      end: Offset.zero,
                    ).animate(
                      CurvedAnimation(
                        parent: _slideCtrl,
                        curve: Curves.easeOutCubic,
                      ),
                    ),
                child: AnimatedBuilder(
                  animation: _shakeCtrl,
                  builder: (context, child) {
                    final sineValue = math.sin(_shakeCtrl.value * math.pi * 3);
                    return Transform.translate(
                      offset: Offset(sineValue * 8, 0),
                      child: child,
                    );
                  },
                  child: AnimatedBuilder(
                    animation: _flipCtrl,
                    builder: (context, child) {
                      return Transform(
                        transform: Matrix4.identity()
                          ..setEntry(3, 2, 0.001)
                          ..rotateY(_flipCtrl.value * math.pi),
                        alignment: Alignment.center,
                        child: _isFlipped
                            ? _buildSuccessCard()
                            : _buildLoginForm(),
                      );
                    },
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
