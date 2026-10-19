import hashlib
import random
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from database import db


_ROUND_ROBIN_INDEX = 0


def get_available_nodes():
    """Retrieve list of active storage node IDs."""
    nodes = db.query_all("SELECT node_id FROM storage_nodes WHERE status = 'active' ORDER BY node_id ASC")
    if not nodes:
        return list(config.DEFAULT_NODES.keys())
    return [n["node_id"] for n in nodes]


def hash_placement(filename, available_nodes=None):
    """
    Consistent hash placement based on MD5 checksum of the filename.
    Deterministically maps a filename to a storage node.
    """
    nodes = available_nodes or get_available_nodes()
    if not nodes:
        return "node2"
    hash_val = int(hashlib.md5(filename.encode("utf-8")).hexdigest(), 16)
    return nodes[hash_val % len(nodes)]


def round_robin_placement(available_nodes=None):
    """
    Round-robin placement distributing files sequentially across nodes.
    """
    global _ROUND_ROBIN_INDEX
    nodes = available_nodes or get_available_nodes()
    if not nodes:
        return "node2"
    node = nodes[_ROUND_ROBIN_INDEX % len(nodes)]
    _ROUND_ROBIN_INDEX += 1
    return node


def random_placement(available_nodes=None):
    """
    Uniform random selection among available storage nodes.
    """
    nodes = available_nodes or get_available_nodes()
    return random.choice(nodes) if nodes else "node2"


def select_static_node(filename, file_size=0, method="hash"):
    """
    Main static placement selection function.
    Supports 'hash', 'round_robin', and 'random'.
    """
    if method == "round_robin":
        return round_robin_placement()
    elif method == "random":
        return random_placement()
    else:
        return hash_placement(filename)
