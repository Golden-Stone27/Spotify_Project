import os

os.environ["HSA_OVERRIDE_GFX_VERSION"] = "10.3.0"
os.environ["ROCM_PATH"] = "/opt/rocm"
import torch
import torch.nn as nn
import torch.nn.functional as F


class VibeStudent(nn.Module):
    def __init__(self, input_size, output_size):
        super(VibeStudent, self).__init__()

        # Katman 1: Genişletilmiş nöron sayısı
        self.fc1 = nn.Linear(input_size, 512)

        # DÜZELTME: BatchNorm yerine LayerNorm kullanıyoruz.
        # LayerNorm, tek tek gelen verilerle (Batch Size=1) çalışabilir.
        self.bn1 = nn.LayerNorm(512)

        # Katman 2
        self.fc2 = nn.Linear(512, 256)
        self.dropout = nn.Dropout(0.3)

        # Çıkış
        self.fc3 = nn.Linear(256, output_size)

    def forward(self, x):
        x = self.fc1(x)
        x = self.bn1(x)
        x = F.relu(x)

        x = F.relu(self.fc2(x))
        x = self.dropout(x)

        x = self.fc3(x)
        return x

    def save_model(self, path="vibe_student.pth"):
        torch.save(self.state_dict(), path)
        print(f"💾 Model kaydedildi: {path}")

    def load_model(self, path="vibe_student.pth"):
        # weights_only=True ile güvenli yükleme
        self.load_state_dict(torch.load(path, weights_only=True))
        print(f"📂 Model yüklendi: {path}")