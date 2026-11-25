# Plan

Written by the Planner, approved by the user. One `## <ID>` entry per task, with these
`- Key: value` lines, one per line. `Agent` is optional (codex | gemini | claude).
`Acceptance criteria` can be one line or indented sub-bullets, one criterion per line.

Context for every task: the old code (`src/`, `main.py`, `data/preprocess.py`) is replaced by a
new package `vibe/` at the repo root. The raw data is `data/spotify_data.csv` (1,159,764 rows,
first column is an unnamed index; columns `artist_name, track_name, track_id, popularity, year,
genre, danceability, energy, key, loudness, mode, speechiness, acousticness, instrumentalness,
liveness, valence, tempo, duration_ms, time_signature`; 82 genres). The CSV is not in git and is
not in worker worktrees: tests must build small synthetic DataFrames and never read the real
CSV. Canonical internal column names after loading: `artist, track, track_id, popularity, year,
genre` plus the audio columns unchanged. Background and decisions: `docs/Roadmap.md`.

## T01-setup
- Title: Project setup, secrets out of code, remove old code
- Agent: claude
- Allowed files: requirements.txt, .env.example, .gitignore, vibe/__init__.py, vibe/settings.py, src/__init__.py, src/config.py, src/ann_model.py, src/data_loader.py, src/llm_client.py, src/spotify_client.py, src/trainer.py, src/__pycache__/, main.py, data/preprocess.py
- Depends on: -
- Acceptance criteria:
  - `requirements.txt` lists numpy, pandas, pyarrow, scikit-learn, torch, faiss-cpu, spotipy, ollama, python-dotenv, lingua-language-detector, pytest
  - old files `src/*.py`, tracked `src/__pycache__/*.pyc`, `main.py`, `data/preprocess.py` are deleted from git
  - `.gitignore` adds `data/*.csv`, `data/processed/`, `artifacts/`, `.env`
  - `.env.example` holds `SPOTIFY_CLIENT_ID=`, `SPOTIFY_CLIENT_SECRET=`, `SPOTIFY_REDIRECT_URI=http://127.0.0.1:8888/callback`, `OLLAMA_HOST=http://localhost:11434`, `LLM_MODEL=llama3.2` with empty secrets
  - `vibe/settings.py` exposes `PROJECT_ROOT`, `DATA_DIR`, `RAW_CSV` (= `data/spotify_data.csv`), `PROCESSED_DIR` (= `data/processed`), `ARTIFACTS_DIR` (= `artifacts`), all absolute `pathlib.Path` built from the package location, not the cwd
  - `settings.get_spotify_credentials()` loads `.env` (python-dotenv) and returns `(client_id, client_secret, redirect_uri)`; raises `RuntimeError` naming the missing variable when one is empty or unset
  - `settings.llm_config()` returns `(host, model)` from env with the defaults above
  - `settings.get_device()` returns `torch.device("cuda")` when available, else `"cpu"`; no ROCm environment variables are set anywhere

## T02-data-clean
- Title: Load and clean the raw CSV
- Depends on: T01
- Allowed files: vibe/data.py
- Acceptance criteria:
  - `load_raw(path) -> pd.DataFrame` reads the CSV, drops the unnamed index column, renames `artist_name -> artist`, `track_name -> track`, keeps all other columns
  - `clean(df) -> tuple[pd.DataFrame, dict]` drops rows with `tempo <= 0`, `time_signature == 0`, `duration_ms < 30000` or `duration_ms > 900000`, and rows with NaN in any required column
  - `clean` removes duplicates on (lower-cased stripped `artist`, lower-cased stripped `track`), keeping the row with the highest `popularity`
  - the returned dict holds counts: `rows_in`, `dropped_tempo`, `dropped_time_signature`, `dropped_duration`, `dropped_na`, `dropped_duplicates`, `rows_out`
  - `clean` resets the index and never mutates its input
  - `save_processed(df, path)` / `load_processed(path)` round-trip a DataFrame through Parquet with identical columns and dtypes

## T03-features
- Title: Feature engineering and frozen scaler
- Depends on: T02
- Allowed files: vibe/features.py
- Acceptance criteria:
  - `FEATURE_NAMES` is the ordered list: danceability, energy, speechiness, acousticness, instrumentalness, liveness, valence, loudness, tempo, tempo_folded, key_sin, key_cos, mode, log_duration, time_signature, year (16 names)
  - `fold_tempo(bpm)` halves or doubles until the value lies in [80, 160); works on scalars and numpy arrays
  - `camelot_position(key, mode) -> int` in 0..11: major key k gives `(7*k) % 12`, minor key k gives the position of its relative major `(7*((k+3) % 12)) % 12`; C major (0,1) and A minor (9,0) give the same position; G major is one step from C major
  - `key_sin`/`key_cos` are sin/cos of `2*pi*camelot_position/12`
  - `log_duration` is `log(duration_ms / 1000)`
  - `FeatureScaler.fit(df)` learns per-column mean and std for the non-trig columns; `transform(df) -> np.ndarray` of shape (N, 16), dtype float32, z-scored, no NaN; trig columns pass through unscaled
  - `FeatureScaler.save(path)` / `FeatureScaler.load(path)` round-trip through JSON and give identical `transform` output
  - a column with zero std transforms to 0.0, not NaN
  - `LEVEL_FEATURES = ["danceability", "energy", "valence", "acousticness", "instrumentalness", "speechiness", "liveness", "tempo"]` and `LEVELS = ["very_low", "low", "mid", "high", "very_high"]`
  - `FeatureLevels.fit(df)` stores the 15/30/40/60/70/85 percentiles and min/max of each raw (unscaled) `LEVEL_FEATURES` column
  - `range_for(feature, level) -> (lo, hi)` in raw units: very_low = [min, p15], low = [min, p40], mid = [p30, p70], high = [p60, max], very_high = [p85, max]; bounds are inclusive, so a range where both cut points coincide still holds that value
  - `FeatureLevels.save(path)` / `FeatureLevels.load(path)` round-trip through JSON with identical `range_for` output; an unknown feature or level raises `KeyError`

## T04-split
- Title: Artist-disjoint train/val/test split
- Depends on: T02
- Allowed files: vibe/split.py
- Acceptance criteria:
  - `artist_split(df, val_frac=0.1, test_frac=0.1, seed=42) -> dict[str, np.ndarray]` returns row-index arrays under keys `train`, `val`, `test`
  - no artist appears in more than one split; the union covers every row exactly once
  - the share of artists (not rows) in val and test is within 0.02 of the requested fractions on a synthetic set of 1000 artists
  - the same seed gives the same split; a different seed gives a different split

## T05-taxonomy
- Title: Genre hierarchy and facets for the 82 genres
- Agent: claude
- Depends on: T01
- Allowed files: data/genre_taxonomy.json, vibe/taxonomy.py
- Acceptance criteria:
  - `GENRES` in `vibe/taxonomy.py` is the sorted list of the 82 dataset genres: acoustic, afrobeat, alt-rock, ambient, black-metal, blues, breakbeat, cantopop, chicago-house, chill, classical, club, comedy, country, dance, dancehall, death-metal, deep-house, detroit-techno, disco, drum-and-bass, dub, dubstep, edm, electro, electronic, emo, folk, forro, french, funk, garage, german, gospel, goth, grindcore, groove, guitar, hard-rock, hardcore, hardstyle, heavy-metal, hip-hop, house, indian, indie-pop, industrial, jazz, k-pop, metal, metalcore, minimal-techno, new-age, opera, party, piano, pop, pop-film, power-pop, progressive-house, psych-rock, punk, punk-rock, rock, rock-n-roll, romance, sad, salsa, samba, sertanejo, show-tunes, singer-songwriter, ska, sleep, songwriter, soul, spanish, swedish, tango, techno, trance, trip-hop
  - `data/genre_taxonomy.json` maps every genre to `{"parent": <str>, "language_region": <str or null>, "mood_context": <str or null>}`; there are 10 to 20 distinct parents, and every parent is a lower-case name without spaces
  - `genre_index(name) -> int` gives the position in `GENRES`; unknown names raise `KeyError`
  - `parent_of(genre) -> str`, `facets_of(genre) -> dict`, `parents() -> list[str]`, `genres_in_parent(parent) -> list[str]`
  - `resolve_terms(terms: list[str]) -> list[str]` maps user words to genres: an exact genre gives itself, a parent name gives all its genres, matching is case-insensitive and treats spaces, `-` and `&` alike ("hip hop" -> hip-hop, "Drum & Bass" -> drum-and-bass); unknown terms are ignored; substring matches are not allowed ("rap" does not match "trap")
  - `load_taxonomy()` raises `ValueError` if the JSON misses a genre from `GENRES` or holds one that is not in it

## T06-soft-labels
- Title: Soft genre targets and genre affinity
- Depends on: T05
- Allowed files: vibe/labels.py
- Acceptance criteria:
  - `artist_genre_distribution(df) -> dict[str, np.ndarray]`: per artist, a length-82 vector (order of `taxonomy.GENRES`) of the share of that artist's tracks in each genre; sums to 1
  - `genre_affinity(df) -> np.ndarray` (82, 82): entry (g, h) counts artists with tracks in both g and h, rows normalized to sum 1, diagonal included; a genre with no multi-genre artist has 1.0 on its diagonal
  - `soft_targets(df, alpha=0.3, gamma=0.1, affinity=None) -> np.ndarray` (N, 82) float32 = `(1-alpha-gamma)*onehot(genre) + alpha*artist_distribution + gamma*affinity[genre]`; every row sums to 1 within 1e-5; `alpha=gamma=0` gives exact one-hot rows
  - an artist with a single genre gets the same row from the one-hot and the artist-distribution parts

## T07-evaluate
- Title: Retrieval metrics on held-out artists
- Depends on: T05
- Allowed files: vibe/evaluate.py
- Acceptance criteria:
  - `relevance(query_row, result_rows) -> np.ndarray`: 3 same artist, 2 same genre, 1 same parent genre (taxonomy), 0 otherwise
  - `genre_precision_at_k`, `parent_precision_at_k`: share of the top k results with the query's genre / parent genre
  - `artist_recall_at_k`: same-artist hits in the top k divided by `min(k, other tracks of that artist in the pool)`; queries whose artist has no other track are skipped
  - `ndcg_at_k` using the relevance grades above, ideal DCG computed from the pool
  - `evaluate(search_fn, df_pool, query_idx, k=10) -> dict` where `search_fn(query_idx_array, k+1)` returns result row indices; the query itself is removed from its results; returns the mean of the four metrics plus `n_queries`
  - `sample_queries(df_pool, n, seed) -> np.ndarray` is deterministic for a seed
  - hand-built examples with known answers give exact expected values for every metric

## T08-index
- Title: FAISS vector index wrapper
- Depends on: T01
- Allowed files: vibe/index.py
- Acceptance criteria:
  - `VectorIndex(dim, metric="cosine" | "l2")`; cosine L2-normalizes vectors on add and query and uses `IndexFlatIP`; l2 uses `IndexFlatL2`
  - `add(vectors, ids)` with int64 ids; `search(queries, k) -> (ids, scores)` both shape (Q, k); a vector queried against an index holding it returns its own id first
  - `save(dir)` / `VectorIndex.load(dir)` round-trip index and ids; search results are identical after load
  - `reconstruct(ids) -> np.ndarray` returns the stored vectors (normalized for cosine)

## T09-baseline
- Title: Path A, scaled raw features
- Depends on: T03, T08
- Allowed files: vibe/baseline.py
- Acceptance criteria:
  - `DEFAULT_WEIGHTS: dict[str, float]` over `features.FEATURE_NAMES`, all 1.0 except `year` 0.5
  - `embed_a(X, weights=None) -> np.ndarray`: multiplies the scaled feature matrix columns by the weights; float32, same row count
  - `build_index_a(X, ids, weights=None) -> VectorIndex` with metric `l2`
  - with a zero weight on a column, two rows that differ only in that column get distance 0

## T10-encoder
- Title: VibeEncoder model, losses and pair sampler
- Depends on: T01
- Allowed files: vibe/model.py
- Acceptance criteria:
  - `VibeEncoder(in_dim=16, hidden=128, emb_dim=64, n_genres=82, dropout=0.1)`: Linear-LayerNorm-ReLU, Linear-LayerNorm-ReLU, Linear to `emb_dim`, L2-normalized; `forward(x)` returns embeddings of shape (B, 64) with unit norm; `genre_logits(emb)` returns (B, 82)
  - works with batch size 1 in train and eval mode
  - `info_nce_loss(anchor, positive, temperature=0.1)`: in-batch negatives, symmetric cross-entropy; lower when positives equal anchors than for random pairs
  - `soft_cross_entropy(logits, soft_targets)` equals standard cross-entropy when targets are one-hot
  - `PairSampler(artist_codes, batch_size, seed)` yields `(anchor_idx, positive_idx)` index arrays: each pair shares an artist, the two indices differ, only artists with at least 2 tracks are used, and no artist appears twice in one batch
  - `save_encoder(model, path, config)` / `load_encoder(path)` round-trip weights and config; outputs match after load

## T11-train
- Title: Training loop for path B
- Depends on: T03, T04, T06, T07, T10
- Allowed files: vibe/train.py
- Acceptance criteria:
  - `TrainConfig` dataclass: epochs=20, batch_size=1024, lr=1e-3, weight_decay=1e-4, temperature=0.1, genre_weight=0.5, alpha=0.3, gamma=0.1, patience=3, seed=42
  - `train_encoder(X_train, df_train, X_val, df_val, config, out_path) -> dict`: loss = `info_nce + genre_weight * soft_cross_entropy` with soft targets from `labels.soft_targets`; AdamW; uses `settings.get_device()`
  - after each epoch computes `evaluate.evaluate` on val (index of val embeddings, k=10) and keeps the checkpoint with the best `parent_precision_at_k`; stops early after `patience` epochs without improvement
  - returns a history dict with per-epoch `loss` and val metrics, and `best_epoch`
  - `embed_b(model, X, batch_size=8192) -> np.ndarray` (N, 64) float32 in eval mode without gradients
  - on a synthetic set (two well-separated clusters of artists) 3 epochs reduce the loss and the checkpoint file exists

## T12-language
- Title: Language detection from track names
- Depends on: T01
- Allowed files: vibe/language.py
- Acceptance criteria:
  - `SUPPORTED = ["en","es","pt","fr","de","sv","tr","it","ko","ja","zh","hi"]`
  - `detect_language(text, min_confidence=0.5) -> str` returns an ISO 639-1 code from `SUPPORTED` or `"unknown"` (empty, digits only, or low confidence) using lingua with only these languages loaded
  - clear examples: "Bir Derdim Var Ki Anlatamam Sana" -> tr, "Je ne regrette rien du tout" -> fr, "Ich will nicht nach Hause gehen" -> de, "Me quedo contigo para siempre" -> es, "" -> unknown
  - `detect_languages(texts) -> list[str]` uses lingua's batch API and gives the same answers as calling `detect_language` one by one

## T13-rerank
- Title: Re-ranking, filters and diversity
- Depends on: T01
- Allowed files: vibe/rerank.py
- Acceptance criteria:
  - `artist_centroids(emb, artist_codes) -> (centroids, code_to_row)`: mean embedding per artist, L2-normalized
  - `RerankConfig`: lam=0.3, popularity_bias=0.0 (range -1..1), max_per_artist=3, diversity=0.2 (MMR weight 0..1), year_range=None, language=None, n=50
  - `rerank(query_vec, query_artist_vec, cand_ids, cand_emb, cand_meta, config) -> list[int]`: base score `cos(query, cand) + lam * cos(query_artist_vec, cand_artist_centroid)` (`lam` term skipped when `query_artist_vec` is None) `+ popularity_bias * popularity_z`; drops candidates outside `year_range` or not matching `language`; then MMR selection `(1-diversity)*score - diversity*max_cos_to_selected`; at most `max_per_artist` per artist; returns up to `n` ids in order
  - `diversity=0`, `lam=0`, `popularity_bias=0` and no limits return candidates sorted by cosine similarity
  - positive `popularity_bias` moves popular tracks up, negative moves them down

## T14-query
- Title: Query engine (by track, by genre, by spec)
- Depends on: T03, T05, T08, T13
- Allowed files: vibe/query.py
- Acceptance criteria:
  - `QuerySpec` dataclass: `genres: list[str]`, `feature_ranges: dict[str, tuple[float, float]]` (keys among danceability, energy, valence, acousticness, instrumentalness, speechiness, liveness in 0..1, and tempo in BPM), `year_range: tuple[int, int] | None`, `language: str | None`, `popularity_bias: float`, `seed_track_id: str | None`
  - `QueryEngine(df, X_scaled, emb, index, embed_fn, scaler)`; `embed_fn` maps scaled features to the index space, so the engine works for both path A and path B
  - `find_track(text) -> list[int]`: by exact `track_id`, else case-insensitive match on "artist - track", else rows whose track name contains the text; at most 10 rows, most popular first
  - `by_track(row, n, rerank_config)` excludes the seed track and its duplicates by name
  - `by_genres(genres, n, rerank_config)`: genres pass through `taxonomy.resolve_terms`; query vector is the normalized mean embedding of those genres' tracks; raises `ValueError` when nothing resolves
  - `by_spec(spec, n, rerank_config)`: starts from the genre centroid of the spec's genres (global mean when empty), sets the ranged raw features to the range midpoints, scales with `scaler`, embeds with `embed_fn`, searches, then removes tracks whose raw feature values fall outside the ranges; uses the seed track as the query when `seed_track_id` is set
  - all three return a DataFrame with `track_id, artist, track, genre, year, popularity, score`, length at most `n`, after `rerank.rerank`

## T15-llm-query
- Title: Free text to QuerySpec with the LLM
- Depends on: T03, T05, T14
- Allowed files: vibe/llm_query.py
- Acceptance criteria:
  - `parse_query(text, levels, chat_fn=None) -> QuerySpec`; `levels` is a `features.FeatureLevels`; `chat_fn(prompt) -> str` is injectable; the default calls ollama `chat` with `format="json"` using `settings.llm_config()`
  - the prompt lists the allowed genres and parents from the taxonomy, the allowed feature keys and the allowed level words, and asks for one JSON object only, shaped like `{"genres": [...], "features": {"energy": "low", ...}, "year_range": null, "language": null, "popularity_bias": 0}`
  - the LLM gives levels, never numbers: each feature value must be one of `very_low, low, mid, high, very_high`; the only exception is `tempo`, which may also be a `[min_bpm, max_bpm]` pair when the text names a BPM
  - level words become `QuerySpec.feature_ranges` through `levels.range_for(feature, level)`; an explicit tempo pair is clamped to 40..220 with min <= max
  - validation: unknown genres dropped, unknown feature keys or level words ignored, `popularity_bias` clamped to -1..1, language kept only if in `language.SUPPORTED`
  - the same LLM answer always gives the same `QuerySpec` for the same `levels`
  - when `chat_fn` raises or returns invalid JSON, falls back to `taxonomy.resolve_terms` on the words of the text and empty ranges; never raises for any input string
  - answers are cached per normalized text in `artifacts/llm_cache.json`; a cached text does not call `chat_fn` again
  - tests use a fake `chat_fn`; no test needs a running Ollama

## T16-flow
- Title: Playlist flow ordering and A-to-B journey
- Depends on: T03, T08
- Allowed files: vibe/flow.py
- Acceptance criteria:
  - `camelot_distance(pos_a, pos_b) -> int` is the circular distance on 0..11 (0 to 6)
  - `transition_cost(a, b) = |energy_a - energy_b| + |tempo_folded_a - tempo_folded_b| / 40 + 0.1 * camelot_distance` on raw rows
  - `order_by_flow(df_rows, start=0) -> list[int]`: greedy nearest-next ordering by `transition_cost`, starting from `start`, each row exactly once
  - `order_build_up(df_rows) -> list[int]`: sorted by rising energy, ties broken by tempo
  - `journey(index, emb_a, emb_b, n, exclude_ids) -> list[int]`: n points by spherical interpolation between the two unit vectors, the nearest unused id for each point, no duplicates, the first result nearest to a, the last nearest to b

## T17-feedback
- Title: Like/dislike feedback loop
- Depends on: T01
- Allowed files: vibe/feedback.py
- Acceptance criteria:
  - `rocchio(query, liked, disliked, a=1.0, b=0.75, c=0.25) -> np.ndarray`: `a*q + b*mean(liked) - c*mean(disliked)`, L2-normalized; empty liked or disliked lists contribute nothing
  - `FeedbackSession(query_vec)`: `record(id, vec, liked: bool)`, `current_query()`, `seen_ids()`; the next round of results excludes seen ids
  - with only likes, the updated query has a higher cosine to the liked vectors than the original

## T18-spotify
- Title: Spotify playlist creation from env credentials
- Depends on: T01
- Allowed files: vibe/spotify.py
- Acceptance criteria:
  - `to_uri(track_id)` gives `spotify:track:<id>` and leaves an existing URI unchanged
  - `PlaylistCreator(client=None)`: without a client, builds spotipy `Spotify(auth_manager=SpotifyOAuth(...))` from `settings.get_spotify_credentials()` with scope `playlist-modify-private playlist-modify-public`
  - `create(name, track_ids, description="", public=False, dry_run=False) -> str`: creates the playlist, adds tracks in chunks of 100, returns the playlist URL; `dry_run=True` makes no API call and returns a summary string
  - API errors surface as `RuntimeError` with the Spotify message; tests use a fake client

## T19-pipeline
- Title: End-to-end build and A/B comparison report
- Depends on: T02, T03, T04, T07, T09, T11, T12, T13
- Allowed files: vibe/pipeline.py
- Acceptance criteria:
  - `prepare(raw_csv, out_dir, detect_lang=True) -> dict`: load, clean, add a `language` column from track names, save `tracks.parquet` and the clean report JSON
  - `build(processed_dir, artifacts_dir, methods=("A","B"), train_config=None)`: fit the scaler on train rows only and save it; fit `features.FeatureLevels` on all rows and save it as `artifacts/feature_levels.json`; build and save one index per method over all rows; for B train the encoder first and save it; saves the split indices
  - `compare(processed_dir, artifacts_dir, n_queries=2000, k=10, lams=(0.0, 0.3, 0.5)) -> pd.DataFrame`: indexes the test split only (unseen artists) for each method, evaluates with `evaluate.evaluate`, for B also each `lam` via `rerank`; writes `artifacts/report.json` and `artifacts/report.md` (one row per method/lam, one column per metric)
  - each step can be re-run; it overwrites its own outputs only
  - a synthetic end-to-end run (a few hundred rows, 1 training epoch) produces every artifact file

## T20-cli
- Title: Command-line interface
- Depends on: T14, T15, T16, T17, T18, T19
- Allowed files: vibe/cli.py, vibe/__main__.py, main.py
- Acceptance criteria:
  - `python -m vibe <command>` and `python main.py <command>` run the same argparse CLI
  - commands: `prepare`, `build [--methods A B] [--epochs N]`, `compare`, `recommend`, `journey`
  - `recommend` takes exactly one of `--track TEXT`, `--genre "rap, trap"`, `--text "free text"`, plus `--method A|B` (default B), `--n 30`, `--lam`, `--discovery -1..1`, `--years 2010-2019`, `--lang tr`, `--max-per-artist`, `--flow none|smooth|build-up`, `--interactive`, `--spotify NAME`, `--dry-run`
  - `--track` with several matches prints a numbered list and asks which one; `--interactive` runs the like/dislike loop from `feedback` (input like `+3 -5`, empty line to stop)
  - `journey --from TEXT --to TEXT --n 20` prints the ordered list
  - results print as a numbered table: artist, track, genre, year, score
  - missing artifacts give a one-line message naming the command to run first, not a traceback
  - tests drive `cli.main(argv)` with tiny artifacts built in a temp dir and a fake Spotify client

## T21-readme
- Title: Rewrite README to match the real system
- Agent: claude
- Depends on: T20
- Allowed files: README.md
- Acceptance criteria:
  - describes the real architecture (path A, path B, FAISS, query engine, re-ranking, LLM as query parser), the dataset, and the artist-disjoint evaluation
  - quickstart uses the real commands: venv, `pip install -r requirements.txt`, `.env` from `.env.example`, `python -m vibe prepare`, `build`, `compare`, `recommend` examples
  - includes the A/B metrics table from `artifacts/report.md` when it exists, else a placeholder saying how to produce it
  - removes the claims that are not implemented (Kafka, Spark, RL, 75-dim input, 2000-class softmax, O(log N)); "later" items link to `docs/Roadmap.md`
  - every `python -m vibe ...` command shown in the README is accepted by `cli.build_parser().parse_args` (the worker checks this by running each one with `--help` or the parser)
