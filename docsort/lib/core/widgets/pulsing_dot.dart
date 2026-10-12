import 'package:flutter/material.dart';

class PulsingDot extends StatefulWidget {
  final Color color;
  final bool animate;

  const PulsingDot({
    super.key,
    this.color = Colors.green,
    this.animate = true,
  });

  @override
  State<PulsingDot> createState() => _PulsingDotState();
}

class _PulsingDotState extends State<PulsingDot> with SingleTickerProviderStateMixin {
  late AnimationController _ctrl;

  @override
  void initState() {
    super.initState();
    _ctrl = AnimationController(vsync: this, duration: const Duration(milliseconds: 750));
    if (widget.animate) {
      _ctrl.repeat(reverse: true);
    }
  }

  @override
  void didUpdateWidget(PulsingDot oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.animate && !_ctrl.isAnimating) {
      _ctrl.repeat(reverse: true);
    } else if (!widget.animate && _ctrl.isAnimating) {
      _ctrl.stop();
      _ctrl.value = 0;
    }
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _ctrl,
      builder: (context, child) {
        final scale = 1.0 + (_ctrl.value * 0.25);
        final opacity = 1.0 - (_ctrl.value * 0.5);

        return Container(
          width: 10 * scale,
          height: 10 * scale,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: widget.color.withValues(alpha: widget.animate ? opacity : 1.0),
            boxShadow: widget.animate
                ? [BoxShadow(color: widget.color.withValues(alpha: 0.4), blurRadius: 6 * _ctrl.value, spreadRadius: 2 * _ctrl.value)]
                : [],
          ),
        );
      },
    );
  }
}
