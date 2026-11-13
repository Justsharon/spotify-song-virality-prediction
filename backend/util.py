import hashlib
import json
import pickle
import time
from functools import lru_cache
from pathlib import Path

import pandas as pd

import db

BACKEND_DIR = Path(__file__).resolve().parent
ARTIFACT_DIRS = (BACKEND_DIR / "artifacts", BACKEND_DIR.parent / "model")

GENRES = [
    "Classical",
    "Country",
    "Electronic",
    "Hip-Hop",
    "Indie",
    "Jazz",
    "Latin",
    "Pop",
    "R&B",
    "Rock",
]

NUMERIC_FEATURES = [
    "release_year",
    "duration_sec",
    "danceability",
    "energy",
    "valence",
    "tempo_bpm",
    "acousticness",
    "instrumentalness",
    "speechiness",
    "liveness",
    "loudness_db",
    "streams",
]


def _find_artifact(filename: str) -> Path:
    for directory in ARTIFACT_DIRS:
        candidate = directory / filename
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"'{filename}' not found in {[str(d) for d in ARTIFACT_DIRS]}"
    )


@lru_cache(maxsize=1)
def get_model():
    with open(_find_artifact("spotify-virality.pickle"), "rb") as f:
        return pickle.load(f)


@lru_cache(maxsize=1)
def get_feature_columns() -> list[str]:
    with open(_find_artifact("columns.json")) as f:
        return json.load(f)["data_columns"]


def get_genres() -> list[str]:
    encoder = get_model().named_steps["preprocessor"].named_transformers_["cat"].named_steps["encoder"]
    categories = encoder.categories_[0]
    return sorted(str(category) for category in categories)


def to_dataframe(records: list[dict]) -> pd.DataFrame:
    columns = get_feature_columns()
    return pd.DataFrame(records, columns=columns)


def predict_viral(records: list[dict]) -> list[dict]:
    model = get_model()
    frame = to_dataframe(records)
    labels = model.predict(frame)
    probabilities = model.predict_proba(frame)[:, 1]

    results = []
    for label, probability in zip(labels, probabilities):
        results.append(
            {
                "is_viral": bool(label),
                "viral_probability": round(float(probability), 4),
                "label": "Viral" if int(label) == 1 else "Non-Viral",
            }
        )
    return results


def cache_key(record: dict) -> str:
    canonical = json.dumps(
        {column: record.get(column) for column in get_feature_columns()},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def predict_with_cache(records: list[dict], ttl: int = db.CACHE_TTL_SECONDS) -> list[dict]:
    keys = [cache_key(record) for record in records]
    results: list[dict | None] = [None] * len(records)
    misses: list[int] = []

    for index, key in enumerate(keys):
        cached = db.get_cached(key, ttl)
        if cached is not None:
            results[index] = {**cached, "cached": True}
        else:
            misses.append(index)

    if misses:
        started = time.perf_counter()
        fresh = predict_viral([records[index] for index in misses])
        latency_ms = (time.perf_counter() - started) * 1000

        for index, prediction in zip(misses, fresh):
            response = {**prediction, "cached": False}
            results[index] = response
            db.set_cached(keys[index], prediction, str(records[index]["genre"]), ttl)
            db.record_prediction(
                keys[index],
                str(records[index]["genre"]),
                response,
                records[index],
                served_from_cache=False,
                model_latency_ms=latency_ms / len(misses),
            )

    for index, key in enumerate(keys):
        if results[index] is not None and results[index]["cached"]:
            db.record_prediction(
                key,
                str(records[index]["genre"]),
                results[index],
                records[index],
                served_from_cache=True,
            )

    return [result for result in results if result is not None]
