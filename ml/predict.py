import os
import sys
import joblib
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from ml.dataset import FEATURE_COLUMNS, extract_features_for_file

_MODEL_CACHE = None


def load_model(force_reload=False):
    """Load the trained machine learning model from disk."""
    global _MODEL_CACHE
    if _MODEL_CACHE is not None and not force_reload:
        return _MODEL_CACHE

    artifact = joblib.load(config.MODEL_PATH) if os.path.exists(config.MODEL_PATH) else None
    if not (
        isinstance(artifact, dict)
        and artifact.get("version") == config.MODEL_ARTIFACT_VERSION
        and "pipeline" in artifact
    ):
        # Rebuild missing or legacy artifacts from the current feature/training pipeline.
        from ml.train_model import train_placement_model
        train_placement_model()
        artifact = joblib.load(config.MODEL_PATH)

    _MODEL_CACHE = artifact["pipeline"]
    return _MODEL_CACHE


def predict_popularity(features_dict):
    """
    Predict popularity ('hot', 'warm', 'cold') and class probabilities
    from a features dictionary.
    """
    model = load_model()
    df = pd.DataFrame([features_dict])[FEATURE_COLUMNS]
    prediction = str(model.predict(df)[0])
    
    probabilities = {}
    if hasattr(model, "predict_proba"):
        probs = model.predict_proba(df)[0]
        classes = [str(cls) for cls in model.classes_]
        probabilities = {cls: round(float(p), 3) for cls, p in zip(classes, probs)}
    
    confidence = probabilities.get(prediction, 1.0)
    return {
        "predicted_popularity": prediction,
        "confidence": confidence,
        "probabilities": probabilities
    }


def predict_for_file(file_id):
    """
    Extract live features for a given file_id from database and predict popularity.
    """
    features = extract_features_for_file(file_id)
    if not features:
        raise ValueError(f"Cannot predict popularity: file {file_id} was not found.")

    res = predict_popularity(features)
    res["features"] = features
    return res


def recommend_node_for_tier(popularity):
    """Map popularity classification to target storage node."""
    tier_mapping = {
        "hot": "node1",    # Hot / NVMe SSD
        "warm": "node2",   # Warm / Standard SSD
        "cold": "node3"    # Cold / HDD Archive
    }
    try:
        return tier_mapping[popularity.lower()]
    except (AttributeError, KeyError):
        raise ValueError(f"Unsupported ML popularity class: {popularity!r}")
