"""
Tapo C210 Music Player – REST API szerver
Home Assistant (és bármilyen HTTP kliens) számára.

Végpontok:
    POST /play              – lejátszás indítása
    POST /stop              – lejátszás leállítása
    GET  /status            – aktuális státusz JSON-ban
    POST /volume            – hangerő beállítása (0–100)
    GET  /volume            – aktuális hangerő lekérdezése

Futtatás:
    python server.py
    python server.py --host 0.0.0.0 --port 8099
"""

import argparse
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from pytapo import Tapo

from tapo_player import TapoAudioPlayer

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Globális lejátszó állapot (szálbiztos)
# ---------------------------------------------------------------------------

class PlayerState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.playing: bool = False
        self.current_file: Optional[str] = None
        self.started_at: Optional[float] = None
        self.volume: int = 50                  # utoljára beállított hangerő (0-100)
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self, file: str, host: str, user: str, password: str) -> None:
        with self._lock:
            if self.playing:
                raise RuntimeError("Már játszik valami, először állítsd le.")
            self._stop_event.clear()
            self.playing = True
            self.current_file = file
            self.started_at = time.time()
            self._thread = threading.Thread(
                target=self._run,
                args=(file, host, user, password),
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> bool:
        """Leállítja a lejátszást. True, ha volt mit leállítani."""
        with self._lock:
            if not self.playing:
                return False
            self._stop_event.set()

        if self._thread:
            self._thread.join(timeout=3.0)

        self._reset()
        return True

    def status(self) -> dict:
        with self._lock:
            elapsed = (
                round(time.time() - self.started_at, 1)
                if self.started_at
                else None
            )
            return {
                "playing": self.playing,
                "file": self.current_file,
                "elapsed_seconds": elapsed,
                "volume": self.volume,
            }

    def _run(self, file: str, host: str, user: str, password: str) -> None:
        try:
            player = TapoAudioPlayer(host, user, password)
            player.play(file)
        except Exception as exc:
            logger.error("Lejátszási hiba: %s", exc)
        finally:
            self._reset()

    def _reset(self) -> None:
        with self._lock:
            self.playing = False
            self.current_file = None
            self.started_at = None
            self._thread = None


_state = PlayerState()


# ---------------------------------------------------------------------------
# FastAPI alkalmazás
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Tapo Music API szerver indul...")
    yield
    logger.info("Tapo Music API szerver leáll.")
    _state.stop()


app = FastAPI(
    title="Tapo C210 Music Player API",
    description=(
        "Home Assistant integrációhoz REST API "
        "a Tapo C210 kamera hangszóró vezérléséhez."
    ),
    version="1.1.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Request/Response modellek
# ---------------------------------------------------------------------------

class PlayRequest(BaseModel):
    file: Optional[str] = None
    """MP3 fájl elérési útja. Ha nincs megadva, a MUSIC_FILE env változót használja."""


class VolumeRequest(BaseModel):
    level: int = Field(..., ge=0, le=100, description="Hangerő 0-tól 100-ig")


class StatusResponse(BaseModel):
    playing: bool
    file: Optional[str]
    elapsed_seconds: Optional[float]
    volume: int


class VolumeResponse(BaseModel):
    volume: int


# ---------------------------------------------------------------------------
# Segédfüggvények
# ---------------------------------------------------------------------------

def _get_config() -> tuple[str, str, str]:
    """Kamera konfigurációt olvas az env-ből, hibát dob ha hiányzik."""
    host = os.getenv("TAPO_IP")
    user = os.getenv("TAPO_USER")
    password = os.getenv("TAPO_PASSWORD")

    missing = [
        k for k, v in {
            "TAPO_IP": host,
            "TAPO_USER": user,
            "TAPO_PASSWORD": password,
        }.items()
        if not v
    ]
    if missing:
        raise HTTPException(
            status_code=500,
            detail=f"Hiányzó környezeti változók: {', '.join(missing)}. Ellenőrizd a .env fájlt.",
        )
    return host, user, password


def _get_tapo() -> Tapo:
    """Visszaad egy Tapo kamera kapcsolatot."""
    host, user, password = _get_config()
    return Tapo(host, user, password)


# ---------------------------------------------------------------------------
# Lejátszás végpontok
# ---------------------------------------------------------------------------

@app.post("/play", summary="Lejátszás indítása")
def play(request: PlayRequest = PlayRequest()):
    """
    Elindítja az MP3 lejátszást a Tapo C210 kamera hangszóróján.
    Ha már játszik valami, 409 Conflict hibát ad vissza.
    """
    host, user, password = _get_config()
    music_file = request.file or os.getenv("MUSIC_FILE", "music/sample.mp3")

    if not os.path.exists(music_file):
        raise HTTPException(
            status_code=404,
            detail=f"Fájl nem található: {music_file}",
        )

    try:
        _state.start(music_file, host, user, password)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    logger.info("Lejátszás indítva: %s", music_file)
    return {"status": "playing", "file": music_file}


@app.post("/stop", summary="Lejátszás leállítása")
def stop():
    """
    Leállítja az aktív lejátszást.
    Ha nem játszik semmi, 200-at ad vissza (idempotens).
    """
    was_playing = _state.stop()
    logger.info("Lejátszás leállítva (volt aktív: %s)", was_playing)
    return {"status": "stopped", "was_playing": was_playing}


@app.get("/status", response_model=StatusResponse, summary="Aktuális státusz")
def status():
    """
    Visszaadja az aktuális lejátszási státuszt és a hangerőt.
    Home Assistant sensor erre pollol.
    """
    return _state.status()


# ---------------------------------------------------------------------------
# Hangerő végpontok
# ---------------------------------------------------------------------------

@app.post("/volume", response_model=VolumeResponse, summary="Hangerő beállítása")
def set_volume(request: VolumeRequest):
    """
    Beállítja a kamera hangszórójának hangerejét (0–100).
    A beállítás azonnal érvényes, lejátszás közben is működik.
    """
    tapo = _get_tapo()

    try:
        # pytapo setSpeakerVolume / setVolume metódus (verziótól függően)
        if hasattr(tapo, "setSpeakerVolume"):
            tapo.setSpeakerVolume(request.level)
        elif hasattr(tapo, "setVolume"):
            tapo.setVolume(request.level)
        else:
            # Fallback: device info PUT-on keresztül
            tapo.setDeviceInfo({"speaker_volume": request.level})
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Hangerő beállítás sikertelen: {exc}",
        )

    _state.volume = request.level
    logger.info("Hangerő beállítva: %d%%", request.level)
    return {"volume": request.level}


@app.get("/volume", response_model=VolumeResponse, summary="Aktuális hangerő lekérdezése")
def get_volume():
    """
    Lekérdezi a kamera aktuális hangszóró hangerejét közvetlenül a kamerától.
    """
    tapo = _get_tapo()

    try:
        if hasattr(tapo, "getSpeakerVolume"):
            level = tapo.getSpeakerVolume()
        elif hasattr(tapo, "getVolume"):
            level = tapo.getVolume()
        else:
            # Nem támogatott – visszaadjuk az utolsó ismert értéket
            level = _state.volume
    except Exception as exc:
        logger.warning("Hangerő lekérdezés sikertelen, utolsó ismert érték: %s", exc)
        level = _state.volume

    _state.volume = int(level)
    return {"volume": _state.volume}


# ---------------------------------------------------------------------------
# Egyéb
# ---------------------------------------------------------------------------

@app.get("/health", include_in_schema=False)
def health():
    return {"ok": True}


# ---------------------------------------------------------------------------
# CLI belépési pont
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tapo Music Player API szerver")
    parser.add_argument("--host", default="0.0.0.0", help="Bind cím (alapért.: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8099, help="Port (alapért.: 8099)")
    parser.add_argument("--reload", action="store_true", help="Auto-reload fejlesztéshez")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    uvicorn.run(
        "server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
