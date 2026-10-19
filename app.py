import os
import sys
import queue
import random
import socket
import uuid
from io import BytesIO
from mimetypes import guess_type
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_file, Response
from werkzeug.utils import secure_filename

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from database import db
from services.file_service import (
    save_file, get_file, delete_file, get_all_files, get_all_storage_nodes, ensure_storage_directories
)
from services.access_logger import get_recent_access_logs, get_file_access_stats
from services.event_broker import broker
from placement.placement_controller import (
    determine_placement, evaluate_and_migrate_file, evaluate_and_migrate_all_files,
    run_benchmark_simulation, NODE_METADATA
)
from ml.train_model import train_placement_model
from ml.predict import load_model
from ml.dataset import FEATURE_COLUMNS

app = Flask(__name__)
app.config["SECRET_KEY"] = config.SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = config.UPLOAD_MAX_SIZE

# Initialize database and storage directories on startup
with app.app_context():
    db.init_db()
    ensure_storage_directories()


def get_host_ip():
    """Detect LAN/local IP address to allow other devices to connect."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


@app.route("/")
@app.route("/admin")
def dashboard():
    """Serve the unchanged dashboard file with its live backend adapter."""
    dashboard_path = os.path.join(config.BASE_DIR, "datapilot-dashboard.html")
    with open(dashboard_path, "r", encoding="utf-8") as dashboard_file:
        dashboard_html = dashboard_file.read()

    live_script = '<script src="/static/live-pipeline.js"></script>'
    dashboard_html = dashboard_html.replace("</body>", f"{live_script}</body>", 1)
    return Response(dashboard_html, mimetype="text/html")


@app.route("/user")
@app.route("/upload")
def user_portal():
    """Render the user-facing upload client interface."""
    return render_template("user.html")


@app.route("/api/network-info", methods=["GET"])
def get_network_info():
    """Retrieve host IP and network connection URLs for multi-system access."""
    ip = get_host_ip()
    return jsonify({
        "host_ip": ip,
        "port": 5000,
        "admin_url": f"http://{ip}:5000/",
        "user_url": f"http://{ip}:5000/upload"
    })


@app.route("/api/events")
def sse_events():
    """
    Server-Sent Events (SSE) endpoint.
    Streams real-time events (uploads, access events, dynamic migrations)
    to any connected admin dashboard across the network.
    """
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    q = broker.subscribe()

    def stream():
        try:
            # Initial connection acknowledgement
            init_payload = {
                "status": "connected",
                "client_ip": client_ip,
                "timestamp": datetime.now().isoformat()
            }
            yield f"event: connected\ndata: {jsonify(init_payload).get_data(as_text=True)}\n\n"
            while True:
                try:
                    msg = q.get(timeout=20)
                    yield msg
                except queue.Empty:
                    # Heartbeat keepalive comment
                    yield ": heartbeat\n\n"
        finally:
            broker.unsubscribe(q)

    return Response(
        stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive"
        }
    )


@app.route("/api/status", methods=["GET"])
def get_system_status():
    """Retrieve overview metrics and storage node status."""
    nodes = get_all_storage_nodes()
    files = get_all_files()
    logs = get_recent_access_logs(limit=20)
    
    total_files = len(files)
    total_used_bytes = sum(n.get("used_bytes", 0) for n in nodes)
    total_capacity_bytes = sum(n.get("capacity_bytes", 0) for n in nodes)
    
    avg_lat_res = db.query_one("SELECT AVG(response_time_ms) as avg_lat FROM access_logs")
    overall_avg_lat = round(avg_lat_res["avg_lat"], 2) if avg_lat_res and avg_lat_res["avg_lat"] else 0.0

    model = load_model()
    return jsonify({
        "status": "healthy",
        "model": {
            "algorithm": "Random Forest Classifier",
            "ready": True,
            "artifact_version": config.MODEL_ARTIFACT_VERSION,
            "classes": [str(label) for label in getattr(model, "classes_", [])],
            "features": FEATURE_COLUMNS,
            "training_source": "synthetic access-history bootstrap; live access history is used for inference",
        },
        "nodes": nodes,
        "summary": {
            "total_files": total_files,
            "total_used_bytes": total_used_bytes,
            "total_capacity_bytes": total_capacity_bytes,
            "overall_utilization_pct": round((total_used_bytes / total_capacity_bytes) * 100, 2) if total_capacity_bytes > 0 else 0,
            "avg_latency_ms": overall_avg_lat,
            "total_access_logs": db.query_one("SELECT COUNT(*) as cnt FROM access_logs")["cnt"],
            "active_sse_clients": broker.client_count
        },
        "recent_logs": logs
    })


@app.route("/api/files", methods=["GET", "POST"])
def handle_files():
    """GET list of files or POST upload a new file via Machine Learning placement."""
    if request.method == "POST":
        if "file" not in request.files:
            return jsonify({"error": "No file part in request"}), 400
        
        uploaded_file = request.files["file"]
        if uploaded_file.filename == "":
            return jsonify({"error": "No file selected"}), 400

        filename = secure_filename(uploaded_file.filename)
        if not filename:
            filename = f"upload_{int(datetime.now().timestamp())}.dat"

        source = request.form.get("source", "user")
        client_ip = request.headers.get("X-Forwarded-For", request.remote_addr)
        
        # Read content to measure size
        content = uploaded_file.read()
        file_size = len(content)
        pipeline_id = uuid.uuid4().hex
        pipeline_started_at = datetime.now().isoformat()

        def publish_pipeline_stage(stage, **details):
            broker.broadcast("pipeline_stage", {
                "pipeline_id": pipeline_id,
                "started_at": pipeline_started_at,
                "stage": stage,
                "filename": filename,
                "file_size": file_size,
                "source": source,
                "client_ip": client_ip,
                **details,
                "timestamp": datetime.now().isoformat(),
            })

        publish_pipeline_stage("received")
        publish_pipeline_stage("metadata", features={"file_size": file_size})

        try:
            # Exclusively Machine Learning placement decision
            decision = determine_placement(
                filename=filename,
                file_size=file_size,
                policy="ml"
            )
            target_node = decision["node_id"]
            predicted_pop = decision["predicted_popularity"]

            publish_pipeline_stage(
                "model",
                tier=predicted_pop,
                confidence=decision.get("confidence", 0.0),
                probabilities=decision.get("probabilities", {}),
                features=decision.get("features", {}),
            )
            publish_pipeline_stage(
                "placement",
                tier=predicted_pop,
                target_node=target_node,
                target_node_name=decision.get("target_node_name", target_node),
                confidence=decision.get("confidence", 0.0),
                probabilities=decision.get("probabilities", {}),
            )

            publish_pipeline_stage(
                "storing",
                tier=predicted_pop,
                target_node=target_node,
                target_node_name=decision.get("target_node_name", target_node),
                confidence=decision.get("confidence", 0.0),
                probabilities=decision.get("probabilities", {}),
            )

            saved_record = save_file(
                file_data=content,
                filename=filename,
                target_node_id=target_node,
                policy="ml",
                predicted_popularity=predicted_pop
            )

            publish_pipeline_stage(
                "stored",
                file_id=saved_record["file_id"],
                tier=predicted_pop,
                target_node=target_node,
                target_node_name=decision.get("target_node_name", target_node),
                confidence=decision.get("confidence", 0.0),
                probabilities=decision.get("probabilities", {}),
                features=decision.get("features", {}),
            )

            # Broadcast real-time event to all connected admin dashboards
            upload_event_data = {
                "pipeline_id": pipeline_id,
                "file_id": saved_record["file_id"],
                "filename": filename,
                "file_size": file_size,
                "target_node": target_node,
                "target_node_name": decision.get("target_node_name", target_node),
                "tier": predicted_pop,
                "confidence": decision.get("confidence", 1.0),
                "probabilities": decision.get("probabilities", {}),
                "features": decision.get("features", {}),
                "reason": decision.get("reason", "ML Model placement"),
                "client_ip": client_ip,
                "source": source,
                "timestamp": datetime.now().isoformat()
            }
            broker.broadcast("file_uploaded", upload_event_data)

            return jsonify({
                "message": f"File '{filename}' placed on {target_node} ({predicted_pop.upper()} tier) by ML model",
                "file": saved_record,
                "placement_decision": decision,
                "client_ip": client_ip
            }), 201

        except Exception as e:
            publish_pipeline_stage("failed", error=str(e))
            return jsonify({"error": str(e)}), 500

    # GET
    files = get_all_files()
    return jsonify({"files": files})


@app.route("/api/files/<int:file_id>/access", methods=["POST", "GET"])
def access_file_endpoint(file_id):
    """Log a read, then let the ML model re-evaluate and migrate the file if needed."""
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    file_record, _, latency = get_file(file_id, simulate_delay=True, access_type="read")
    if not file_record:
        return jsonify({"error": "File not found"}), 404

    evaluation = evaluate_and_migrate_file(file_id, policy="ml")
    current_file = evaluation["file"]
    decision = evaluation["decision"]
    accessed_node = file_record["current_node_id"]

    access_event_data = {
        "file_id": file_id,
        "filename": file_record["filename"],
        "node_id": accessed_node,
        "node_name": NODE_METADATA.get(accessed_node, {}).get("name", accessed_node),
        "tier": NODE_METADATA.get(accessed_node, {}).get("tier", "unknown"),
        "current_node": current_file["current_node_id"],
        "latency_ms": latency,
        "access_count": file_record.get("access_count", 0) + 1,
        "new_predicted_popularity": decision["predicted_popularity"],
        "confidence": decision["confidence"],
        "probabilities": decision["probabilities"],
        "features": decision["features"],
        "migrated": bool(evaluation["migration"] and evaluation["migration"]["success"]),
        "client_ip": client_ip,
        "timestamp": datetime.now().isoformat()
    }

    # Broadcast real-time access event to admin dashboard
    broker.broadcast("file_accessed", access_event_data)

    return jsonify({
        "filename": file_record["filename"],
        "message": f"File {file_record['filename']} retrieved from {accessed_node}",
        "latency_ms": latency,
        "accessed_node": accessed_node,
        "current_node": current_file["current_node_id"],
        "new_predicted_popularity": decision["predicted_popularity"],
        "confidence": decision["confidence"],
        "probabilities": decision["probabilities"],
        "features": decision["features"],
        "migration": evaluation["migration"]
    })


@app.route("/api/files/<int:file_id>/download", methods=["GET"])
def download_file_endpoint(file_id):
    """Download a file, then re-evaluate its tier using the newly logged access."""
    file_record, file_path, _ = get_file(file_id, simulate_delay=False, access_type="download")
    if not file_record or not os.path.exists(file_path):
        return jsonify({"error": "File not found on storage node"}), 404

    with open(file_path, "rb") as stored_file:
        payload = stored_file.read()
    response = send_file(
        BytesIO(payload),
        mimetype=guess_type(file_record["filename"])[0] or "application/octet-stream",
        as_attachment=True,
        download_name=file_record["filename"]
    )
    evaluation = evaluate_and_migrate_file(file_id, policy="ml")
    if evaluation:
        decision = evaluation["decision"]
        broker.broadcast("file_accessed", {
            "file_id": file_id,
            "filename": file_record["filename"],
            "node_id": file_record["current_node_id"],
            "current_node": evaluation["file"]["current_node_id"],
            "new_predicted_popularity": decision["predicted_popularity"],
            "confidence": decision["confidence"],
            "probabilities": decision["probabilities"],
            "features": decision["features"],
            "access_type": "download",
            "migrated": bool(evaluation["migration"] and evaluation["migration"]["success"]),
            "timestamp": datetime.now().isoformat(),
        })
    return response


@app.route("/api/files/<int:file_id>", methods=["DELETE"])
def delete_file_endpoint(file_id):
    """Delete a file from system and broadcast event."""
    file_row = db.query_one("SELECT filename, current_node_id FROM files WHERE file_id = ?", (file_id,))
    success = delete_file(file_id)
    if not success:
        return jsonify({"error": "File could not be deleted"}), 404

    if file_row:
        broker.broadcast("file_deleted", {
            "file_id": file_id,
            "filename": file_row["filename"],
            "node_id": file_row["current_node_id"],
            "timestamp": datetime.now().isoformat()
        })

    return jsonify({"message": "File deleted successfully"})


@app.route("/api/migrate", methods=["POST"])
def trigger_migration():
    """Trigger dynamic re-evaluation and migration for all files via ML model."""
    res = evaluate_and_migrate_all_files(policy="ml")
    return jsonify(res)


@app.route("/api/train", methods=["POST"])
def trigger_model_training():
    """Retrain the machine learning placement model."""
    data = request.get_json() or {}
    use_synthetic = data.get("use_synthetic", True)
    try:
        metrics = train_placement_model(use_synthetic=use_synthetic)
        load_model(force_reload=True)
        broker.broadcast("model_trained", {
            "metrics": metrics,
            "accuracy": metrics.get("accuracy", 0.0),
            "timestamp": datetime.now().isoformat()
        })
        return jsonify({
            "message": "Model trained successfully",
            "metrics": metrics
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400 if isinstance(e, ValueError) else 500


@app.route("/api/benchmark", methods=["POST"])
def run_benchmark():
    """Run benchmark simulation under current ML placement policy."""
    data = request.get_json() or {}
    num_requests = int(data.get("requests", 50))
    result = run_benchmark_simulation(num_requests=num_requests)
    return jsonify(result)


@app.route("/api/seed-demo", methods=["POST"])
def seed_demo_data():
    """Populate sample files and unlabelled access histories for demonstration."""
    sample_files = [
        ("user_profile_avatars.zip", 2 * 1024 * 1024),
        ("realtime_index.bin", 512 * 1024),
        ("daily_session_cache.db", 4 * 1024 * 1024),
        ("system_logs_2026_09.tar.gz", 25 * 1024 * 1024),
        ("historical_archive_2025.iso", 45 * 1024 * 1024),
        ("monthly_compliance_report.pdf", 8 * 1024 * 1024),
        ("product_catalog.json", 1 * 1024 * 1024),
        ("analytics_summary.csv", 3 * 1024 * 1024),
        ("landing_page_banner.png", 650 * 1024),
        ("customer_invoices_batch.pdf", 12 * 1024 * 1024),
    ]

    created = []
    access_counts = (0, 1, 2, 5, 10, 20, 40)
    access_weights = (4, 4, 3, 2, 1, 1, 1)
    for fname, size in sample_files:
        dummy_content = b"0" * size
        decision = determine_placement(fname, size, policy="ml")
        
        file_rec = save_file(
            file_data=dummy_content,
            filename=fname,
            target_node_id=decision["node_id"],
            policy="ml",
            predicted_popularity=decision["predicted_popularity"]
        )

        accesses = random.choices(access_counts, weights=access_weights, k=1)[0]
        for _ in range(accesses):
            get_file(file_rec["file_id"], simulate_delay=False)

        created.append(fname)

    evaluate_and_migrate_all_files(policy="ml")

    return jsonify({
        "message": f"Successfully seeded {len(created)} demonstration files and access logs.",
        "files": created
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=config.DEBUG, threaded=True)
