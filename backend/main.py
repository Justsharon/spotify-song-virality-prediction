from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field, create_model

import db
import util


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    db.purge_expired()
    yield


app = FastAPI(
    title="Spotify Song Virality Prediction API",
    description="Predict whether a song will go viral based on its audio features.",
    version="1.1.0",
    lifespan=lifespan,
)

Genre = Literal[tuple(util.GENRES)]

SongFeatures = create_model(
    "SongFeatures",
    genre=(Genre, Field(..., description="Track genre")),
    release_year=(int, Field(..., ge=2010, le=2025, description="Year the song was released")),
    duration_sec=(int, Field(..., gt=0, description="Track duration in seconds")),
    danceability=(float, Field(..., ge=0, le=1, description="How suitable a track is for dancing")),
    energy=(float, Field(..., ge=0, le=1, description="Perceptual measure of intensity")),
    valence=(float, Field(..., ge=0, le=1, description="Musical positivity / mood")),
    tempo_bpm=(float, Field(..., gt=0, description="Overall tempo in beats per minute")),
    acousticness=(float, Field(..., ge=0, le=1, description="Likelihood the track is acoustic")),
    instrumentalness=(float, Field(..., ge=0, le=1, description="Presence of vocals likelihood inverse")),
    speechiness=(float, Field(..., ge=0, le=1, description="Presence of spoken words")),
    liveness=(float, Field(..., ge=0, le=1, description="Presence of an audience")),
    loudness_db=(float, Field(..., le=0, description="Overall loudness in decibels")),
    streams=(int, Field(..., ge=0, description="Total stream count")),
)


class PredictionResponse(BaseModel):
    is_viral: bool
    label: str
    viral_probability: float = Field(..., description="Probability that the song is viral (0-1)")
    cached: bool = Field(False, description="Whether the result was served from the cache")


class BatchPredictionRequest(BaseModel):
    songs: list[SongFeatures] = Field(..., min_length=1, max_length=100)


class BatchPredictionResponse(BaseModel):
    predictions: list[PredictionResponse]


class PredictionRecord(BaseModel):
    id: int
    created_at: float
    genre: str
    is_viral: bool
    viral_probability: float
    served_from_cache: bool
    model_latency_ms: float


def _ensure_known_genre(song: SongFeatures) -> None:
    if song.genre not in util.GENRES:
        raise HTTPException(status_code=422, detail=f"Unknown genre: {song.genre}")


@app.get("/")
def root():
    return {"message": "Spotify Song Virality Prediction API", "docs": "/docs"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/genres", response_model=list[str])
def genres():
    return util.GENRES


@app.post("/predict", response_model=PredictionResponse)
def predict(song: SongFeatures):
    _ensure_known_genre(song)
    try:
        return util.predict_with_cache([song.model_dump()])[0]
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/predict/batch", response_model=BatchPredictionResponse)
def predict_batch(request: BatchPredictionRequest):
    for song in request.songs:
        _ensure_known_genre(song)
    try:
        results = util.predict_with_cache([song.model_dump() for song in request.songs])
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"predictions": results}


@app.get("/cache/stats")
def cache_stats():
    return db.cache_stats()


@app.delete("/cache")
def clear_cache():
    removed = db.clear_cache()
    return {"cleared": removed}


@app.post("/cache/purge")
def purge_cache():
    removed = db.purge_expired()
    return {"purged": removed}


@app.get("/history", response_model=list[PredictionRecord])
def history(limit: int = Query(20, ge=1, le=100)):
    return db.recent_predictions(limit)


@app.get("/history/stats")
def history_stats():
    return db.prediction_stats()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8080)
