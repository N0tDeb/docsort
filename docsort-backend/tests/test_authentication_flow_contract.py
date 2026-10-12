from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "docsort-backend"
FLUTTER_ROOT = PROJECT_ROOT / "docsort"


def test_backend_auth_contract_has_no_secondary_pin_endpoint():
    main_source = (BACKEND_ROOT / "app" / "main.py").read_text(encoding="utf-8")

    assert "app.api import" in main_source
    assert "include_router(pin.router)" not in main_source
    assert "share, pin" not in main_source
    assert not (BACKEND_ROOT / "app" / "api" / "pin.py").exists()


def test_flutter_login_routes_directly_after_password_authentication():
    login_source = (
        FLUTTER_ROOT
        / "lib"
        / "features"
        / "auth"
        / "presentation"
        / "screens"
        / "login_screen.dart"
    ).read_text(encoding="utf-8")

    assert "pin_screen.dart" not in login_source
    assert "pinProvider" not in login_source
    assert "showPinBottomSheet" not in login_source
    assert "/auth/pin/" not in login_source
    assert "context.go(authState.isAdmin ? '/admin' : '/home')" in login_source
    assert not (
        FLUTTER_ROOT
        / "lib"
        / "features"
        / "auth"
        / "presentation"
        / "screens"
        / "pin_screen.dart"
    ).exists()
