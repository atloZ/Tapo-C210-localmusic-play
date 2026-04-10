# Tapo C210 Local Music Player

MP3 fájlt játszik le a Tapo C210 IP kamera beépített hangszóróján helyi hálózaton keresztül, Python script segítségével. Home Assistant dashboardról vezérelhető: lejátszás indítása, leállítása, hangerő-szabályozás csúszkával, státusz megjelenítés.

---

## Tartalom

- [Előfeltételek](#előfeltételek)
- [Telepítés](#telepítés)
- [Konfiguráció](#konfiguráció)
- [Parancssori használat](#parancssori-használat)
- [Docker deploy](#docker-deploy)
- [Home Assistant integráció](#home-assistant-integráció)
- [API referencia](#api-referencia)
- [Könyvtárstruktúra](#könyvtárstruktúra)
- [Hibaelhárítás](#hibaelhárítás)

---

## Előfeltételek

| Eszköz | Verzió |
|--------|--------|
| Python | 3.10+ |
| ffmpeg | bármely aktuális |
| Tapo C210 | azonos LAN-on a szerverrel |

### ffmpeg telepítése

```bash
# Ubuntu / Debian
sudo apt install ffmpeg

# macOS
brew install ffmpeg

# Windows – töltsd le és add hozzá a PATH-hoz:
# https://ffmpeg.org/download.html
```

---

## Telepítés

```bash
git clone <repo_url>
cd Tapo-C210-localmusic-play

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

---

## Konfiguráció

Hozd létre a `.env` fájlt a sablon alapján:

```bash
cp .env.example .env
```

Majd szerkeszd ki:

```ini
TAPO_IP=192.168.1.100         # kamera IP-je
TAPO_USER=email@example.com   # Tapo fiók e-mail
TAPO_PASSWORD=jelszo          # Tapo fiók jelszó
MUSIC_FILE=music/sample.mp3   # alapértelmezett MP3 fájl
```

> A kamera IP-jét megtalálod a routered admin felületén vagy a Tapo appban:
> **Eszköz → Beállítások → Eszköz info**

---

## Parancssori használat

Másold az MP3 fájlodat a `music/` könyvtárba, majd:

```bash
# Alapértelmezett fájl lejátszása (.env-ből)
python main.py

# Explicit fájl megadása
python main.py --file music/dal.mp3

# Részletes naplózás
python main.py --verbose
```

---

## Docker deploy

A szerver Docker konténerként fut, ami izolált, könnyen indítható és újraindítható.

### Hálózat (fontos!)

A `docker-compose.yml` **`network_mode: host`** módot használ:
- A konténer a gazdagép hálózatán ül → közvetlenül éri a Tapo kamerát
- A HAOS a **gazdagép LAN IP-jén** (pl. `192.168.1.50`) éri el a `8099`-es portot

### Előfeltétel: Docker telepítése

```bash
# Ubuntu / Debian / Raspberry Pi OS
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER   # logout + login után hatásos
```

### 1. Konfiguráció

```bash
cp .env.example .env
# Szerkeszd ki: TAPO_IP, TAPO_USER, TAPO_PASSWORD, MUSIC_FILE
```

### 2. MP3 fájl elhelyezése

```bash
cp /ut/a/dalodhoz/dal.mp3 music/
```

A `./music/` mappa be van csatolva a konténerbe – **nem kell rebuild** új fájl hozzáadásakor.

### 3. Build és indítás

```bash
docker compose up -d --build
```

### Ellenőrzés

```bash
# Szerver él?
curl http://localhost:8099/health
# → {"ok": true}

# Státusz
curl http://localhost:8099/status
# → {"playing": false, "file": null, "elapsed_seconds": null, "volume": 50}

# Teszt lejátszás
curl -X POST http://localhost:8099/play
```

### Hasznos parancsok

| Parancs | Leírás |
|---------|--------|
| `docker compose up -d --build` | Build + indítás háttérben |
| `docker compose logs -f` | Élő naplók |
| `docker compose restart` | Újraindítás (pl. .env változás után) |
| `docker compose down` | Leállítás |
| `docker compose pull && docker compose up -d --build` | Frissítés |

### Szerver IP meghatározása a HAOS bekötéshez

```bash
hostname -I | awk '{print $1}'
# pl. 192.168.1.50  ← ezt kell beírni PLAYER_SERVER_IP helyére
```

---

## Home Assistant integráció

### Architektúra

```
HA Dashboard
  │
  ├─ Play/Stop gomb ──► POST /play  /stop
  ├─ Hangerő csúszka ─► POST /volume
  └─ Státusz szenzor ◄─ GET  /status  (5 mp-enként)
                              │
                        server.py (FastAPI)
                              │
                        TapoAudioPlayer
                              │
                        Tapo C210 hangszóró
```

---

### 1. lépés – REST API szerver indítása

```bash
# Aktivált venv-ben:
python server.py
# Explicit cím/port:
python server.py --host 0.0.0.0 --port 8099
```

Elérhető: `http://<szerver_ip>:8099`
Swagger dokumentáció: `http://<szerver_ip>:8099/docs`

#### Automatikus indítás (systemd, Linux)

Hozz létre `/etc/systemd/system/tapo-music.service` fájlt:

```ini
[Unit]
Description=Tapo C210 Music Player API
After=network.target

[Service]
User=<felhasználónév>
WorkingDirectory=/home/<felhasználónév>/Tapo-C210-localmusic-play
ExecStart=/home/<felhasználónév>/Tapo-C210-localmusic-play/venv/bin/python server.py
Restart=on-failure
EnvironmentFile=/home/<felhasználónév>/Tapo-C210-localmusic-play/.env

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable tapo-music
sudo systemctl start tapo-music
```

---

### 2. lépés – Home Assistant konfiguráció

Add hozzá a következő blokkot a `configuration.yaml` fájlhoz.

> **Csere:** `PLAYER_SERVER_IP` → a szerver IP-je (pl. `192.168.1.50`)

```yaml
# REST szenzor – státusz + hangerő lekérdezés 5 mp-enként
sensor:
  - platform: rest
    name: "Tapo Music Status"
    unique_id: tapo_music_status
    resource: "http://PLAYER_SERVER_IP:8099/status"
    scan_interval: 5
    value_template: "{{ 'playing' if value_json.playing else 'stopped' }}"
    json_attributes:
      - file
      - elapsed_seconds
      - volume

# Hangerő csúszka entitás (0–100, lépés: 5)
number:
  - platform: template
    numbers:
      tapo_volume:
        name: "Tapo Hangerő"
        unique_id: tapo_music_volume
        min: 0
        max: 100
        step: 5
        icon: mdi:volume-high
        value_template: "{{ state_attr('sensor.tapo_music_status', 'volume') | int(50) }}"
        set_value:
          service: shell_command.tapo_set_volume
          data:
            level: "{{ value | int }}"

# Shell parancsok
shell_command:
  tapo_play:  "curl -s -X POST http://PLAYER_SERVER_IP:8099/play"
  tapo_stop:  "curl -s -X POST http://PLAYER_SERVER_IP:8099/stop"
  tapo_set_volume: >-
    curl -s -X POST http://PLAYER_SERVER_IP:8099/volume
    -H "Content-Type: application/json"
    -d "{\"level\": {{ level }}}"

# Scriptek
script:
  play_tapo_music:
    alias: "Tapo kamera zene lejátszás"
    sequence:
      - service: shell_command.tapo_play

  stop_tapo_music:
    alias: "Tapo kamera zene leállítás"
    sequence:
      - service: shell_command.tapo_stop

  set_tapo_volume:
    alias: "Tapo hangerő beállítás"
    fields:
      level:
        description: "Hangerő 0-tól 100-ig"
        default: 50
    sequence:
      - service: shell_command.tapo_set_volume
        data:
          level: "{{ level }}"
```

A kész sablon: [`ha_config/configuration.yaml`](ha_config/configuration.yaml)

Módosítás után töltsd újra a HA konfigurációt:
**Beállítások → Rendszer → Konfiguráció ellenőrzése → Újratöltés**

---

### 3. lépés – Dashboard kártya hozzáadása

1. Lovelace dashboard → **Szerkesztés** → **Kártya hozzáadása**
2. Görgess le: **Manuális kártya** → YAML nézet
3. Illeszd be a [`ha_config/dashboard.yaml`](ha_config/dashboard.yaml) tartalmát

A dashboard kártyán megjelenik:

| Elem | Leírás |
|------|--------|
| Státusz felirat | `PLAYING` vagy `STOPPED` |
| Fájlnév | éppen játszott MP3 |
| Eltelt idő | másodpercben |
| **Play gomb** | zölden világít lejátszás közben |
| **Stop gomb** | pirosan világít lejátszás közben |
| **Hangerő csúszka** | 0–100, azonnal beállítja a kamerát |
| Gyors hangerő gombok | 25% / 50% / 75% / 100% |

> A gomb-szín visszajelzéshez a [card-mod](https://github.com/thomasloven/lovelace-card-mod) HACS kiegészítő szükséges. A gombok e nélkül is működnek.

---

## API referencia

| Metódus | URL | Leírás |
|---------|-----|--------|
| `POST` | `/play` | Lejátszás indítása |
| `POST` | `/stop` | Lejátszás leállítása |
| `GET` | `/status` | Státusz + hangerő lekérdezése |
| `POST` | `/volume` | Hangerő beállítása |
| `GET` | `/volume` | Hangerő lekérdezése a kamerától |
| `GET` | `/docs` | Swagger UI dokumentáció |
| `GET` | `/health` | Szerver életjel |

### Státusz válasz (`GET /status`)

```json
{
  "playing": true,
  "file": "music/sample.mp3",
  "elapsed_seconds": 12.4,
  "volume": 70
}
```

### Hangerő beállítás (`POST /volume`)

```bash
curl -X POST http://PLAYER_SERVER_IP:8099/volume \
     -H "Content-Type: application/json" \
     -d '{"level": 70}'
```

Válasz:
```json
{ "volume": 70 }
```

### Egyedi fájl lejátszása

```bash
curl -X POST http://PLAYER_SERVER_IP:8099/play \
     -H "Content-Type: application/json" \
     -d '{"file": "music/masik_dal.mp3"}'
```

---

## Könyvtárstruktúra

```
Tapo-C210-localmusic-play/
├── main.py              # Parancssori lejátszó
├── server.py            # FastAPI REST szerver (HA integrációhoz)
├── tapo_player.py       # TapoAudioPlayer osztály
├── requirements.txt     # Python függőségek
├── Dockerfile           # Docker image leírása
├── docker-compose.yml   # Konténer konfiguráció (host network, volume, healthcheck)
├── .dockerignore        # Docker build-ből kizárt fájlok
├── .env.example         # Konfiguráció sablon
├── .gitignore
├── music/               # MP3 fájlok helye (host volume)
│   └── .gitkeep
└── ha_config/           # Home Assistant konfigurációs sablonok
    ├── configuration.yaml   # HA config (sensor, number, shell_command, script)
    ├── dashboard.yaml       # Lovelace kártya
    └── automations.yaml     # Opcionális automatizációk
```

---

## Hibaelhárítás

### `ffmpeg: command not found`
Telepítsd az ffmpeg-et – lásd [Előfeltételek](#előfeltételek).

### `Connection refused` a kamerához
- Ellenőrizd, hogy a kamera és a szerver azonos LAN-on van
- Pingeld a kamerát: `ping 192.168.1.100`
- Ellenőrizd a `.env`-ben lévő IP-t

### `FileNotFoundError: music/sample.mp3`
- Másold az MP3 fájlt a `music/` könyvtárba
- Vagy add meg a `--file` kapcsolóval: `python main.py --file /ut/dal.mp3`

### HA szenzor `unavailable` állapotban
- Ellenőrizd, hogy a `server.py` fut-e: `curl http://PLAYER_SERVER_IP:8099/health`
- Ellenőrizd, hogy a HA eléri a szerver IP-jét és portját
- HA naplók: **Beállítások → Rendszer → Naplók**

### Hangerő csúszka nem jelenik meg a dashboardon
- Ellenőrizd, hogy a `number` entitás létrejött-e: **Beállítások → Entitások** → keress rá: `tapo_volume`
- HA 2023.x+ szükséges a template number platformhoz

### `pytapo audio session nem elérhető` figyelmeztetés
Ez nem hiba – a szerver automatikusan ffmpeg RTSP fallback-re vált. Ha a fallback is sikertelen, frissítsd a pytapo könyvtárat:
```bash
pip install --upgrade pytapo
```

### Docker: `Permission denied` a `music/` mappán
```bash
chmod -R 755 music/
```

### Docker: konténer elindul, de a kamera nem érhető el
Ellenőrizd, hogy `network_mode: host` van-e a `docker-compose.yml`-ben.
Bridge hálózat esetén a konténer nem látja közvetlenül a LAN eszközöket.

### Docker: változtattam a `.env`-ben, de nem hat
```bash
docker compose restart   # elegendő, nem kell rebuild
```

### Docker: port foglalt (`address already in use`)
Valami más is használja a 8099-es portot. Módosítsd a portot a `docker-compose.yml`-ben
és a `.env` / HA konfigurációban egységesen.
