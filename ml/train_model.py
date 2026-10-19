import os
import sys
import joblib
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, accuracy_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from ml.dataset import generate_synthetic_workload, FEATURE_COLUMNS


def train_placement_model(use_synthetic=True, n_samples=1500):
    """
    Train a Random Forest classifier to predict file popularity (hot, warm, cold).
    Saves the serialized model pipeline to disk.
    """
    print("Collecting training data...")
    if not use_synthetic:
        raise ValueError(
            "Access history has no ground-truth popularity labels. "
            "Provide labeled training examples before training from live data."
        )
    df = generate_synthetic_workload(num_files=n_samples)

    X = df[FEATURE_COLUMNS]
    y = df["popularity"]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    print(f"Training on {len(X_train)} samples, testing on {len(X_test)} samples...")

    pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("classifier", RandomForestClassifier(
            n_estimators=100,
            max_depth=8,
            random_state=42,
            class_weight="balanced"
        ))
    ])

    pipeline.fit(X_train, y_train)

    y_pred = pipeline.predict(X_test)
    acc = accuracy_score(y_test, y_pred)
    report = classification_report(y_test, y_pred, output_dict=True)

    rf_model = pipeline.named_steps["classifier"]
    feature_importances = dict(zip(FEATURE_COLUMNS, [round(float(v), 4) for v in rf_model.feature_importances_]))

    # Ensure parent dir exists
    os.makedirs(os.path.dirname(config.MODEL_PATH), exist_ok=True)
    joblib.dump({
        "version": config.MODEL_ARTIFACT_VERSION,
        "pipeline": pipeline,
        "training_source": "synthetic access-history bootstrap",
    }, config.MODEL_PATH)
    print(f"Model saved to {config.MODEL_PATH} with test accuracy: {acc * 100:.2f}%")

    return {
        "accuracy": round(float(acc), 4),
        "total_samples": len(df),
        "train_samples": len(X_train),
        "test_samples": len(X_test),
        "feature_importances": feature_importances,
        "classification_report": report
    }


if __name__ == "__main__":
    result = train_placement_model(use_synthetic=True, n_samples=2000)
    print("Model Training Result:")
    print(f"Accuracy: {result['accuracy'] * 100:.2f}%")
    print(f"Feature Importances: {result['feature_importances']}")
