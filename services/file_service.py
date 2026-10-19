import os
import sys
import shutil
import random
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from database import db
from services.access_logger import log_file_access


def ensure_storage_directories():
    """Ensure directory structure for all storage nodes exists."""
    os.makedirs(config.STORAGE_ROOT, exist_ok=True)
    for node_id, data in config.DEFAULT_NODES.items():
        node_dir = data["path"]
        os.makedirs(node_dir, exist_ok=True)


def get_node_info(node_id):
    """Retrieve node details from database or fallback to config."""
    node = db.query_one("SELECT * FROM storage_nodes WHERE node_id = ?", (node_id,))
    if not node and node_id in config.DEFAULT_NODES:
        return config.DEFAULT_NODES[node_id]
    return node


def get_all_storage_nodes():
    """Retrieve all storage nodes with utilization statistics."""
    nodes = db.query_all("SELECT * FROM storage_nodes ORDER BY node_id ASC")
    
    # Calculate file count per node
    for node in nodes:
        count_res = db.query_one(
            "SELECT COUNT(*) as file_count, COALESCE(SUM(file_size), 0) as total_size FROM files WHERE current_node_id = ?",
            (node["node_id"],)
        )
        node["file_count"] = count_res["file_count"] if count_res else 0
        actual_used = count_res["total_size"] if count_res else 0
        node["used_bytes"] = actual_used
        
        cap = node["capacity_bytes"]
        node["utilization_pct"] = round((actual_used / cap) * 100, 2) if cap > 0 else 0
        node["free_bytes"] = max(0, cap - actual_used)
        
    return nodes


def save_file(file_data, filename, target_node_id, policy="ml", predicted_popularity="unclassified"):
    """
    Save file to disk in target node folder and record in database.
    file_data can be bytes or a file-like object with .read().
    """
    ensure_storage_directories()
    
    # Check if file exists with same name
    existing = db.query_one("SELECT file_id, current_node_id FROM files WHERE filename = ?", (filename,))
    if existing:
        delete_file(existing["file_id"])

    # Determine file content and size
    if hasattr(file_data, "read"):
        content = file_data.read()
    elif isinstance(file_data, bytes):
        content = file_data
    elif isinstance(file_data, str):
        content = file_data.encode("utf-8")
    else:
        content = b""

    file_size = len(content)

    # Check capacity of target node
    node = get_node_info(target_node_id)
    if not node:
        raise ValueError(f"Storage node '{target_node_id}' does not exist.")

    used = node.get("used_bytes", 0)
    capacity = node.get("capacity_bytes", 100 * 1024 * 1024)
    if used + file_size > capacity:
        raise ValueError(f"Storage node '{target_node_id}' does not have enough capacity.")

    # Write file to storage node directory
    target_dir = os.path.join(config.STORAGE_ROOT, target_node_id)
    os.makedirs(target_dir, exist_ok=True)
    target_path = os.path.join(target_dir, filename)

    with open(target_path, "wb") as f:
        f.write(content)

    # Record in database
    if config.DB_TYPE == "sqlite":
        file_id = db.execute(
            """
            INSERT INTO files (filename, file_size, current_node_id, predicted_popularity, placement_policy)
            VALUES (?, ?, ?, ?, ?)
            """,
            (filename, file_size, target_node_id, predicted_popularity, policy)
        )
        db.execute(
            "UPDATE storage_nodes SET used_bytes = used_bytes + ? WHERE node_id = ?",
            (file_size, target_node_id)
        )
    else:
        file_id = db.execute(
            """
            INSERT INTO files (filename, file_size, current_node_id, predicted_popularity, placement_policy)
            VALUES (%s, %s, %s, %s, %s) RETURNING file_id
            """,
            (filename, file_size, target_node_id, predicted_popularity, policy)
        )
        db.execute(
            "UPDATE storage_nodes SET used_bytes = used_bytes + %s WHERE node_id = %s",
            (file_size, target_node_id)
        )

    return db.query_one("SELECT * FROM files WHERE file_id = ?", (file_id,))


def get_file(file_id, simulate_delay=True, access_type="read"):
    """
    Retrieve file details, compute tier retrieval latency, record access log,
    and return file info and local path.
    """
    file_record = db.query_one("SELECT * FROM files WHERE file_id = ?", (file_id,))
    if not file_record:
        return None, None, 0.0

    node_id = file_record["current_node_id"]
    node = get_node_info(node_id)
    base_latency = node.get("base_latency_ms", 10.0) if node else 10.0

    # Add realistic latency simulation:
    # base latency + file transfer time (~1ms per 100KB) + random jitter (±10%)
    size_overhead = (file_record["file_size"] / (100 * 1024)) * 1.0
    jitter = random.uniform(-0.15, 0.25) * base_latency
    calculated_latency = max(1.0, round(base_latency + size_overhead + jitter, 2))

    if simulate_delay and calculated_latency > 0:
        # Sleep a fraction of latency in milliseconds (e.g. 1/10th) to feel responsive without stalling
        time.sleep(min(calculated_latency / 1000.0, 0.1))

    # Log access
    log_file_access(file_id, node_id, calculated_latency, access_type=access_type)

    file_path = os.path.join(config.STORAGE_ROOT, node_id, file_record["filename"])
    return file_record, file_path, calculated_latency


def migrate_file(file_id, target_node_id, reason="ml_recommendation", policy="ml"):
    """
    Move a file from its current storage node to a target node.
    """
    file_record = db.query_one("SELECT * FROM files WHERE file_id = ?", (file_id,))
    if not file_record:
        raise ValueError(f"File with ID {file_id} not found.")

    current_node_id = file_record["current_node_id"]
    if current_node_id == target_node_id:
        return False, "File is already on target node"

    file_size = file_record["file_size"]
    target_node = get_node_info(target_node_id)
    if not target_node:
        raise ValueError(f"Target node '{target_node_id}' does not exist.")

    # Check target capacity
    count_res = db.query_one(
        "SELECT COALESCE(SUM(file_size), 0) as total_size FROM files WHERE current_node_id = ?",
        (target_node_id,)
    )
    current_target_used = count_res["total_size"] if count_res else 0
    if current_target_used + file_size > target_node["capacity_bytes"]:
        return False, f"Target node {target_node_id} has insufficient capacity."

    src_path = os.path.join(config.STORAGE_ROOT, current_node_id, file_record["filename"])
    dest_dir = os.path.join(config.STORAGE_ROOT, target_node_id)
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, file_record["filename"])

    # Move physical file if it exists
    if os.path.exists(src_path):
        shutil.move(src_path, dest_path)
    else:
        # If source doesn't exist on disk, create an empty file at destination
        with open(dest_path, "wb") as f:
            f.write(b"")

    # Update database
    if config.DB_TYPE == "sqlite":
        db.execute(
            "UPDATE files SET current_node_id = ?, placement_policy = ? WHERE file_id = ?",
            (target_node_id, policy, file_id)
        )
        db.execute(
            "UPDATE storage_nodes SET used_bytes = MAX(0, used_bytes - ?) WHERE node_id = ?",
            (file_size, current_node_id)
        )
        db.execute(
            "UPDATE storage_nodes SET used_bytes = used_bytes + ? WHERE node_id = ?",
            (file_size, target_node_id)
        )
        db.execute(
            """
            INSERT INTO placement_history (file_id, from_node_id, to_node_id, reason, policy_used)
            VALUES (?, ?, ?, ?, ?)
            """,
            (file_id, current_node_id, target_node_id, reason, policy)
        )
    else:
        db.execute(
            "UPDATE files SET current_node_id = %s, placement_policy = %s WHERE file_id = %s",
            (target_node_id, policy, file_id)
        )
        db.execute(
            "UPDATE storage_nodes SET used_bytes = GREATEST(0, used_bytes - %s) WHERE node_id = %s",
            (file_size, current_node_id)
        )
        db.execute(
            "UPDATE storage_nodes SET used_bytes = used_bytes + %s WHERE node_id = %s",
            (file_size, target_node_id)
        )
        db.execute(
            """
            INSERT INTO placement_history (file_id, from_node_id, to_node_id, reason, policy_used)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (file_id, current_node_id, target_node_id, reason, policy)
        )

    return True, f"Successfully migrated file {file_record['filename']} from {current_node_id} to {target_node_id}"


def delete_file(file_id):
    """Delete a file from disk and database."""
    file_record = db.query_one("SELECT * FROM files WHERE file_id = ?", (file_id,))
    if not file_record:
        return False

    current_node_id = file_record["current_node_id"]
    file_size = file_record["file_size"]
    path = os.path.join(config.STORAGE_ROOT, current_node_id, file_record["filename"])

    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass

    db.execute("DELETE FROM files WHERE file_id = ?", (file_id,))
    db.execute(
        "UPDATE storage_nodes SET used_bytes = MAX(0, used_bytes - ?) WHERE node_id = ?",
        (file_size, current_node_id)
    )
    return True


def get_all_files():
    """Retrieve all files with current node info and popularity stats."""
    return db.query_all(
        """
        SELECT 
            f.file_id,
            f.filename,
            f.file_size,
            f.current_node_id,
            sn.name as node_name,
            sn.tier as node_tier,
            f.predicted_popularity,
            f.placement_policy,
            f.created_at,
            f.last_accessed_at,
            f.access_count,
            (SELECT AVG(response_time_ms) FROM access_logs WHERE file_id = f.file_id) as avg_latency_ms
        FROM files f
        LEFT JOIN storage_nodes sn ON f.current_node_id = sn.node_id
        ORDER BY f.file_id DESC
        """
    )
