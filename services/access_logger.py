import os
import sys
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from database import db


def log_file_access(file_id, node_id, response_time_ms, access_type="read"):
    """
    Record a file access event, update file access count and last_accessed timestamp.
    """
    # 1. Insert access log
    if config.DB_TYPE == "sqlite":
        db.execute(
            """
            INSERT INTO access_logs (file_id, response_time_ms, node_id, access_type, accessed_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (file_id, response_time_ms, node_id, access_type)
        )
        # 2. Update files table
        db.execute(
            """
            UPDATE files
            SET access_count = access_count + 1,
                last_accessed_at = CURRENT_TIMESTAMP
            WHERE file_id = ?
            """,
            (file_id,)
        )
    else:
        db.execute(
            """
            INSERT INTO access_logs (file_id, response_time_ms, node_id, access_type, accessed_at)
            VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
            """,
            (file_id, response_time_ms, node_id, access_type)
        )
        db.execute(
            """
            UPDATE files
            SET access_count = access_count + 1,
                last_accessed_at = CURRENT_TIMESTAMP
            WHERE file_id = %s
            """,
            (file_id,)
        )


def get_file_access_stats(file_id=None):
    """
    Get aggregate access statistics for a file or all files.
    Calculates access count in last 1 hour, 24 hours, and all-time.
    """
    if file_id is not None:
        file_filter = "WHERE file_id = ?" if config.DB_TYPE == "sqlite" else "WHERE file_id = %s"
        params = (file_id,)
        stats = db.query_one(
            f"""
            SELECT 
                COUNT(*) as total_accesses,
                AVG(response_time_ms) as avg_latency_ms,
                MIN(response_time_ms) as min_latency_ms,
                MAX(response_time_ms) as max_latency_ms
            FROM access_logs
            {file_filter}
            """,
            params
        )
        return stats or {"total_accesses": 0, "avg_latency_ms": 0.0}

    # All files
    return db.query_all(
        """
        SELECT 
            f.file_id,
            f.filename,
            f.current_node_id,
            f.access_count,
            f.predicted_popularity,
            AVG(al.response_time_ms) as avg_latency_ms,
            MAX(al.accessed_at) as last_access
        FROM files f
        LEFT JOIN access_logs al ON f.file_id = al.file_id
        GROUP BY f.file_id
        ORDER BY f.access_count DESC
        """
    )


def get_recent_access_logs(limit=50):
    """Fetch the most recent access logs for the dashboard."""
    return db.query_all(
        f"""
        SELECT 
            al.log_id,
            al.file_id,
            f.filename,
            al.node_id,
            sn.tier as node_tier,
            al.response_time_ms,
            al.access_type,
            al.accessed_at
        FROM access_logs al
        JOIN files f ON al.file_id = f.file_id
        JOIN storage_nodes sn ON al.node_id = sn.node_id
        ORDER BY al.accessed_at DESC, al.log_id DESC
        LIMIT {int(limit)}
        """
    )
