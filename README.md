# Spotify Song Virality

A full-stack app that predicts whether a song will go **viral** from its audio features and streaming stats. Enter a track profile in the UI (or call the API) and a trained logistic-regression model returns a viral verdict with a probability, backed by a SQLite cache so repeat requests are near-instant.

```
┌──────────────┐      /api/*       ┌─────────────────┐      ┌────────────────────┐
│  SvelteKit   │ ────────────────► │  FastAPI        │ ───► │  scikit-learn      │
│  + Tailwind  │  (Vite dev proxy) │  backend        │      │  pipeline (.pickle)│
│  UI (5173)   │ ◄──────────────── │  (8080)         │ ◄─── │  LogisticRegression│
└──────────────┘   JSON prediction └────────┬────────┘      └────────────────────┘
                                            │
                                   ┌────────┴─────────┐
                                   │  SQLite          │
                                   │  ├─ cache.db     │  fast repeat lookups
                                   │  └─ virality.db  │  prediction history
                                   └──────────────────┘
```

## Features

- **Prediction API** — single and batch endpoints with strict input validation.
- **Probability, not just a label** — every response carries the model's viral probability.
- **Two-tier SQLite storage** — a TTL cache for fast repeat requests and a history log of every prediction.
- **Matte-blue/black UI** — genre select, guided audio-feature sliders, presets, and an animated verdict card that shows when a result came from cache.
- **Reproducible model** — the training notebook and serialized pipeline live in `model/`.

## Repository layout

```
.
├── model/                    # Training notebook + serialized artifacts
│   ├── spotify.ipynb         # EDA, preprocessing, training, evaluation
│   ├── spotify-virality.pickle
│   └── columns.json          # Ordered feature columns the model expects
├── backend/
│   ├── main.py               # FastAPI app, request models, routes
│   ├── util.py               # Model loading, cache key, prediction orchestration
│   ├── db.py                 # SQLite cache + history, background writer
│   └── artifacts/            # Copy of the model used at runtime
├── frontend/                 # SvelteKit + Tailwind UI
│   ├── src/routes/+page.svelte
│   ├── src/app.css           # Theme tokens (matte blue / black)
│   └── vite.config.ts        # Tailwind plugin + /api proxy
├── pyproject.toml            # Python dependencies (uv)
└── uv.lock
```

## Getting started

### Prerequisites

- Python 3.10+ and [uv](https://docs.astral.sh/uv/)
- Node.js 20+

### 1. Backend

```bash
cd backend
uv run uvicorn main:app --port 8080 --reload
```

Interactive docs: http://localhost:8080/docs

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The dev server proxies `/api/*` to `http://localhost:8080` (see `frontend/vite.config.ts`), so no CORS setup is needed during development.

> If port 8080 is taken, change the backend port and update the proxy target plus the port hints in the UI.

## API reference

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Liveness check |
| `GET` | `/genres` | Supported genres |
| `POST` | `/predict` | Predict one song |
| `POST` | `/predict/batch` | Predict up to 100 songs |
| `GET` | `/cache/stats` | Cache entries, hits, misses, hit rate, TTL |
| `DELETE` | `/cache` | Clear the cache |
| `POST` | `/cache/purge` | Remove expired cache entries |
| `GET` | `/history` | Recent predictions (`?limit=`) |
| `GET` | `/history/stats` | Aggregate prediction stats |

**Request body** (`/predict`):

```json
{
  "genre": "Pop",
  "release_year": 2024,
  "duration_sec": 185,
  "danceability": 0.86,
  "energy": 0.82,
  "valence": 0.71,
  "tempo_bpm": 122,
  "acousticness": 0.04,
  "instrumentalness": 0.0,
  "speechiness": 0.06,
  "liveness": 0.12,
  "loudness_db": -5.2,
  "streams": 42000000
}
```

**Response**:

```json
{
  "is_viral": true,
  "label": "Viral",
  "viral_probability": 1.0,
  "cached": false
}
```

## The model

Trained in `model/spotify.ipynb` on the Kaggle dataset *What Makes a Song Go Viral? (10,000 tracks)*. The target is `viral` (0/1, 36% positive). Identifiers (`track_id`, `track_name`, `artist`) are dropped to avoid leakage.

Preprocessing is a scikit-learn `Pipeline` / `ColumnTransformer`: median imputation + `StandardScaler` for the 12 numeric features, most-frequent imputation + `OneHotEncoder(handle_unknown="ignore")` for `genre`, feeding a `LogisticRegression(class_weight="balanced")`.

Held-out test metrics (80/20 stratified split, `random_state=42`):

| Accuracy | Precision | Recall | F1 | ROC-AUC |
| --- | --- | --- | --- | --- |
| 0.808 | 0.706 | 0.798 | 0.749 | 0.898 |

`class_weight="balanced"` was chosen because the classes are imbalanced (36% viral); it trades a little precision for materially better recall on the viral class, which is the class that matters here.

## Caching & storage design

Requests are keyed by the **SHA-256 of the canonicalized feature vector**, so identical profiles are guaranteed cache hits regardless of key order.

- **`cache.db`** — `cache` table (key → serialized response, TTL, hit counter) and a `cache_meta` table for global hit/miss/eviction counters. Default TTL is 24h (`CACHE_TTL_SECONDS`).
- **`virality.db`** — `predictions` history table for audit and analytics.

Two details make the cache genuinely fast:

1. **Disposable data is not fsynced.** `cache.db` runs in WAL mode with `synchronous=OFF`. A cache entry is re-derived in milliseconds, so there is no reason to pay for disk durability.
2. **History writes are off the request path.** `virality.db` is durable (`synchronous=NORMAL`), but inserts are queued to a background writer thread that batches them. The request returns as soon as the cache read completes.

Measured locally: cold miss ≈ 30 ms (warm model), cache hit ≈ **1 ms in-process / 5–7 ms over HTTP** — roughly a 5–30× reduction, and the gap grows on slower disks where a single fsync costs ~100 ms.

## Why these tools

### Data & modelling

- **scikit-learn** — the whole model is preprocessing + one estimator, and scikit-learn's `Pipeline`/`ColumnTransformer` bundle them into a single serializable object where preprocessing and inference can never drift apart (the #1 source of train/serve skew). It is the right level of abstraction and scale here.
  - *Over XGBoost/LightGBM:* those win on large tabular data, but they add a heavyweight dependency and tuning surface for a dataset of 10k rows where a linear model with `ROC-AUC ≈ 0.90` already captures the signal.
  - *Over a neural network:* 10k rows and 13 features cannot justify the complexity, training time, or loss of interpretability.
  - *Over statsmodels:* statsmodels is great for inference on coefficients but has no production pipeline/serialization story.
- **Logistic Regression** — coefficients are directly interpretable (you can say *which* audio features push a track toward virality), it is fast to train and predict, and `class_weight="balanced"` cleanly handles the class imbalance.
  - *Over Random Forest / SVC:* comparable accuracy but larger artifacts, slower inference, and no simple probability calibration.
- **pandas / NumPy** — the de facto DataFrame stack for tabular EDA and the exact column alignment `ColumnTransformer` needs.
- **kagglehub** — pulls the dataset programmatically so the notebook is reproducible without committing a CSV to the repo.
- **pickle** — zero-config serialization for a scikit-learn pipeline (the ecosystem's standard). *Over ONNX/joblib:* ONNX adds a conversion step and risks unsupported ops; joblib is essentially pickle with array optimizations we don't need for a 3.6 KB artifact.

### Backend

- **FastAPI** — automatic request validation and OpenAPI docs come free from type hints, and its async core plus Pydantic gives you a self-documenting `/docs` page. For a small JSON ML service it is the fastest path from types to a production-ready API.
  - *Over Flask:* Flask needs a separate validation/serialization library and does not generate docs; you would write by hand what FastAPI derives.
  - *Over Django/DRF:* Django brings an ORM, admin, and templating layer this project does not need — too much framework for one model endpoint.
- **Pydantic** — request/response schemas double as input validation (ranges, allowed genres) and as the API contract, so bad input is rejected before it ever reaches the model.
- **uvicorn** — the reference ASGI server for FastAPI, `uvicorn[standard]` includes uvloop and watchfiles for fast I/O and reload. *Over Gunicorn+WSGI:* WSGI cannot run ASGI apps.
- **SQLite** — built into Python, zero-ops, single-file, and ACID; a cache and a small history log do not need a server. It lives inside the same process with no network hop, which is exactly why a hit is ~1 ms.
  - *Over Redis:* the classic cache choice, but it means running and operating another service for data we want persisted on disk anyway. At this scale SQLite wins on simplicity and on keeping the deploy a single process.
  - *Over Postgres:* a full server is unjustified for one table, and adds an install/connection dependency to a portfolio-grade project.
- **`sqlite3` + a background writer thread** — avoids a new dependency while keeping durable history writes off the hot path.
- **uv** — resolves and installs Python dependencies in milliseconds, locks them deterministically (`uv.lock`), and manages the virtualenv, replacing the `pip`/`venv`/`pip-tools`/`pyenv` stack with one tool.
  - *Over pip + requirements.txt:* no lockfile, no resolver speed, no interpreter management.
  - *Over Poetry/conda:* heavier, slower resolves, and conda's value (non-Python binaries) is unnecessary here.

### Frontend

- **SvelteKit + Svelte 5** — compiles components to small, dependency-free JS with no virtual DOM, giving a snappy form-heavy UI with very little code. Svelte 5's runes (`$state`, `$derived`) make reactive state trivial (the probability ring is derived state, not a stored copy).
  - *Over React/Next.js:* React ships a larger runtime and requires manually managing re-renders and memoization; this app has no need for the React ecosystem's breadth or React Server Components.
  - *Over Vue/Nuxt:* Vue is a fine middle ground but has a heavier runtime than Svelte and its tooling is more opinionated; Svelte's compiled output and ergonomics fit a single-screen app better.
  - *Over plain HTML/JS:* hand-wiring reactivity for a dozen bound sliders and async state is exactly the boilerplate frameworks exist to remove.
- **Tailwind CSS v4** — utility classes keep styling colocated with markup, which suits a custom themed design (matte blue/black design tokens defined once in `src/app.css` via `@theme`). v4's Vite plugin needs no config file or PostCSS setup.
  - *Over Bootstrap:* Bootstrap's opinionated components fight a bespoke dark theme and require overrides.
  - *Over CSS Modules / plain CSS:* you would write and name far more CSS by hand for no benefit at this size.
- **Vite** — instant HMR and a one-line dev proxy that removes CORS entirely during development; it is also the underlying build tool SvelteKit uses.
- **TypeScript** — types the API request/response shapes, turning backend contract changes into compile-time errors (`svelte-check` runs clean).

## Further improvements

The biggest usability gap is data entry: users must currently supply 13 audio features by hand. I would integrate an **AI model that lets a user enter only the song name and genre, then automatically fetches the rest of the feature details.**

Concretely:

1. **Lookup first.** Given `track_name` + `artist`/`genre`, query the Spotify Web API (audio-features endpoint) or a public MusicBrainz/Deezer source to retrieve real danceability, energy, valence, tempo, loudness, and stream/popularity numbers.
2. **LLM / ML fallback.** When a track is not indexed, use an LLM with tool access (function calling) — or a regression model trained on track metadata — to estimate the missing audio features from the title, artist, genre, and release year, returning them in the exact schema the predictor expects.
3. **Natural-language input.** Let the user type *"upbeat 2024 pop song, 3 minutes"* and have the model map it to the feature vector, with the UI showing the auto-filled values so they can be reviewed and edited before prediction.

This would extend the current pipeline with a `resolve_features(song_name, genre)` step in front of the existing predictor and cache — `POST /predict/auto` — so the model, cache, and history layers stay unchanged.
