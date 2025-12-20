import os

# ==============================================================================
# AMD ROCm FIX (RX 6000 Serisi İçin - SENİN İÇİN KRİTİK)
# ==============================================================================
os.environ["HSA_OVERRIDE_GFX_VERSION"] = "10.3.0"
os.environ["ROCM_PATH"] = "/opt/rocm"

import torch

# ==============================================================================
# DOSYA YOLLARI
# ==============================================================================
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(PROJECT_ROOT, 'data', 'tracks.csv')

# ==============================================================================
# OLLAMA AYARLARI (LOCAL)
# ==============================================================================
# Terminalde 'ollama pull llama3.2' yaptığın modelin tam adı:
LLM_MODEL_ID = "llama3.2"

# ==============================================================================
# DONANIM VE CSV AYARLARI
# ==============================================================================
CSV_ARTIST = 'artist_name'
CSV_TRACK = 'track_name'
CSV_GENRE = 'genre'
CSV_ID = 'track_id'

SPOTIPY_CLIENT_ID = "63699c7b2ba3443d98f3c4370ca9a86a"
SPOTIPY_CLIENT_SECRET = "148ed299788b4f62b4b6eca6b16d45cf"
SPOTIPY_REDIRECT_URI = "http://127.0.0.1:8888/callback"

def get_device():
    if torch.cuda.is_available():
        return torch.device("cuda")
    else:
        return torch.device("cpu")

DEVICE = get_device()

FEATURE_COLUMNS = [
    'danceability', 'energy', 'loudness', 'speechiness',
    'acousticness', 'instrumentalness', 'liveness', 'valence', 'tempo'
]