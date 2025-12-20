import os
os.environ["HSA_OVERRIDE_GFX_VERSION"] = "10.3.0"
os.environ["ROCM_PATH"] = "/opt/rocm"
import torch
import pandas as pd
from src.data_loader import DataHandler
from src.llm_client import LLMTeacher
from src.ann_model import VibeStudent
from src.trainer import KnowledgeDistiller
from src.spotify_client import SpotifyHandler
import src.config as config


def egitim_modu():
    print("\n🎓 EĞİTİM MODU (DERİN ÖĞRENME 🧠)")

    # 1. AYARLAR
    SAMPLE_SIZE = 50000  # Daha fazla veri (Cache varsa hızlı akar)
    EPOCHS = 50  # Veri setinin üzerinden kaç kez geçeceği

    loader = DataHandler()
    # İlk yükleme
    df = loader.load_data(sample_size=SAMPLE_SIZE)

    teacher = LLMTeacher()
    # Output size 250'de kalsın
    student = VibeStudent(input_size=len(config.FEATURE_COLUMNS), output_size=50000)

    # Varsa eski modeli yükle ki üzerine katalım (Transfer Learning)
    if os.path.exists("data/vibe_student_final.pth"):
        try:
            student.load_model("data/vibe_student_final.pth")
            print("♻️  Önceki bilgiler hatırlandı, üzerine öğreniliyor...")
        except:
            print("⚠️ Eski model boyutu uyumsuz, sıfırdan başlanıyor.")

    trainer = KnowledgeDistiller(student, teacher)

    print(f"🚀 {SAMPLE_SIZE} şarkı ile {EPOCHS} tur (Epoch) eğitim başlıyor...")

    # main.py -> egitim_modu içi

    for epoch in range(EPOCHS):
        print(f"\n🔄 EPOCH {epoch + 1}/{EPOCHS} BAŞLIYOR...")

        # Shuffle
        df = df.sample(frac=1).reset_index(drop=True)

        total_loss = 0
        count = 0

        for index, row in df.iterrows():
            try:
                features = row[config.FEATURE_COLUMNS].values.astype(float)

                loss, genre = trainer.train_step(
                    features, row['artist'], row['track'], row['genre']
                )

                total_loss += loss
                count += 1

                # Raporlama (Her 100 şarkıda bir)
                if count % 100 == 0:
                    avg_loss = total_loss / 100
                    print(f"   [{count}/{len(df)}] Son: {genre} | Loss: {avg_loss:.4f}")
                    total_loss = 0

                    # --- GÜVENLİK EKLENTİSİ: ARA KAYIT ---
                # Her 1.000 şarkıda bir modeli kaydet.
                # Terminali kapatsan bile en fazla son 1000 şarkıyı kaybedersin.
                if count % 1000 == 0:
                    student.save_model("data/vibe_student_final.pth")
                    print(f"💾 Güvenlik Kaydı Alındı ({count}. şarkı)")

            except Exception as e:
                continue

        # Epoch sonu işlemleri (Scheduler + Final Kayıt)
        trainer.adjust_learning_rate(epoch + 1, EPOCHS)
        student.save_model("data/vibe_student_final.pth")
        print(f"💾 Epoch {epoch + 1} TAMAMLANDI ve kaydedildi.")

    print("\n✅ TÜM EĞİTİM BİTTİ. MODEL ARTIK BİR USTA!")


def playlist_modu():
    print("\n🎧 PLAYLIST MODU (UNIVERSAL SEARCH 🌍)")
    print("İpucu: Birden fazla türü birleştirmek için virgül kullanabilirsin.")
    print("Örnek: 'rap, hip-hop, trap' veya 'rock, metal, punk'")

    model_path = "data/vibe_student_final.pth"
    if not os.path.exists(model_path):
        print("❌ Model yok! Önce eğit.")
        return

    from src.trainer import GenreMapper
    mapper = GenreMapper()
    if not mapper.genre_to_id:
        print("❌ Harita boş!")
        return

    # Modeli Yükle (Kapasiteyi 250 yaptığını varsayıyorum)
    student = VibeStudent(input_size=len(config.FEATURE_COLUMNS), output_size=50000)

    try:
        student.load_model(model_path)
    except Exception as e:
        print(f"❌ Model yükleme hatası: {e}")
        return

    student.to(config.DEVICE)
    student.eval()

    # --- KULLANICI GİRİŞİ ---
    print(f"\n📋 Sistemde {len(mapper.genre_to_id)} farklı tür kayıtlı.")
    raw_input = input("🎵 Türleri yazın: ").strip().lower()

    # Girdiyi virgüllere böl ve temizle (örn: ['rap', 'hip-hop', 'drill'])
    search_terms = [t.strip() for t in raw_input.split(',')]

    # --- AKILLI EŞLEŞTİRME ---
    target_ids = []
    found_genres = []

    # Tüm kayıtlı türleri tarıyoruz
    for genre, id in mapper.genre_to_id.items():
        # Kayıtlı türün içinde, aradığımız kelimelerden HERHANGİ BİRİ geçiyor mu?
        # Örn: "east coast hip hop" içinde "hip hop" var mı? EVET.
        if any(term in genre.lower() for term in search_terms):
            target_ids.append(int(id))
            found_genres.append(genre)

    # Hiçbir şey bulunamadıysa
    if not target_ids:
        print(f"⚠️ '{raw_input}' ile eşleşen hiçbir alt tür bulunamadı.")
        return

    # Kullanıcıya ne bulduğumuzu raporlayalım (Güven vermek için)
    print(f"\n🔎 Şu alt türlerin güçleri birleştiriliyor ({len(found_genres)} adet):")
    # Çok uzunsa sadece ilk 10 tanesini göster
    display_limit = 10
    print(f"   {', '.join(found_genres[:display_limit])}")
    if len(found_genres) > display_limit:
        print(f"   ... ve {len(found_genres) - display_limit} tane daha.")

    # --- VERİ İŞLEME ---
    print("\n📚 Veri seti belleğe alınıyor...")
    loader = DataHandler()
    df = loader.load_data(sample_size=None)

    print(f"⚡ {len(df)} şarkı taranıyor...")

    try:
        features_np = df[config.FEATURE_COLUMNS].values.astype(float)

        # --- BELLEK DOSTU (CHUNK) HESAPLAMA ---
        chunk_size = 50000  # Her seferde 50 bin şarkı işle
        all_probs = []

        print(f"🧠 GPU Belleği korunuyor, {chunk_size}'lık parçalar halinde hesaplanıyor...")

        for i in range(0, len(features_np), chunk_size):
            chunk = features_np[i: i + chunk_size]
            chunk_tensor = torch.tensor(chunk, dtype=torch.float32).to(config.DEVICE)

            with torch.no_grad():
                outputs = student(chunk_tensor)
                probs = torch.softmax(outputs, dim=1)
                # Sadece ihtiyacımız olan sütunların (target_ids) toplamını alıp CPU'ya çek
                total_chunk_probs = probs[:, target_ids].sum(dim=1).cpu()
                all_probs.append(total_chunk_probs)

            # Belleği temizle
            del chunk_tensor
            torch.cuda.empty_cache() if torch.cuda.is_available() else None

        # Tüm parçaları birleştir
        df['score'] = torch.cat(all_probs).numpy()
        # --------------------------------------

        # Eşiği 0.1 yaptık, istersen 0.3'e çekip daha kaliteli sonuç alabilirsin
        result_df = df[df['score'] > 0.1].sort_values(by='score', ascending=False)

        playlist = []
        for index, row in result_df.head(100).iterrows():
            playlist.append((row['artist'], row['track'], row['score'], row['spotify_id']))

    except Exception as e:
        print(f"❌ Hesaplama Hatası: {e}")
        return

    print(f"\n🎵 SONUÇ: {len(playlist)} Şarkı Bulundu")
    for i, p in enumerate(playlist[:15]):
        print(f" {i + 1}. {p[0]} - {p[1]} (Skor: {p[2]:.2f})")

    if playlist:
        q = input("\nSpotify'a yükleyelim mi? (E/H): ").lower()
        if q == 'e':
            ids = [p[3] for p in playlist]
            sp = SpotifyHandler()
            # Playlist ismini kullanıcının girdisine göre yapıyoruz
            clean_name = raw_input.replace(",", " &").title()
            sp.create_playlist_from_ids(ids, f"AI Mix: {clean_name}")


def main():
    while True:
        print("\n--- SPOTIFY AI ---")
        print("1. Eğit")
        print("2. Playlist Yap")
        print("3. Çıkış")
        c = input("Seç: ")
        if c == '1':
            egitim_modu()
        elif c == '2':
            playlist_modu()
        elif c == '3':
            break


if __name__ == "__main__":
    main()