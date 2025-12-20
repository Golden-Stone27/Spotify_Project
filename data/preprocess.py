import pandas as pd
import json
import os
from src import config


def pre_process_data():
    print("🚀 GLOBAL NORMALİZASYON BAŞLIYOR...")

    # 1. Ham veriyi yükle
    input_path = os.path.join(config.PROJECT_ROOT, 'data', 'tracks.csv')
    if not os.path.exists(input_path):
        print("❌ Hata: tracks.csv bulunamadı!")
        return

    print("📚 1 Milyonluk veri okunuyor (Biraz sürebilir)...")
    df = pd.read_csv(input_path)

    # Sütun isimlerini düzelt
    df.columns = df.columns.str.strip().str.lower()

    rename_map = {
        config.CSV_ARTIST: 'artist',
        config.CSV_TRACK: 'track',
        config.CSV_GENRE: 'genre',
        config.CSV_ID: 'spotify_id'
    }
    df.rename(columns=rename_map, inplace=True)

    # Gerekli sütunlar boşsa at
    required = config.FEATURE_COLUMNS + ['artist', 'track', 'spotify_id']
    df.dropna(subset=required, inplace=True)

    # 2. İstatistikleri Hesapla ve Kaydet (Scaler JSON)
    scaler_stats = {}

    print("⚖️  Normalizasyon uygulanıyor...")
    for col in config.FEATURE_COLUMNS:
        min_val = df[col].min()
        max_val = df[col].max()

        # JSON için sakla (Float'a çeviriyoruz ki JSON hata vermesin)
        scaler_stats[col] = {
            "min": float(min_val),
            "max": float(max_val)
        }

        # Veriyi Dönüştür: (X - Min) / (Max - Min)
        if max_val - min_val != 0:
            df[col] = (df[col] - min_val) / (max_val - min_val)
        else:
            df[col] = 0.0

    # 3. Scaler Bilgilerini Kaydet (İleride tek şarkı tahmini için lazım)
    scaler_path = os.path.join(config.PROJECT_ROOT, 'data', 'scalers.json')
    with open(scaler_path, 'w') as f:
        json.dump(scaler_stats, f, indent=4)
    print(f"💾 Scaler bilgileri kaydedildi: {scaler_path}")

    # 4. İşlenmiş Veriyi Kaydet
    output_path = os.path.join(config.PROJECT_ROOT, 'data', 'tracks_normalized.csv')
    df.to_csv(output_path, index=False)
    print(f"✅ BİTTİ! Yeni dosya: {output_path}")
    print(f"📊 Toplam İşlenen Satır: {len(df)}")


if __name__ == "__main__":
    pre_process_data()