"""
user_repository.py — All `users` table access through the shared Supabase client.

The repository uses the single `SupabaseClient` in `app.core.database`, keeping
database access behind one backend data-access layer.
"""
from app.core.database import get_supabase_sync


def create_user(data: dict) -> dict:
    """Insert a new user row and return it."""
    res = get_supabase_sync().table("users").insert(data).execute()
    return res.data[0] if res.data else {}


def get_user_by_email(email: str) -> list:
    """Return users matching the given email (usually 0 or 1)."""
    res = (
        get_supabase_sync()
        .table("users")
        .select("*")
        .eq("email", email)
        .execute()
    )
    return res.data or []


def update_user(user_id: str, data: dict) -> dict:
    """Partially update a user row by id and return the updated row."""
    res = (
        get_supabase_sync()
        .table("users")
        .update(data)
        .eq("id", user_id)
        .execute()
    )
    return res.data[0] if res.data else {}
