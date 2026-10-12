"""Print configured DocSort departments from Supabase.

Run from the repository root with: ``python scripts/get_depts.py``.
Requires ``docsort-backend/.env`` to be configured.
"""
from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parents[1] / "docsort-backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.core.database import get_supabase_sync  # noqa: E402


def main() -> None:
    supabase = get_supabase_sync()
    res = supabase.table("departments").select("id, code, name").execute()
    print("\n--- VALID DEPARTMENTS ---")
    for row in res.data:
        print(f"Code: {row['code']} | Name: {row['name']} | ID: {row['id']}")
    print("-------------------------\n")


if __name__ == "__main__":
    main()
