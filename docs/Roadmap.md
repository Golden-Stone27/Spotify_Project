# Yol haritası

Bu dosya, planlama oturumunda konuşulanların özetidir. Çalışma ayrıntısı `Plan.md`'de.

## Veri hakkında bilinenler (`data/spotify_data.csv`)

- 1.159.764 şarkı, 2000–2023, 82 tür, 64.159 sanatçı, eksik değer yok.
- Sütunlar: `artist_name, track_name, track_id, popularity, year, genre, danceability, energy,
  key, loudness, mode, speechiness, acousticness, instrumentalness, liveness, valence, tempo,
  duration_ms, time_signature`.
- Tür aslında sanatçı etiketi: bir sanatçının şarkılarının ortalama %94'ü aynı türde.
  Bu yüzden sanatçı modele **girdi olmaz**, sadece eğitim sinyalidir.
- 10.533 sanatçı birden fazla türde geçiyor, bunlardan türler arası yakınlık çıkar.
- Bazı türler ses türü değil: dil/bölge (`indian`, `k-pop`, `spanish`, `french`, `german`,
  `swedish`, `cantopop`, `sertanejo`...), ruh hali/bağlam (`sleep`, `sad`, `party`, `romance`,
  `chill`), müzik dışı (`comedy`, `show-tunes`). Türkçe tür yok.
- Kirli satırlar: 7.868 tekrar eden (sanatçı + ad), %13,7'si popülerlik 0, `tempo = 0` ve
  `time_signature = 0` olanlar, 100 dakikaya kadar süreler.

## Kararlar

- Şarkı başına LLM ile tür etiketleme **kaldırıldı**. Llama 3.2 şarkıları tanımıyor, ses
  özelliklerinden öğrenilemeyecek bilgiye dayanıyor ve zaten var olan `genre` sütununu
  kötüleştiriyor.
- LLM'in rolleri: (1) 82 türü tek seferlik hiyerarşiye ayırmak, (2) serbest metni yapılandırılmış
  sorguya (JSON) çevirmek. Kapalı tür listesiyle sınırlı, sonuç doğrulanır.
- İki yol kurulur ve **aynı testle** kıyaslanır:
  - **A (baseline):** ölçeklenmiş ham özelliklerle kNN.
  - **B:** `VibeEncoder` MLP (~17D → 128 → 128 → 64), InfoNCE (aynı sanatçı = pozitif) ile
    yumuşak tür hedefli yardımcı kayıp.
- Test, **sanatçı bazında** ayrılır: test sanatçıları eğitimde hiç görülmez.
- Sanatçı bilgisi sorgu anında kullanılır: sanatçı merkezi benzerliği (λ), sanatçı başına limit.
- Arayüz: komut satırı (CLI).
- Kafka/Spark, streaming ingestion ve RL çıkarıldı. Spotify Kasım 2024'te yeni uygulamalar için
  `audio-features` ve `recommendations` uç noktalarını kapattı, yeni şarkı özelliği çekecek
  kaynak yok.

## Aktif olarak yapılacaklar (bu plan)

1. Temizlik, güvenlik ve kurulum: secret'lar `.env` dosyasına, `requirements.txt`, eski kodun
   kaldırılması.
2. Veri temizliği ve özellik mühendisliği (Camelot key kodlaması, log süre, katlanmış tempo).
3. Sanatçı bazlı train/val/test ayrımı.
4. Tür hiyerarşisi (82 tür, yaklaşık 15 ana tür ve dil/ruh hali eksenleri).
5. Yumuşak tür hedefleri ve türler arası yakınlık matrisi (LLM'siz soft-label distillation).
6. Değerlendirme: tür-precision@K, ana tür-precision@K, sanatçı recall@K, nDCG@K.
7. FAISS indeks sarmalayıcısı.
8. A baseline'ı.
9. B modeli (`VibeEncoder`) ve eğitimi.
10. Uçtan uca pipeline ve A/B karşılaştırma raporu (λ taraması dahil).
11. Sorgu motoru: şarkıdan, türden, yapılandırılmış sorgudan.
12. Yeniden sıralama: λ sanatçı benzerliği, MMR çeşitliliği, sanatçı limiti, keşif ayarı,
    dönem filtresi.
13. LLM sorgu çevirici (serbest metin → JSON). LLM sayı değil seviye verir (`very_low` …
    `very_high`); seviyeler veri setinin yüzdeliklerine göre gerçek aralıklara çevrilir.
14. Akışlı playlist: enerji/tempo/Camelot geçişleri ve "A'dan B'ye yolculuk".
15. Geri bildirim döngüsü (👍/👎 → Rocchio ile sorgu güncelleme).
16. Şarkı adından dil tespiti (filtre olarak).
17. Spotify playlist oluşturma (env'den kimlik bilgisi).
18. CLI.
19. README'yi gerçeğe uygun yeniden yazmak.

## Sonraya kalanlar

- **Kendi Spotify playlistlerin:** gerçek bir test seti ("birlikte duran şarkıları model yakın
  buluyor mu?") ve kişisel zevk profili. API erişimini o zaman kontrol etmek gerek.
- **Playlist birlikteliği verisi:** Spotify Million Playlist Dataset. En güçlü "birlikte
  dinlenir" sinyalini verir ama araştırma lisansıyla geliyor.
- **FAISS HNSW/IVF:** 1,16M × 64 için kesin arama (Flat) yeterli. Ancak ölçek büyürse gerekir.
- **Web arayüzü:** şimdilik CLI yeterli.
