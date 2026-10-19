import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Simulated Storage Nodes Configuration
STORAGE_ROOT = os.environ.get("STORAGE_ROOT", str(BASE_DIR / "storage"))

DEFAULT_NODES = {
    "node1": {
        "node_id": "node1",
        "name": "Node-1 (Hot / NVMe SSD)",
        "tier": "hot",
        "capacity_bytes": 100 * 1024 * 1024,  # 100 MB
        "base_latency_ms": 5.0,
        "path": os.path.join(STORAGE_ROOT, "node1")
    },
    "node2": {
        "node_id": "node2",
        "name": "Node-2 (Warm / Standard SSD)",
        "tier": "warm",
        "capacity_bytes": 300 * 1024 * 1024,  # 300 MB
        "base_latency_ms": 25.0,
        "path": os.path.join(STORAGE_ROOT, "node2")
    },
    "node3": {
        "node_id": "node3",
        "name": "Node-3 (Cold / HDD Archive)",
        "tier": "cold",
        "capacity_bytes": 1000 * 1024 * 1024,  # 1000 MB (1 GB)
        "base_latency_ms": 120.0,
        "path": os.path.join(STORAGE_ROOT, "node3")
    }
}

# Database settings
DB_TYPE = os.environ.get("DB_TYPE", "sqlite")  # 'sqlite' or 'postgres'
SQLITE_DB_PATH = os.environ.get("SQLITE_DB_PATH", str(BASE_DIR / "dynamic_placement.db"))

PG_HOST = os.environ.get("PG_HOST", "localhost")
PG_PORT = int(os.environ.get("PG_PORT", 5432))
PG_DBNAME = os.environ.get("PG_DBNAME", "dynamic_placement")
PG_USER = os.environ.get("PG_USER", "postgres")
PG_PASSWORD = os.environ.get("PG_PASSWORD", "postgres")

# Machine Learning model settings
MODEL_PATH = os.environ.get("MODEL_PATH", str(BASE_DIR / "ml" / "placement_model.joblib"))
MODEL_ARTIFACT_VERSION = 2

# Flask Configuration
SECRET_KEY = os.environ.get("SECRET_KEY", "dynamic-placement-secret-key-12345")
UPLOAD_MAX_SIZE = 50 * 1024 * 1024  # 50 MB max per upload
DEBUG = os.environ.get("FLASK_DEBUG", "True").lower() in ("true", "1", "yes")
