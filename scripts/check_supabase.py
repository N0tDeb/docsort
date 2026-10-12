"""Small Supabase connectivity smoke check for local development.

Run from the repository root with: ``python scripts/check_supabase.py``.
Requires ``docsort-backend/.env`` to be configured.
"""
from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parents[1] / "docsort-backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.core.database import get_supabase_sync  # noqa: E402


def main() -> None:
    supabase = get_supabase_sync()
    result = supabase.table("documents").select("id").limit(1).execute()
    print("Supabase connection OK; documents table is reachable.")
    print(f"Sample rows returned: {len(result.data or [])}")


if __name__ == "__main__":
    main()
