import ollama
import json
import os
os.environ["HSA_OVERRIDE_GFX_VERSION"] = "10.3.0"
os.environ["ROCM_PATH"] = "/opt/rocm"
from . import config


class LLMTeacher:
    def __init__(self):
        self.model_id = config.LLM_MODEL_ID
        print(f"🦙 LOCAL ÖĞRETMEN: {self.model_id} (Ollama)")

        self.cache_file = os.path.join(config.PROJECT_ROOT, 'data', 'knowledge_base.json')
        self.cache = {}
        self.load_cache()

        try:
            ollama.list()
        except:
            print("❌ UYARI: 'ollama serve' çalışmıyor olabilir!")

    def load_cache(self):
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    self.cache = json.load(f)
                print(f"🧠 Hafıza Yüklendi: {len(self.cache)} şarkı.")
            except:
                self.cache = {}

    def save_cache(self):
        with open(self.cache_file, 'w', encoding='utf-8') as f:
            json.dump(self.cache, f, indent=4)

    def get_corrected_genre(self, artist, track, current_genre="Unknown"):
        # 1. Önce Cache kontrolü (Hafızada var mı?)
        cache_key = f"{artist} - {track}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        # 2. Prompt (Llama'ya emir veriyoruz)
        prompt = f"""
        Song: {artist} - {track}
        Task: Identify the specific music genre. 
        Output: ONLY the genre name (e.g. Dream Pop, Trap, Alt-Rock). 
        Do NOT write sentences.
        """

        try:
            response = ollama.chat(
                model=self.model_id,
                messages=[{'role': 'user', 'content': prompt}],
            )
            content = response['message']['content'].strip()

            # --- İYİLEŞTİRİLMİŞ TEMİZLİK ---
            # Nokta, virgül, tırnak işaretlerini kaldır
            content = content.replace(".", "").replace('"', '').replace("'", "").strip()

            # Alt satıra geçmişse sadece ilk satırı al
            content = content.split('\n')[0]

            # Yasaklı kelimeler (AI özür dilerse vs.)
            forbidden = ["sorry", "assist", "language", "model", "cannot", "provide", "none", "unknown", "apologize"]

            # Eğer yasaklı kelime varsa veya cevap boşsa
            is_invalid = any(w in content.lower() for w in forbidden) or not content

            # Kelime sayısı kontrolü (Örn: "I think it is rock" -> 5 kelime, bunu elemeliyiz ama "Post rock" -> 2 kelime, kalmalı)
            # Limiti 6'ya çektik.
            if len(content.split()) > 6:
                is_invalid = True

            # --- KRİTİK MÜDAHALE (FALLBACK) ---
            if is_invalid:
                # Eğer AI bilemediyse, CSV'deki eski veriyi (varsa) koru!
                # Eskiden direkt "Unknown" yapıyorduk, bu veriyi çöpe atıyordu.
                if current_genre and current_genre.lower() != "unknown":
                    final_decision = current_genre
                else:
                    final_decision = "Unknown"
            else:
                final_decision = content.title()  # Baş harfleri büyüt (Pop Rock)

            # ----------------

            # Hafızaya kaydet
            self.cache[cache_key] = final_decision
            self.save_cache()
            return final_decision

        except Exception as e:
            print(f"⚠️ Ollama Hatası: {e}")
            # Hata olursa da eski veriyi korumaya çalış
            return current_genre if current_genre else "Unknown"