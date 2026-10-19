import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from database import db


def heuristic_recommendation(file_size, access_count=0, recent_access_24h=0):
    """
    Rule-based placement logic using file size and access patterns:
    - High access count or high recent activity -> Node 1 (Hot Tier)
    - Very large file (> 10MB) or no access -> Node 3 (Cold Tier)
    - Moderate size and access -> Node 2 (Warm Tier)
    """
    if access_count >= 20 or recent_access_24h >= 5:
        return "node1", "hot", "High access frequency detected"
    elif file_size > 10 * 1024 * 1024:
        return "node3", "cold", "Large file size (> 10MB) relegated to cold tier"
    elif access_count <= 2:
        return "node3", "cold", "Low access frequency (cold)"
    else:
        return "node2", "warm", "Moderate access frequency (warm)"


def select_heuristic_node(filename, file_size, access_count=0, recent_access_24h=0):
    """
    Select storage node using heuristic rules while verifying capacity.
    """
    recommended_node, tier, reason = heuristic_recommendation(
        file_size, access_count, recent_access_24h
    )

    # Check capacity of recommended node
    nodes = db.query_all("SELECT node_id, capacity_bytes, used_bytes FROM storage_nodes WHERE status = 'active'")
    nodes_by_id = {n["node_id"]: n for n in nodes}

    target = nodes_by_id.get(recommended_node)
    if target and (target["capacity_bytes"] - target["used_bytes"]) >= file_size:
        return recommended_node, tier, reason

    # Fallback to node with most free capacity
    available_sorted = sorted(
        nodes,
        key=lambda n: (n["capacity_bytes"] - n["used_bytes"]),
        reverse=True
    )

    for cand in available_sorted:
        if (cand["capacity_bytes"] - cand["used_bytes"]) >= file_size:
            return cand["node_id"], cand.get("tier", "warm"), f"Primary {recommended_node} was full, overflowed to {cand['node_id']}"

    return recommended_node, tier, "Capacity warning: Storage full across nodes"
