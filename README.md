
# 🎵 VibeStudent: Hybrid LLM & ANN-Powered Music Recommendation Engine

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![PyTorch](https://img.shields.io/badge/PyTorch-2.x-EE4C2C.svg)](https://pytorch.org/)
[![FAISS](https://img.shields.io/badge/FAISS-Vector%20Search-green.svg)](https://github.com/facebookresearch/faiss)
[![LLM](https://img.shields.io/badge/Teacher%20Model-Llama%203.2-purple.svg)](https://ai.meta.com/llama/)
[![Hardware](https://img.shields.io/badge/Hardware%20Accel-AMD%20ROCm-red.svg)](https://www.amd.com/en/products/software/rocm.html)

**VibeStudent** is an enterprise-scale, hybrid music recommendation architecture bridging semantic music intelligence with real-time, low-latency inference. By applying **Knowledge Distillation** from a high-capacity Large Language Model (Llama 3.2) to a lightweight **Artificial Neural Network (ANN)**, the system maps multi-modal audio signals, artist semantics, and metadata into a high-dimensional vector space for real-time similarity search over massive datasets.

---

## 🚀 Key Architectural Highlights

* **Knowledge Distillation (Teacher-Student Pipeline):** Translates deep contextual and cultural music understanding from an on-premise LLM (Llama 3.2 via Ollama) into a fast, 256-dimensional neural network embedding layer (`VibeStudent`).
* **Multi-Modal Feature Space:** Ingests a 75-dimensional input vector combining:
  * **Audio Features (9–11D):** Danceability, energy, tempo, valence, acousticness, etc.
  * **Artist Latent Space (64D):** Trainable artist embeddings capturing genre clustering and musical style.
  * **Metadata (2D):** Normalized release year and track popularity.
* **Vector Indexing & Sub-Millisecond Search:** Integrates **FAISS (Facebook AI Similarity Search)** with $O(\log N)$ search complexity to query over 1.16 million indexed tracks with minimal RAM footprint (~1.1 GB).
* **Production Stability & Data Drift Mitigation:**
  * **Frozen Global Scalers:** Prevents vector space drift when ingesting streaming tracks.
  * **Batch Normalization:** Guarantees latent stability across varying feature distributions.
* **Continuous Self-Improvement via Reinforcement Learning (RL):** Adapts to live implicit user feedback (play completion vs. early skip) using policy gradient updates constrained by **KL-Divergence**, **Experience Replay**, and a **Target Network** to avoid catastrophic forgetting.
* **Scalable Data Ingestion (Lambda Architecture):** Ready for distributed stream ingestion via **Apache Kafka** and **Spark Streaming**, separating the immutable batch layer (SQL/Parquet) from the real-time speed layer.

---

## 🧠 Neural Architecture Details

```text
Input Layer (75 Dimensions)
  ├── 9 Audio Features (Acoustic / Psychoacoustic)
  ├── 64D Trainable Artist Embedding Lookup
  └── 2 Metadata Parameters (Year, Popularity)
         │
         ▼
Hidden Bottleneck / Representation Layer (256 Neurons, ReLU, BatchNorm)
  └── [Extracts 256D "Vibe" Coordinate Vector -> FAISS Index]
         │
         ▼
Output Layer (2000 Neurons, Softmax)
  └── Soft Genre Distribution (Confidence Score for Fallback & Auditing)

```

---

## 📊 Evaluation & Validation Metrics

The engine measures both retrieval relevance and ranking quality against distilled ground-truth benchmarks:

* **Precision@K:** Evaluates the concentration of relevant items within the top-$K$ recommendations.
* **nDCG (Normalized Discounted Cumulative Gain):** Penalizes relevant recommendations positioned lower in the ranked list to guarantee peak relevance in top ranks.
* **Confidence Gating:** Utilizes Softmax probability distributions. Low-confidence inferences trigger an automated fallback to the Teacher LLM for supervision and continuous model calibration.

---

## 🛠️ Tech Stack & Dependencies

* **Core:** Python 3.10+, PyTorch, NumPy, Pandas, Scikit-learn
* **Vector Engine:** FAISS (CPU/GPU)
* **LLM Engine:** Llama 3.2 running on-premise (Ollama)
* **Data Pipelines:** Apache Kafka, Apache Spark Streaming, SQLite / PostgreSQL, Parquet
* **Hardware Acceleration:** AMD ROCm / CUDA

---

## ⚙️ Quickstart Guide

### 1. Clone the Repository

```bash
git clone [https://github.com/Golden-Stone27/Spotify_Project.git](https://github.com/Golden-Stone27/Spotify_Project.git)
cd Spotify_Project

```

### 2. Environment Setup

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt

```

### 3. Configure Environment Variables

Create a `.env` file in the root directory:

```env
SPOTIFY_CLIENT_ID="your_spotify_client_id"
SPOTIFY_CLIENT_SECRET="your_spotify_client_secret"
OLLAMA_ENDPOINT="http://localhost:11434"
LLM_MODEL_NAME="llama3.2"
EMBEDDING_DIM=256

```

### 4. Run the Pipeline

```bash
# Data preparation and feature scaling
python src/data_preprocessing.py

# Model training with Knowledge Distillation
python src/train.py

# Build and query FAISS vector index
python src/indexing.py

```

---

## 🗺️ Roadmap

* [x] Initial KNN baseline and exploratory data analysis.
* [x] Multi-modal feature processing (64D artist embeddings + audio descriptors).
* [x] Knowledge distillation pipeline with Llama 3.2.
* [x] FAISS indexing for 1.16M tracks.
* [ ] Online Reinforcement Learning pipeline with Experience Replay.
* [ ] Distributed stream processing via Apache Kafka and Spark Streaming.
* [ ] Automated hyperparameter scheduling using Bayesian Optimization.

---

## 📄 License

Distributed under the MIT License. See `LICENSE` for more information.

```

```
