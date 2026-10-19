import sqlite3
import os
import sys
from contextlib import contextmanager

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

try:
    import psycopg2
    import psycopg2.extras
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False


def get_connection():
    """Return a database connection based on config.DB_TYPE."""
    if config.DB_TYPE == "postgres":
        if not PSYCOPG2_AVAILABLE:
            raise RuntimeError("psycopg2 is not installed but DB_TYPE is set to 'postgres'")
        conn = psycopg2.connect(
            host=config.PG_HOST,
            port=config.PG_PORT,
            dbname=config.PG_DBNAME,
            user=config.PG_USER,
            password=config.PG_PASSWORD
        )
        return conn
    else:
        # SQLite
        os.makedirs(os.path.dirname(os.path.abspath(config.SQLITE_DB_PATH)), exist_ok=True)
        conn = sqlite3.connect(config.SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn


@contextmanager
def get_db():
    """Context manager for acquiring and closing db connections."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def dict_from_row(row):
    """Convert SQLite Row or tuple to dictionary."""
    if row is None:
        return None
    if isinstance(row, sqlite3.Row):
        return dict(row)
    if isinstance(row, dict):
        return row
    return dict(row)


def query_all(sql, params=()):
    """Execute a SELECT query and return list of dictionaries."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        if config.DB_TYPE == "postgres":
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in rows]
        return [dict_from_row(r) for r in rows]


def query_one(sql, params=()):
    """Execute a SELECT query and return one dictionary or None."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        row = cursor.fetchone()
        if row is None:
            return None
        if config.DB_TYPE == "postgres":
            columns = [desc[0] for desc in cursor.description]
            return dict(zip(columns, row))
        return dict_from_row(row)


def execute(sql, params=()):
    """Execute INSERT/UPDATE/DELETE query and return lastrowid / rowcount."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        return cursor.lastrowid


def init_db():
    """Initialize database tables and default storage nodes."""
    schema_path = os.path.join(config.BASE_DIR, "database", "schema.sql")
    with open(schema_path, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    with get_db() as conn:
        cursor = conn.cursor()
        if config.DB_TYPE == "sqlite":
            cursor.executescript(schema_sql)
        else:
            cursor.execute(schema_sql)

        # Seed default storage nodes if they don't exist
        for node_id, data in config.DEFAULT_NODES.items():
            cursor.execute("SELECT node_id FROM storage_nodes WHERE node_id = ?", (node_id,) if config.DB_TYPE == "sqlite" else "%s")
            exists = cursor.fetchone()
            if not exists:
                if config.DB_TYPE == "sqlite":
                    cursor.execute(
                        """
                        INSERT INTO storage_nodes (node_id, name, tier, capacity_bytes, used_bytes, base_latency_ms, status)
                        VALUES (?, ?, ?, ?, 0, ?, 'active')
                        """,
                        (data["node_id"], data["name"], data["tier"], data["capacity_bytes"], data["base_latency_ms"])
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO storage_nodes (node_id, name, tier, capacity_bytes, used_bytes, base_latency_ms, status)
                        VALUES (%s, %s, %s, %s, 0, %s, 'active')
                        """,
                        (data["node_id"], data["name"], data["tier"], data["capacity_bytes"], data["base_latency_ms"])
                    )


if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")
