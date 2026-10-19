import os
import sys
import random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from database import db
from ml.predict import predict_for_file, predict_popularity, recommend_node_for_tier
from services.file_service import migrate_file, get_file
from services.event_broker import broker

NODE_METADATA = {
    "node1": {"name": "Node 1: Hot / NVMe SSD", "tier": "hot", "latency_ms": 5.0},
    "node2": {"name": "Node 2: Warm / Standard SSD", "tier": "warm", "latency_ms": 25.0},
    "node3": {"name": "Node 3: Cold / HDD Archive", "tier": "cold", "latency_ms": 120.0},
}

def infer_initial_features(file_size):
    """
    Build the cold-start feature vector from facts available at upload time.
    Access behavior is zero until the system observes real reads/downloads.
    """
    return {
        "file_size": file_size,
        "access_count": 0,
        "recent_access_1h": 0,
        "recent_access_24h": 0,
        "hours_since_last_access": 0.0,
        "accesses_per_day": 0.0,
    }


def determine_placement(filename, file_size, policy="ml", file_id=None):
    """
    AI-Driven placement decision using Machine Learning Random Forest Classifier.
    Exclusively powered by ML prediction.
    """
    if file_id is not None:
        # Re-evaluating existing file with real historical access logs
        pred_res = predict_for_file(file_id)
        popularity = pred_res["predicted_popularity"]
        confidence = pred_res.get("confidence", 1.0)
        probabilities = pred_res.get("probabilities", {popularity: 1.0})
        features = pred_res.get("features", {})
        reason = f"ML Random Forest re-evaluation ({popularity.upper()} with {int(confidence * 100)}% confidence)"
    else:
        # New upload: run ML inference on initial feature vector
        features = infer_initial_features(file_size)
        pred_res = predict_popularity(features)
        popularity = pred_res["predicted_popularity"]
        confidence = pred_res["confidence"]
        probabilities = pred_res["probabilities"]
        reason = f"ML Random Forest inference ({popularity.upper()} with {int(confidence * 100)}% confidence)"

    target_node = recommend_node_for_tier(popularity)
    is_overflow = False
    original_target = target_node

    # Capacity overflow check: ensure target node can hold file_size
    node = db.query_one("SELECT capacity_bytes, used_bytes FROM storage_nodes WHERE node_id = ?", (target_node,))
    if node and (node["capacity_bytes"] - node["used_bytes"]) < file_size:
        fallback = "node2" if target_node != "node2" else "node3"
        reason += f" [Capacity overflow from {target_node} -> redirected to {fallback}]"
        target_node = fallback
        is_overflow = True

    node_meta = NODE_METADATA.get(target_node, {"name": target_node, "tier": popularity, "latency_ms": 25.0})

    return {
        "node_id": target_node,
        "target_node_name": node_meta["name"],
        "node_latency_ms": node_meta["latency_ms"],
        "tier": popularity,
        "policy": "ml",
        "predicted_popularity": popularity,
        "confidence": round(confidence, 3),
        "probabilities": probabilities,
        "features": features,
        "reason": reason,
        "is_overflow": is_overflow,
        "original_target": original_target if is_overflow else None,
    }


def evaluate_and_migrate_file(file_id, policy="ml"):
    """Predict from a file's observed access history and migrate if its tier changed."""
    file_record = db.query_one("SELECT * FROM files WHERE file_id = ?", (file_id,))
    if not file_record:
        return None

    decision = determine_placement(
        file_record["filename"],
        file_record["file_size"],
        policy=policy,
        file_id=file_id
    )
    predicted_popularity = decision["predicted_popularity"]
    db.execute(
        "UPDATE files SET predicted_popularity = ? WHERE file_id = ?",
        (predicted_popularity, file_id)
    )

    current_node = file_record["current_node_id"]
    recommended_node = decision["node_id"]
    migration = None
    if recommended_node != current_node:
        success, message = migrate_file(
            file_id=file_id,
            target_node_id=recommended_node,
            reason=f"ML Dynamic Promotion/Demotion ({decision['reason']})",
            policy=policy
        )
        migration = {
            "file_id": file_id,
            "filename": file_record["filename"],
            "from_node": current_node,
            "to_node": recommended_node,
            "from_tier": NODE_METADATA.get(current_node, {}).get("tier", "unknown"),
            "to_tier": predicted_popularity,
            "popularity": predicted_popularity,
            "confidence": decision["confidence"],
            "success": success,
            "message": message,
        }
        if success:
            broker.broadcast("file_migrated", migration)

    updated_file = db.query_one("SELECT * FROM files WHERE file_id = ?", (file_id,))
    return {
        "file": updated_file,
        "decision": decision,
        "migration": migration,
    }


def evaluate_and_migrate_all_files(policy="ml"):
    """
    Re-evaluate all files in the system using the ML model and dynamically
    migrate files whose popularity tier has shifted based on live access patterns.
    """
    files = db.query_all("SELECT file_id FROM files ORDER BY file_id ASC")
    migration_results = []

    for f in files:
        result = evaluate_and_migrate_file(f["file_id"], policy=policy)
        if result and result["migration"] is not None:
            migration_results.append(result["migration"])

    return {
        "policy": "ml",
        "total_files_evaluated": len(files),
        "migrations_performed": sum(1 for migration in migration_results if migration["success"]),
        "migration_attempts": len(migration_results),
        "details": migration_results
    }


def run_benchmark_simulation(num_requests=50):
    """
    Simulate Zipfian access workload across files and measure latency.
    """
    files = db.query_all("SELECT file_id, filename, current_node_id, file_size FROM files")
    if not files:
        return {"error": "No files found in storage. Upload some files first."}

    num_files = len(files)
    weights = [1.0 / ((i + 1) ** 0.8) for i in range(num_files)]
    total_w = sum(weights)
    probs = [w / total_w for w in weights]

    latencies = []
    tier_counts = {"hot": 0, "warm": 0, "cold": 0}

    for _ in range(num_requests):
        selected_file = random.choices(files, weights=probs, k=1)[0]
        _, _, latency_ms = get_file(selected_file["file_id"], simulate_delay=False)
        latencies.append(latency_ms)

        node = db.query_one("SELECT tier FROM storage_nodes WHERE node_id = ?", (selected_file["current_node_id"],))
        if node:
            tier_counts[node["tier"]] = tier_counts.get(node["tier"], 0) + 1

    avg_latency = round(sum(latencies) / len(latencies), 2)
    min_latency = round(min(latencies), 2)
    max_latency = round(max(latencies), 2)

    return {
        "total_requests": num_requests,
        "avg_latency_ms": avg_latency,
        "min_latency_ms": min_latency,
        "max_latency_ms": max_latency,
        "tier_distribution": tier_counts
    }
