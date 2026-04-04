"""
Tapo C210 Local Music Player
Lejátssz egy MP3 fájlt a Tapo C210 kamera beépített hangszóróján.

Konfiguráció: .env fájl (lásd .env.example)
Futtatás:
    python main.py
    python main.py --file music/other_song.mp3
    python main.py --verbose
"""

import argparse
import logging
import os
import sys

from dotenv import load_dotenv

from tapo_player import TapoAudioPlayer

# .env fájl betöltése (ha létezik)
load_dotenv()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="MP3 lejátszás Tapo C210 kamera hangszóróján"
    )
    parser.add_argument(
        "--file", "-f",
        default=None,
        help="MP3 fájl elérési útja (felülírja a MUSIC_FILE env változót)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Részletes naplózás",
    )
    return parser.parse_args()


def get_env(name: str) -> str:
    """Kötelező env változó lekérése; hiány esetén kilép."""
    value = os.getenv(name)
    if not value:
        print(f"[HIBA] Hiányzó konfiguráció: {name}", file=sys.stderr)
        print("       Hozd létre a .env fájlt a .env.example alapján:", file=sys.stderr)
        print("         cp .env.example .env", file=sys.stderr)
        sys.exit(1)
    return value


def main() -> None:
    args = parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # Konfiguráció beolvasása
    host = get_env("TAPO_IP")
    user = get_env("TAPO_USER")
    password = get_env("TAPO_PASSWORD")

    # Fájl: CLI argumentum > env változó > alapértelmezett
    music_file = args.file or os.getenv("MUSIC_FILE", "music/sample.mp3")

    print(f"Kamera:  {host}")
    print(f"Fájl:    {music_file}")
    print()

    player = TapoAudioPlayer(host, user, password)

    try:
        player.play(music_file)
        print("Lejátszás sikeres!")
    except FileNotFoundError as exc:
        print(f"[HIBA] {exc}", file=sys.stderr)
        print(
            "       Helyezd az MP3 fájlt a music/ könyvtárba, "
            "vagy add meg a --file kapcsolóval.",
            file=sys.stderr,
        )
        sys.exit(1)
    except EnvironmentError as exc:
        print(f"[HIBA] {exc}", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as exc:
        print(f"[HIBA] Streaming sikertelen: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"[HIBA] Váratlan hiba: {exc}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
