import os

os.environ["HSA_OVERRIDE_GFX_VERSION"] = "10.3.0"
os.environ["ROCM_PATH"] = "/opt/rocm"
import torch
import torch.nn as nn
import torch.optim as optim
from . import config
import json


class GenreMapper:
    def __init__(self):
        self.genre_to_id = {}
        self.id_to_genre = {}
        self.next_id = 0
        self.map_file = os.path.join(config.PROJECT_ROOT, 'data', 'genre_map.json')
        self.load_map()

    def get_id(self, genre_name):
        genre_name = genre_name.lower().strip()
        if genre_name not in self.genre_to_id:
            self.genre_to_id[genre_name] = self.next_id
            self.id_to_genre[self.next_id] = genre_name
            self.next_id += 1
        return self.genre_to_id[genre_name]

    def save_map(self):
        with open(self.map_file, 'w') as f:
            json.dump(self.genre_to_id, f)

    def load_map(self):
        if os.path.exists(self.map_file):
            with open(self.map_file, 'r') as f:
                self.genre_to_id = json.load(f)
            self.id_to_genre = {int(v): k for k, v in self.genre_to_id.items()}
            self.next_id = len(self.genre_to_id)
            print(f"📂 Harita Yüklendi: {len(self.genre_to_id)} tür.")


class KnowledgeDistiller:
    def __init__(self, student_model, teacher_client):
        self.student = student_model
        self.teacher = teacher_client
        self.device = config.DEVICE
        self.student.to(self.device)

        # Başlangıç Hızı (Base Learning Rate)
        self.base_lr = 0.001

        # Optimizer'ı başlat
        self.optimizer = optim.Adam(self.student.parameters(), lr=self.base_lr, weight_decay=1e-5)

        self.criterion = nn.CrossEntropyLoss(label_smoothing=0.1)
        self.mapper = GenreMapper()

    def train_step(self, features, artist, track, old_genre):
        self.student.train()

        features_tensor = torch.tensor(features, dtype=torch.float32).unsqueeze(0).to(self.device)

        # Öğretmene Sor
        true_genre_name = self.teacher.get_corrected_genre(artist, track, old_genre)
        true_label_id = self.mapper.get_id(true_genre_name)

        target_tensor = torch.tensor([true_label_id], dtype=torch.long).to(self.device)

        self.optimizer.zero_grad()
        outputs = self.student(features_tensor)

        # Kapasite Kontrolü
        if true_label_id >= outputs.shape[1]:
            return 0.0, true_genre_name

        loss = self.criterion(outputs, target_tensor)
        loss.backward()

        # Gradient Clipping
        torch.nn.utils.clip_grad_norm_(self.student.parameters(), max_norm=1.0)

        self.optimizer.step()
        self.mapper.save_map()

        return loss.item(), true_genre_name

    # --- YENİ DİNAMİK SCHEDULER ---
    def adjust_learning_rate(self, current_epoch, total_epochs):
        """
        Strateji:
        - İlk %50'lik kısım: Hızlı öğren (Base LR)
        - %50 - %80 arası: Vitesi düşür (Base LR / 5)
        - Son %20'lik kısım: Çok ince ayar (Base LR / 10)
        """

        lr = self.base_lr

        if current_epoch >= total_epochs * 0.8:
            # Son düzlük (Örn: 20 epochsa 16. epoch'tan sonra)
            lr = self.base_lr / 10
        elif current_epoch >= total_epochs * 0.5:
            # İkinci yarı (Örn: 20 epochsa 10. epoch'tan sonra)
            lr = self.base_lr / 5

        # Optimizer'daki hızı güncelle
        for param_group in self.optimizer.param_groups:
            param_group['lr'] = lr

        print(f"📉 Epoch {current_epoch + 1} İçin Learning Rate: {lr:.6f}")