import unittest
import os
import sys
import tempfile
import io

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from database import db
from services.file_service import (
    save_file, get_file, migrate_file, delete_file, get_all_files, get_all_storage_nodes
)
from services.access_logger import get_recent_access_logs
from ml.dataset import generate_synthetic_workload, extract_features_for_file
from ml.predict import predict_popularity, load_model
from placement.placement_controller import determine_placement, evaluate_and_migrate_all_files, run_benchmark_simulation
from app import app


class DynamicDataPlacementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Initialize database
        db.init_db()

    def test_01_storage_nodes_exist(self):
        nodes = get_all_storage_nodes()
        self.assertGreaterEqual(len(nodes), 3)
        node_ids = [n["node_id"] for n in nodes]
        self.assertIn("node1", node_ids)
        self.assertIn("node2", node_ids)
        self.assertIn("node3", node_ids)

    def test_02_file_upload_and_access(self):
        content = b"Simulated file payload for unit testing dynamic placement system"
        fname = "test_unit_file.txt"
        
        # Save file
        saved = save_file(
            file_data=content,
            filename=fname,
            target_node_id="node2",
            policy="static",
            predicted_popularity="warm"
        )
        self.assertIsNotNone(saved)
        file_id = saved["file_id"]

        # Access file
        rec, path, latency = get_file(file_id, simulate_delay=False)
        self.assertEqual(rec["filename"], fname)
        self.assertGreater(latency, 0.0)

        # Check access logs
        logs = get_recent_access_logs(limit=5)
        self.assertTrue(any(l["file_id"] == file_id for l in logs))

        # Clean up
        delete_file(file_id)

    def test_03_ml_model_prediction(self):
        model = load_model()
        self.assertIsNotNone(model)

        features = {
            "file_size": 1024 * 1024,
            "access_count": 80,
            "recent_access_1h": 10,
            "recent_access_24h": 35,
            "hours_since_last_access": 0.5,
            "accesses_per_day": 12.0
        }
        res = predict_popularity(features)
        self.assertIn("predicted_popularity", res)
        self.assertEqual(res["predicted_popularity"], "hot")

    def test_04_placement_controller_and_migration(self):
        # Create a file
        saved = save_file(
            file_data=b"hot data",
            filename="hot_candidate.bin",
            target_node_id="node3",  # initially placed on cold node
            policy="static",
            predicted_popularity="cold"
        )
        file_id = saved["file_id"]

        # Simulate heavy accesses to turn it hot
        for _ in range(35):
            get_file(file_id, simulate_delay=False)

        # Run dynamic migration
        migration_res = evaluate_and_migrate_all_files(policy="ml")
        self.assertIn("migrations_performed", migration_res)

        # Check updated file record
        updated = db.query_one("SELECT current_node_id, predicted_popularity FROM files WHERE file_id = ?", (file_id,))
        self.assertEqual(updated["predicted_popularity"], "hot")
        self.assertEqual(updated["current_node_id"], "node1")

        # Clean up
        delete_file(file_id)

    def test_05_flask_api_endpoints(self):
        client = app.test_client()

        # 1. Status endpoint
        resp = client.get("/api/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("nodes", data)
        self.assertIn("summary", data)

        # 2. Upload endpoint
        upload_resp = client.post(
            "/api/files",
            data={
                "file": (io.BytesIO(b"Hello world from Flask API test"), "api_test.txt"),
                "policy": "ml"
            },
            content_type="multipart/form-data"
        )
        self.assertEqual(upload_resp.status_code, 201)
        upload_data = upload_resp.get_json()
        file_id = upload_data["file"]["file_id"]

        # 3. Access endpoint
        acc_resp = client.post(f"/api/files/{file_id}/access")
        self.assertEqual(acc_resp.status_code, 200)

        # 4. Benchmark endpoint
        bench_resp = client.post("/api/benchmark", json={"requests": 10})
        self.assertEqual(bench_resp.status_code, 200)

        # 5. Delete file
        del_resp = client.delete(f"/api/files/{file_id}")
        self.assertEqual(del_resp.status_code, 200)

    def test_06_user_portal_and_network_info(self):
        client = app.test_client()
        resp = client.get("/user")
        self.assertEqual(resp.status_code, 200)

        net_resp = client.get("/api/network-info")
        self.assertEqual(net_resp.status_code, 200)
        net_data = net_resp.get_json()
        self.assertIn("host_ip", net_data)
        self.assertIn("user_url", net_data)


if __name__ == "__main__":
    unittest.main()

