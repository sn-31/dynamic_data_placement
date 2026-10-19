# AI-Driven Dynamic Data Placement in Cloud Distributed File Systems Using Machine Learning

## Project Overview

This project simulates ML-based placement and migration for a tiered distributed file system. A Random Forest Classifier predicts whether a file is `hot`, `warm`, or `cold` and maps that prediction to a storage node.

At upload, the system knows the file size but has no access history, so it starts with a cold-start feature vector. Every read and download is logged. After serving an access, the model re-evaluates the file from its observed history and migrates it when the recommended node changes.

### Key Highlights

- **ML-Only Placement Flow**: Upload and migration decisions use the Random Forest prediction, with a capacity check before writing or moving files.
- **Two Separate Views**: Users get a focused upload page (`/upload`); administrators monitor files and storage on `/admin`.
- **Live Placement Animation**: The Admin Dashboard animates each upload through **User Upload ➔ Metadata ➔ ML Model ➔ Placement Controller ➔ Selected Storage Node**.
- **Shareable Upload Link**: Copy the user upload URL from the admin dashboard and send it to users on the same reachable host/network.
- **Server-Sent Events (SSE)**: Instant, zero-polling real-time push telemetry across the local network.
- **Access Feedback Loop**: Reads and downloads update the access history, trigger inference, and can promote or demote a file automatically.

---

## Architecture

```text
[ User Upload ] ─► [ Metadata DB ] ─► [ Random Forest ] ─► [ Placement Controller ] ─► [ Storage Nodes ]
                                           ▲                                         │
                                           └──────── [ Access History ] ◄─ [ Read / Download Monitor ]
```

### Storage Tiers

| Node | Name | Tier | Capacity | Latency | Target Workload |
|---|---|---|---|---|---|
| **Node 1** | Hot NVMe SSD | `hot` | 100 MB | ~5 ms | High-frequency streaming, cache, real-time index |
| **Node 2** | Standard SSD | `warm` | 300 MB | ~25 ms | Balanced working documents, JSON/CSV data |
| **Node 3** | HDD Archive | `cold` | 1000 MB | ~120 ms | Infrequent backups, ISO images, compressed tarballs |

---

## Machine Learning Pipeline

- **Algorithm**: Scikit-Learn `RandomForestClassifier` (100 estimators, balanced class weights).
- **Features Extracted**:
  1. `file_size`: Size in bytes.
  2. `access_count`: Total lifetime accesses.
  3. `recent_access_1h`: Accesses in the last 1 hour.
  4. `recent_access_24h`: Accesses in the last 24 hours.
  5. `hours_since_last_access`: Elapsed time since previous access.
  6. `accesses_per_day`: Access velocity over file lifespan.
- **Bootstrap data**: The model can bootstrap from synthetic access histories with sampled latent popularity classes. Its validation score describes that synthetic dataset and is not a real-world accuracy claim.
- **Live inference**: Observed reads and downloads are used as model features. They are not assigned training labels by hand; supervised retraining from real data requires ground-truth labels.

---

## Multi-System Setup & Demonstration

### 1. Start the Server

```bash
source venv/bin/activate
python app.py
```

The application runs on `0.0.0.0:5000`.

### 2. Open the Admin Dashboard (System A)

Open in your browser on the host system:
```text
http://localhost:5000/
```
Or across your local network:
```text
http://<HOST_IP>:5000/
```

### 3. Share the User Upload Page (System B / Phone / Other Browser)

Copy the upload link from the **Share the user upload page** panel on the Admin Dashboard, or open it directly on another laptop or phone connected to the same Wi-Fi/LAN:
```text
http://<HOST_IP>:5000/upload
```

When the dashboard is opened through `localhost`, it detects the host's local network address for the copied link.

### 4. Watch the Real-Time Animation

1. On the **User Upload Page**, choose a file and upload it.
2. The Admin Dashboard animates that upload through metadata extraction, ML inference, node selection, and storage. The stored file appears in the admin file list.
3. On the admin dashboard, access or download the file to create access history. The next prediction uses observed access features and may move the file to a different tier.

---

## Project Structure

```text
dynamic_data_placement/
├── app.py                     # Flask web app & SSE streaming endpoints
├── config.py                  # Node definitions and configuration
├── requirements.txt           # Project dependencies
├── database/
│   ├── db.py                  # Database abstraction layer
│   └── schema.sql             # Relational schema
├── storage/                   # Simulated physical storage nodes
│   ├── node1/                 # Hot NVMe tier
│   ├── node2/                 # Warm SSD tier
│   └── node3/                 # Cold HDD tier
├── ml/
│   ├── dataset.py             # Feature engineering & synthetic access-history generator
│   ├── train_model.py         # Model training script
│   └── predict.py             # Model inference & prediction cache
├── placement/
│   └── placement_controller.py# ML placement engine & dynamic migration
├── datapilot-dashboard.html  # Admin dashboard served by Flask at / and /admin
├── services/
│   ├── file_service.py        # File I/O & storage operations
│   ├── access_logger.py       # Access tracking & latency metrics
│   └── event_broker.py        # Real-time Server-Sent Events broker
├── templates/
│   └── user.html                # Dedicated user client portal
└── static/
    ├── datapilot-dashboard.js  # Live data, upload, access, and migration dashboard
    ├── style.css               # Client portal styling
    └── user.js                 # User client portal scripts
```

---

## Running Automated Tests

```bash
python -m unittest discover -s tests -p "test_*.py"
```

---

## Retraining the ML Model

```bash
python ml/train_model.py
```
Or click **"Retrain bootstrap model"** on the Admin Dashboard. The current application has no ground-truth popularity labels for live files, so this button retrains on synthetic access histories.
