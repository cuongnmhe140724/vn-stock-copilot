"""Run SQL migrations against Supabase Postgres.

Usage:
    python -m database.migrate              # Run all pending migrations
    python -m database.migrate --status     # Show migration status
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv()

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _get_connection():
    """Build a direct Postgres connection from env vars.

    Priority:
      1. DATABASE_URL (if set, use as-is)
      2. Auto-construct from SUPABASE_URL + SUPABASE_PASSWORD, trying regions
    """
    # Option 1: explicit DATABASE_URL
    database_url = os.getenv("DATABASE_URL", "")
    if database_url:
        return psycopg2.connect(database_url)

    # Option 2: build from Supabase env vars
    url = os.getenv("SUPABASE_URL", "")
    password = os.getenv("SUPABASE_PASSWORD", "")

    if not url or not password:
        print("❌ Set DATABASE_URL or both SUPABASE_URL + SUPABASE_PASSWORD in .env")
        sys.exit(1)

    ref = url.replace("https://", "").replace(".supabase.co", "").strip("/")

    # Try common Supabase pooler regions
    regions = [
        "ap-southeast-1",  # Singapore
        "us-east-1",       # N. Virginia
        "us-west-1",       # N. California
        "eu-west-1",       # Ireland
        "eu-central-1",    # Frankfurt
        "ap-northeast-1",  # Tokyo
        "ap-south-1",      # Mumbai
    ]

    from urllib.parse import quote as url_quote
    safe_pw = url_quote(password, safe="")

    for region in regions:
        conn_str = (
            f"postgresql://postgres.{ref}:{safe_pw}"
            f"@aws-0-{region}.pooler.supabase.com:6543/postgres"
        )
        try:
            conn = psycopg2.connect(conn_str, connect_timeout=5)
            print(f"✅ Connected via region: {region}")
            return conn
        except psycopg2.OperationalError:
            continue

    print("❌ Could not connect to any Supabase region.")
    print("   Please set DATABASE_URL in .env directly.")
    print("   Find it at: Supabase Dashboard → Settings → Database → Connection string → URI")
    sys.exit(1)


def _ensure_migrations_table(conn):
    """Create the migrations tracking table if it doesn't exist."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS _migrations (
                id          SERIAL PRIMARY KEY,
                filename    TEXT NOT NULL UNIQUE,
                checksum    TEXT NOT NULL,
                applied_at  TIMESTAMPTZ DEFAULT now()
            );
        """)
    conn.commit()


def _get_applied(conn) -> set[str]:
    """Return set of already-applied migration filenames."""
    with conn.cursor() as cur:
        cur.execute("SELECT filename FROM _migrations ORDER BY id;")
        return {row[0] for row in cur.fetchall()}


def _file_checksum(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def run_migrations():
    """Run all pending .sql files in migrations/ folder."""
    if not MIGRATIONS_DIR.exists():
        print(f"❌ Migrations directory not found: {MIGRATIONS_DIR}")
        sys.exit(1)

    sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not sql_files:
        print("ℹ️  No migration files found.")
        return

    conn = _get_connection()
    try:
        _ensure_migrations_table(conn)
        applied = _get_applied(conn)

        pending = [f for f in sql_files if f.name not in applied]
        if not pending:
            print("✅ All migrations already applied.")
            return

        for f in pending:
            print(f"▶️  Applying: {f.name} ... ", end="", flush=True)
            sql = f.read_text(encoding="utf-8")

            with conn.cursor() as cur:
                cur.execute(sql)
                cur.execute(
                    "INSERT INTO _migrations (filename, checksum) VALUES (%s, %s);",
                    (f.name, _file_checksum(f)),
                )
            conn.commit()
            print("✅")

        print(f"\n🎉 Applied {len(pending)} migration(s) successfully!")

    except Exception as exc:
        conn.rollback()
        print(f"\n❌ Migration failed: {exc}")
        sys.exit(1)
    finally:
        conn.close()


def show_status():
    """Show which migrations have been applied."""
    conn = _get_connection()
    try:
        _ensure_migrations_table(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT filename, applied_at FROM _migrations ORDER BY id;")
            rows = cur.fetchall()

        sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
        applied_names = {r[0] for r in rows}

        print("Migration Status:")
        print("-" * 60)
        for f in sql_files:
            status = "✅ Applied" if f.name in applied_names else "⏳ Pending"
            print(f"  {status}  {f.name}")
        if not sql_files:
            print("  (no migration files found)")
        print("-" * 60)
    finally:
        conn.close()


if __name__ == "__main__":
    if "--status" in sys.argv:
        show_status()
    else:
        run_migrations()
