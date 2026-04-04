"""
TapoAudioPlayer – MP3 lejátszás Tapo C210 kamera hangszóróján keresztül.

A kamera two-way audio protokollt használ a hangátvitelhez.
Az MP3 fájlt G.711 μ-law formátumra konvertáljuk (8 kHz, mono),
mert ezt fogadja el a kamera belső hangszórója.

Rendszer-szintű függőség: ffmpeg
"""

import logging
import os
import subprocess
import tempfile
import time

from pytapo import Tapo

logger = logging.getLogger(__name__)

# A Tapo C210 által elvárt audio paraméterek
SAMPLE_RATE = 8000   # Hz
CHANNELS = 1         # mono
CODEC = "pcm_mulaw"  # G.711 μ-law


class TapoAudioPlayer:
    """
    MP3 fájlt játszik le a Tapo C210 kamera beépített hangszóróján.

    Példa:
        player = TapoAudioPlayer("192.168.1.100", "user@email.com", "jelszo")
        player.play("music/sample.mp3")
    """

    def __init__(self, host: str, user: str, password: str):
        """
        Args:
            host:     A kamera IP-címe (pl. "192.168.1.100")
            user:     Tapo fiók e-mail cím
            password: Tapo fiók jelszó
        """
        self.host = host
        self.user = user
        self.password = password
        self._tapo: Tapo | None = None

    # ------------------------------------------------------------------
    # Nyilvános API
    # ------------------------------------------------------------------

    def connect(self) -> "TapoAudioPlayer":
        """Kapcsolódik a kamerához és ellenőrzi az elérhetőségét."""
        logger.info("Kapcsolódás a kamerához: %s", self.host)
        self._tapo = Tapo(self.host, self.user, self.password)
        try:
            info = self._tapo.getDeviceInfo()
            alias = (
                info.get("device_info", {})
                .get("basic_info", {})
                .get("device_alias", "ismeretlen")
            )
            logger.info("Sikeresen kapcsolódva: %s (%s)", alias, self.host)
        except Exception as exc:
            logger.warning("Eszközinfo lekérés sikertelen (folytatás): %s", exc)
        return self

    def play(self, mp3_path: str) -> None:
        """
        Lejátssza a megadott MP3 fájlt a kamera hangszóróján.

        Args:
            mp3_path: Az MP3 fájl elérési útja

        Raises:
            FileNotFoundError: Ha a fájl nem létezik
            RuntimeError:      Ha a konverzió vagy a streaming sikertelen
        """
        if not os.path.exists(mp3_path):
            raise FileNotFoundError(f"Az audio fájl nem található: {mp3_path}")

        if self._tapo is None:
            self.connect()

        logger.info("Lejátszás indul: %s", mp3_path)

        pcm_path = self._convert_to_pcm(mp3_path)
        try:
            self._stream_to_camera(pcm_path)
        finally:
            _safe_remove(pcm_path)

        logger.info("Lejátszás befejezve.")

    # ------------------------------------------------------------------
    # Belső metódusok
    # ------------------------------------------------------------------

    def _convert_to_pcm(self, mp3_path: str) -> str:
        """
        MP3 → G.711 μ-law WAV konverzió ffmpeg segítségével.

        Returns:
            Az ideiglenes WAV fájl elérési útja (törlés a hívó felelőssége)
        """
        _check_ffmpeg()

        fd, tmp_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)

        cmd = [
            "ffmpeg", "-y",
            "-i", mp3_path,
            "-vn",                      # nincs videó
            "-acodec", CODEC,           # G.711 μ-law
            "-ar", str(SAMPLE_RATE),    # 8000 Hz
            "-ac", str(CHANNELS),       # mono
            tmp_path,
        ]

        logger.debug("ffmpeg parancs: %s", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            _safe_remove(tmp_path)
            raise RuntimeError(
                f"ffmpeg konverzió sikertelen:\n{result.stderr[-500:]}"
            )

        logger.info("PCM konverzió kész: %s", tmp_path)
        return tmp_path

    def _stream_to_camera(self, pcm_path: str) -> None:
        """
        A konvertált PCM fájlt streameli a kamera hangszóróján keresztül
        a pytapo two-way audio protokollja segítségével.

        Ha a pytapo verzió nem támogatja a natív audio session-t,
        ffmpeg RTSP backchannel-re vált vissza.
        """
        # WAV fejléc kihagyása (44 byte)
        with open(pcm_path, "rb") as f:
            f.read(44)
            pcm_data = f.read()

        data_len = len(pcm_data)
        logger.info("Streaming: %d byte audio adat", data_len)

        # 1. kísérlet: pytapo natív audio session (v3.x+)
        if self._try_pytapo_audio(pcm_data):
            return

        # 2. kísérlet: ffmpeg RTSP backchannel (régebbi pytapo / más firmware)
        logger.info("Fallback: ffmpeg RTSP backchannel")
        self._stream_via_ffmpeg(pcm_path)

    def _try_pytapo_audio(self, pcm_data: bytes) -> bool:
        """
        pytapo natív audio session használata.

        Returns:
            True, ha sikeres; False, ha nem támogatott és fallback kell.
        """
        tapo = self._tapo

        # startAudioSession elérhetőségének ellenőrzése
        if not hasattr(tapo, "startAudioSession"):
            logger.debug("pytapo.startAudioSession nem elérhető, fallback következik")
            return False

        try:
            session = tapo.startAudioSession()

            # Streaming 1 másodperces (8000 byte) darabokban
            chunk_size = SAMPLE_RATE
            total = len(pcm_data)
            sent = 0

            while sent < total:
                chunk = pcm_data[sent : sent + chunk_size]
                session.transmitAudio(chunk)
                sent += len(chunk)
                # Valós idejű lejátszás szimulálása
                time.sleep(chunk_size / SAMPLE_RATE)

            session.close()
            return True

        except Exception as exc:
            logger.warning("pytapo audio session hiba: %s – fallback következik", exc)
            return False

    def _stream_via_ffmpeg(self, audio_path: str) -> None:
        """
        Fallback: ffmpeg RTSP backchannel streaming.

        Egyes Tapo firmware-ek elfogadják az audio adatot ezen a módon.
        """
        rtsp_url = (
            f"rtsp://{self.user}:{self.password}"
            f"@{self.host}:554/stream1"
        )

        cmd = [
            "ffmpeg", "-re",
            "-i", audio_path,
            "-vn",
            "-acodec", "copy",
            "-f", "rtsp",
            "-rtsp_transport", "tcp",
            rtsp_url,
        ]

        logger.debug("ffmpeg RTSP parancs: %s", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            raise RuntimeError(
                f"ffmpeg RTSP streaming sikertelen:\n{result.stderr[-500:]}"
            )


# ------------------------------------------------------------------
# Segédfüggvények
# ------------------------------------------------------------------

def _check_ffmpeg() -> None:
    """Ellenőrzi, hogy ffmpeg telepítve van-e."""
    result = subprocess.run(
        ["ffmpeg", "-version"], capture_output=True, text=True
    )
    if result.returncode != 0:
        raise EnvironmentError(
            "ffmpeg nem található. Telepítés:\n"
            "  Ubuntu/Debian: sudo apt install ffmpeg\n"
            "  macOS:         brew install ffmpeg\n"
            "  Windows:       https://ffmpeg.org/download.html"
        )


def _safe_remove(path: str) -> None:
    """Fájl törlése hiba nélkül, ha létezik."""
    try:
        if path and os.path.exists(path):
            os.unlink(path)
    except OSError:
        pass
