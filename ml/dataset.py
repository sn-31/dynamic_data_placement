import os
import sys
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import db


FEATURE_COLUMNS = [
    "file_size",
    "access_count",
    "recent_access_1h",
    "recent_access_24h",
    "hours_since_last_access",
    "accesses_per_day"
]


def generate_synthetic_workload(num_files=1000, random_seed=42):
    """
    Generate synthetic access histories for bootstrapping the classifier.

    Popularity is a latent class sampled before feature generation. The model
    learns from the resulting access measurements instead of labels assigned
    by thresholds over those same measurements.
    """
    np.random.seed(random_seed)

    file_sizes = np.random.lognormal(mean=11.0, sigma=1.8, size=num_files).astype(int)
    file_sizes = np.clip(file_sizes, 1024, 50 * 1024 * 1024)
    file_ages_days = np.random.uniform(1.0, 30.0, size=num_files)
    latent_popularity = np.random.choice(
        ["hot", "warm", "cold"], size=num_files, p=[0.20, 0.30, 0.50]
    )
    daily_rates = {"hot": 18.0, "warm": 2.0, "cold": 0.12}

    data = []
    for i in range(num_files):
        age = file_ages_days[i]
        size = int(file_sizes[i])
        label = str(latent_popularity[i])
        rate = daily_rates[label]
        total_acc = int(np.random.poisson(rate * age))

        # Include new or untouched files, which have no prior access history.
        if label == "cold" and np.random.random() < 0.35:
            total_acc = 0
        elif label != "cold" and total_acc == 0:
            total_acc = 1

        if total_acc == 0:
            recent_24h = 0
            recent_1h = 0
            hours_since_last = 0.0
            acc_per_day = 0.0
        else:
            recent_24h = min(total_acc, int(np.random.poisson(rate)))
            recent_1h = min(recent_24h, int(np.random.poisson(rate / 24.0)))
            hours_since_last = min(age * 24.0, float(np.random.exponential(24.0 / rate)))
            acc_per_day = total_acc / max(1.0, age)

        data.append({
            "file_size": size,
            "access_count": total_acc,
            "recent_access_1h": recent_1h,
            "recent_access_24h": recent_24h,
            "hours_since_last_access": round(hours_since_last, 2),
            "accesses_per_day": round(acc_per_day, 2),
            "popularity": label
        })

    return pd.DataFrame(data)


def extract_features_for_file(file_id):
    """
    Extract live feature vector for a specific file from the active database.
    """
    file_row = db.query_one("SELECT * FROM files WHERE file_id = ?", (file_id,))
    if not file_row:
        return None

    now = datetime.now()
    created_at = datetime.fromisoformat(str(file_row["created_at"]).replace("Z", ""))
    days_alive = max(1.0, (now - created_at).total_seconds() / 86400.0)
    access_count = file_row["access_count"]

    if access_count:
        last_accessed_at = datetime.fromisoformat(str(file_row["last_accessed_at"]).replace("Z", ""))
        hours_since_last = max(0.0, (now - last_accessed_at).total_seconds() / 3600.0)
    else:
        # Zero is the trained cold-start sentinel for files with no observations.
        hours_since_last = 0.0

    # Count accesses in last 1h and 24h
    one_hour_ago = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    twenty_four_hours_ago = (now - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")

    res_1h = db.query_one(
        "SELECT COUNT(*) as cnt FROM access_logs WHERE file_id = ? AND accessed_at >= ?",
        (file_id, one_hour_ago)
    )
    recent_1h = res_1h["cnt"] if res_1h else 0

    res_24h = db.query_one(
        "SELECT COUNT(*) as cnt FROM access_logs WHERE file_id = ? AND accessed_at >= ?",
        (file_id, twenty_four_hours_ago)
    )
    recent_24h = res_24h["cnt"] if res_24h else 0

    accesses_per_day = access_count / days_alive

    return {
        "file_size": file_row["file_size"],
        "access_count": access_count,
        "recent_access_1h": recent_1h,
        "recent_access_24h": recent_24h,
        "hours_since_last_access": round(hours_since_last, 2),
        "accesses_per_day": round(accesses_per_day, 2)
    }
