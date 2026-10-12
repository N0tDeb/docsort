"""Regression checks for the simplified organization/member/admin model."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "docsort-backend"
FLUTTER = ROOT / "docsort"


def test_schema_uses_only_member_and_admin_roles():
    schema = (BACKEND / "schema.sql").read_text(encoding="utf-8")
    assert "role IN ('user', 'admin')" in schema
    assert "role IN ('user', 'officer', 'admin')" not in schema
    assert "UPDATE users SET role = 'user' WHERE role = 'officer'" in schema
    assert "DROP CONSTRAINT IF EXISTS users_role_check" in schema
    assert "ADD CONSTRAINT users_role_check CHECK (role IN ('user', 'admin'))" in schema


def test_backend_has_no_unused_role_helper():
    assert not (BACKEND / "app/core/roles.py").exists()


def test_flutter_presents_organization_admin_consistently():
    admin = (FLUTTER / "lib/features/admin/presentation/screens/admin_screen.dart").read_text(encoding="utf-8")
    router = (FLUTTER / "lib/core/router/app_router.dart").read_text(encoding="utf-8")
    register = (FLUTTER / "lib/features/auth/presentation/screens/register_screen.dart").read_text(encoding="utf-8")

    assert "Organization Admin" in admin
    assert "Promote to Organization Admin" in admin
    assert "No users in your department yet." not in admin
    assert "officer pages" not in router
    assert "administrator" in register.lower()
    assert "approval" in register.lower()


def test_auth_messages_do_not_imply_department_admin_role():
    auth = (BACKEND / "app/api/auth.py").read_text(encoding="utf-8")
    assert "pending administrator approval" in auth
    assert "Contact an administrator" in auth
    assert "department admin" not in auth


def test_readme_documents_single_organization_scope():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "A DocSort deployment represents one organization" in readme
    assert "Organization administrator (`admin`)" in readme
    assert "Member (`user`)" in readme
    assert "organization-wide operational/security views" in readme


def test_fastapi_metadata_is_domain_neutral():
    main = (BACKEND / "app/main.py").read_text(encoding="utf-8")
    assert "document intelligence" in main
    assert "government documents" not in main
