import pandas as pd
import numpy as np
import os

os.environ["HSA_OVERRIDE_GFX_VERSION"] = "10.3.0"
os.environ["ROCM_PATH"] = "/opt/rocm"
from . import config


class DataHandler:
    def __init__(self):
        self.file_path = config.DATA_PATH
        self.df = None
        self.feature_cols = config.FEATURE_COLUMNS

    def load_data(self, sample_size=None):
        if not os.path.exists(self.file_path):
            raise FileNotFoundError(f"Veri dosyası bulunamadı: {self.file_path}")

        print(f"⏳ Veri yükleniyor (AMD ROCm Gücüyle 🚀): {self.file_path}...")

        # 1. Tüm veriyi oku
        self.df = pd.read_csv(self.file_path)
        print(f"✅ Veri okundu! Ham Satır: {len(self.df)}")

        # 2. Shuffle (Karıştırma)
        self.df = self.df.sample(frac=1, random_state=42).reset_index(drop=True)
        print("🔀 Veri seti karıştırıldı!")

        # 3. Sample Size (Eğer belirtildiyse kes)
        if sample_size:
            self.df = self.df.head(sample_size)
            print(f"✂️  Eğitim için {sample_size} satır kesildi.")

        # 4. Sütun isimleri temizliği
        self.df.columns = self.df.columns.str.strip().str.lower()
        rename_map = {
            config.CSV_ARTIST: 'artist',
            config.CSV_TRACK: 'track',
            config.CSV_GENRE: 'genre',
            config.CSV_ID: 'spotify_id'
        }
        self.df.rename(columns=rename_map, inplace=True)

        # 5. Temizlik ve NORMALİZASYON
        self._clean_and_normalize()

        return self.df

    def _clean_and_normalize(self):
        # NOT: Artık normalizasyon preprocess.py ile baştan yapıldığı için
        # burada sadece kritik eksik veri kontrolü yapıyoruz.
        # Hesaplama yükü kalktı! 🚀

        print("🧹 Veri bütünlüğü kontrol ediliyor...")

        required = self.feature_cols + ['artist', 'track', 'spotify_id']
        self.df.dropna(subset=required, inplace=True)

        # Normalizasyon kodu SİLİNDİ, çünkü veri zaten normalize geliyor.

        print(f"✅ Hazır Veri: {len(self.df)}")