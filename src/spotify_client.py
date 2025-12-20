import spotipy
from spotipy.oauth2 import SpotifyOAuth
from . import config


class SpotifyHandler:
    def __init__(self):
        print("🌍 Spotify Bağlantısı Kuruluyor...")
        try:
            self.sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
                client_id=config.SPOTIPY_CLIENT_ID,
                client_secret=config.SPOTIPY_CLIENT_SECRET,
                redirect_uri=config.SPOTIPY_REDIRECT_URI,
                scope="playlist-modify-public playlist-modify-private"
            ))
            self.user_id = self.sp.current_user()['id']
            print(f"✅ Giriş Başarılı! Kullanıcı: {self.user_id}")
        except Exception as e:
            print(f"❌ Spotify Giriş Hatası: {e}")
            self.sp = None

    def create_playlist_from_ids(self, track_ids, playlist_name, description="AI Hybrid Model"):
        if not self.sp or not track_ids: return

        try:
            print(f"🔨 Playlist: {playlist_name}")
            playlist = self.sp.user_playlist_create(
                user=self.user_id, name=playlist_name, public=True, description=description
            )

            uris = [tid if str(tid).startswith("spotify:track:") else f"spotify:track:{tid}" for tid in track_ids]

            for i in range(0, len(uris), 100):
                self.sp.playlist_add_items(playlist['id'], uris[i:i + 100])
                print(f"   ➕ {len(uris[i:i + 100])} eklendi...")

            print(f"🎉 LİNK: {playlist['external_urls']['spotify']}")
        except Exception as e:
            print(f"❌ Yükleme Hatası: {e}")