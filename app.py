import eventlet
eventlet.monkey_patch()

import os
import re
import uuid
import json
import subprocess
from datetime import datetime

import yt_dlp
from flask import Flask, render_template, request, jsonify, send_from_directory, session, redirect
from flask_socketio import SocketIO


app = Flask(__name__)
app.config["SECRET_KEY"] = "sr-mediadrop-local-secret"

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="eventlet"
)

BASE_DIR = os.getcwd()
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
DATA_DIR = os.path.join(BASE_DIR, "data")
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

APP_PIN = os.environ.get("MEDIADROP_PIN", "1234")

jobs = {}


# ==========================================================
# GENERAL HELPERS
# ==========================================================

def load_history():
    if not os.path.exists(HISTORY_FILE):
        return []

    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return []


def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as file:
        json.dump(history, file, indent=2, ensure_ascii=False)


def add_history(item):
    history = load_history()
    history.insert(0, item)
    history = history[:80]
    save_history(history)


def seconds_to_time(seconds):
    if not seconds:
        return "Desconocido"

    try:
        seconds = int(seconds)
    except Exception:
        return "Desconocido"

    minutes = seconds // 60
    secs = seconds % 60

    if minutes >= 60:
        hours = minutes // 60
        minutes = minutes % 60
        return f"{hours}h {minutes}m"

    return f"{minutes}m {secs}s"


def clean_text(value):
    if not value:
        return ""

    value = str(value)
    value = re.sub(r"\x1b\[[0-9;]*m", "", value)

    return value.strip()


def clean_error(error):
    msg = str(error)

    if "Requested format is not available" in msg:
        return "El formato solicitado no está disponible. Prueba otra calidad o MP3."

    if "Sign in to confirm" in msg or "not a bot" in msg:
        return "YouTube pidió verificación. Prueba actualizar yt-dlp o usar otro video."

    if "HTTP Error 429" in msg or "Too Many Requests" in msg:
        return "La plataforma limitó temporalmente las solicitudes. Espera unos minutos e intenta otra vez."

    if "Unsupported URL" in msg:
        return "Ese enlace no es compatible."

    return msg


def emit_progress(job_id, payload):
    if job_id not in jobs:
        return

    jobs[job_id].update(payload)

    socketio.emit("progress", {
        "job_id": job_id,
        **jobs[job_id]
    })

    socketio.sleep(0)


def check_command(command):
    try:
        subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True
        )
        return True
    except Exception:
        return False


def get_file_size(filename):
    path = os.path.join(DOWNLOAD_DIR, filename)

    if not os.path.exists(path):
        return "Desconocido"

    size = os.path.getsize(path)

    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"

    if size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"

    return f"{size / (1024 * 1024 * 1024):.1f} GB"


def get_newest_file(before_files):
    after_files = set(os.listdir(DOWNLOAD_DIR))
    new_files = list(after_files - before_files)

    candidates = [
        f for f in new_files
        if os.path.isfile(os.path.join(DOWNLOAD_DIR, f))
    ]

    if not candidates:
        candidates = [
            f for f in os.listdir(DOWNLOAD_DIR)
            if os.path.isfile(os.path.join(DOWNLOAD_DIR, f))
        ]

    if not candidates:
        return None

    return sorted(
        candidates,
        key=lambda f: os.path.getmtime(os.path.join(DOWNLOAD_DIR, f)),
        reverse=True
    )[0]


# ==========================================================
# YT-DLP HELPERS
# ==========================================================

def base_ydl_opts():
    return {
        "quiet": True,
        "no_warnings": True,
        "noprogress": False,
        "nopart": False,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "es-CR,es;q=0.9,en;q=0.8",
        },
    }


def progress_hook(job_id):
    def hook(d):
        status = d.get("status")

        if status == "downloading":
            downloaded = d.get("downloaded_bytes") or 0
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0

            if total > 0:
                percent = (downloaded / total) * 100
            else:
                raw_percent = clean_text(d.get("_percent_str", "0")).replace("%", "")

                try:
                    percent = float(raw_percent)
                except Exception:
                    percent = 0

            percent = max(0, min(100, percent))

            emit_progress(job_id, {
                "status": "downloading",
                "progress": percent,
                "message": f"Descargando... {percent:.1f}%",
                "speed": clean_text(d.get("_speed_str", "")),
                "eta": clean_text(d.get("_eta_str", "")),
            })

        elif status == "finished":
            emit_progress(job_id, {
                "status": "processing",
                "progress": 96,
                "message": "Procesando archivo...",
            })

    return hook


def extract_available_qualities(info):
    formats = info.get("formats", [])
    qualities = {}

    for fmt in formats:
        height = fmt.get("height")
        vcodec = fmt.get("vcodec")

        if not height:
            continue

        if vcodec == "none":
            continue

        if height < 144:
            continue

        label = f"{height}p"

        if label not in qualities:
            qualities[label] = {
                "label": label,
                "value": str(height),
                "height": height,
            }

    return sorted(
        qualities.values(),
        key=lambda item: item["height"],
        reverse=True
    )


def get_best_thumbnail(info):
    thumbnail = info.get("thumbnail")

    if thumbnail:
        return thumbnail

    thumbnails = info.get("thumbnails", [])

    if not thumbnails:
        return ""

    valid_thumbnails = []

    for item in thumbnails:
        url = item.get("url")
        width = item.get("width") or 0
        height = item.get("height") or 0

        if url:
            valid_thumbnails.append({
                "url": url,
                "score": width * height
            })

    if not valid_thumbnails:
        return ""

    best = sorted(
        valid_thumbnails,
        key=lambda item: item["score"],
        reverse=True
    )[0]

    return best["url"]


def classify_link(url, info):
    url_lower = url.lower()

    is_playlist = "playlist" in url_lower or "list=" in url_lower
    is_tiktok = "tiktok.com" in url_lower
    is_instagram_reel = "instagram.com/reel" in url_lower or "instagram.com/reels" in url_lower
    is_youtube_shorts = "youtube.com/shorts" in url_lower or "youtu.be/shorts" in url_lower
    is_youtube_music = "music.youtube.com" in url_lower
    is_youtube = "youtube.com" in url_lower or "youtu.be" in url_lower

    has_music_metadata = bool(
        info.get("track") or
        info.get("artist") or
        info.get("album")
    )

    if is_playlist:
        return {
            "media_type": "playlist",
            "platform": "youtube",
            "platform_label": "YouTube Playlist",
            "platform_icon": "list-video",
            "allowed_types": ["video", "mp3"],
            "default_type": "video",
            "label": "Playlist detectada"
        }

    if is_tiktok:
        return {
            "media_type": "short",
            "platform": "tiktok",
            "platform_label": "TikTok",
            "platform_icon": "music-2",
            "allowed_types": ["mp3", "reels"],
            "default_type": "reels",
            "label": "TikTok detectado"
        }

    if is_instagram_reel:
        return {
            "media_type": "short",
            "platform": "instagram",
            "platform_label": "Instagram Reel",
            "platform_icon": "instagram",
            "allowed_types": ["mp3", "reels"],
            "default_type": "reels",
            "label": "Instagram Reel detectado"
        }

    if is_youtube_shorts:
        return {
            "media_type": "short",
            "platform": "youtube_shorts",
            "platform_label": "YouTube Shorts",
            "platform_icon": "badge-play",
            "allowed_types": ["mp3", "reels"],
            "default_type": "reels",
            "label": "YouTube Short detectado"
        }

    if is_youtube_music or has_music_metadata:
        return {
            "media_type": "music",
            "platform": "youtube_music",
            "platform_label": "YouTube Music",
            "platform_icon": "music",
            "allowed_types": ["mp3"],
            "default_type": "mp3",
            "label": "Canción detectada"
        }

    if is_youtube:
        return {
            "media_type": "video",
            "platform": "youtube",
            "platform_label": "YouTube",
            "platform_icon": "youtube",
            "allowed_types": ["video", "mp3"],
            "default_type": "video",
            "label": "Video de YouTube detectado"
        }

    return {
        "media_type": "video",
        "platform": "generic",
        "platform_label": "Video",
        "platform_icon": "video",
        "allowed_types": ["video", "mp3"],
        "default_type": "video",
        "label": "Video detectado"
    }


def quick_classify_url(url):
    url_lower = url.lower()

    if "tiktok.com" in url_lower:
        return {
            "is_quick": True,
            "title": "TikTok detectado",
            "thumbnail": "",
            "uploader": "TikTok",
            "duration": "Desconocido",
            "webpage_url": url,
            "qualities": [],
            "media_type": "short",
            "platform": "tiktok",
            "platform_label": "TikTok",
            "platform_icon": "music-2",
            "allowed_types": ["mp3", "reels"],
            "default_type": "reels",
            "label": "TikTok detectado"
        }

    if "instagram.com/reel" in url_lower or "instagram.com/reels" in url_lower:
        return {
            "is_quick": True,
            "title": "Instagram Reel detectado",
            "thumbnail": "",
            "uploader": "Instagram",
            "duration": "Desconocido",
            "webpage_url": url,
            "qualities": [],
            "media_type": "short",
            "platform": "instagram",
            "platform_label": "Instagram Reel",
            "platform_icon": "instagram",
            "allowed_types": ["mp3", "reels"],
            "default_type": "reels",
            "label": "Instagram Reel detectado"
        }

    return None


def build_ydl_options(job_id, download_type, quality):
    ydl_opts = base_ydl_opts()

    ydl_opts.update({
        "outtmpl": os.path.join(DOWNLOAD_DIR, "%(title).160s.%(ext)s"),
        "progress_hooks": [progress_hook(job_id)],
        "noplaylist": True,
        "ignoreerrors": False,
    })

    if download_type == "mp3":
        audio_quality = quality if quality in ["320", "192", "128"] else "320"

        ydl_opts.update({
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": audio_quality,
            }],
        })

    elif download_type == "reels":
        # Formato compatible para ProPresenter:
        # intenta MP4 H.264 + AAC/M4A primero.
        ydl_opts.update({
            "format": (
                "bestvideo[ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/"
                "best[ext=mp4][vcodec^=avc1]/"
                "best[ext=mp4]/"
                "best"
            ),
            "merge_output_format": "mp4",
            "postprocessors": [{
                "key": "FFmpegVideoConvertor",
                "preferedformat": "mp4",
            }],
        })

    else:
        if quality and quality != "best":
            try:
                height = int(quality)

                fmt = (
                    f"bestvideo[ext=mp4][vcodec^=avc1][height<={height}]+bestaudio[ext=m4a]/"
                    f"best[ext=mp4][vcodec^=avc1][height<={height}]/"
                    f"bestvideo[height<={height}]+bestaudio/"
                    f"best[height<={height}]/"
                    "best"
                )
            except ValueError:
                fmt = (
                    "bestvideo[ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/"
                    "best[ext=mp4][vcodec^=avc1]/"
                    "best"
                )
        else:
            fmt = (
                "bestvideo[ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/"
                "best[ext=mp4][vcodec^=avc1]/"
                "bestvideo[ext=mp4]+bestaudio[ext=m4a]/"
                "best[ext=mp4]/"
                "best"
            )

        ydl_opts.update({
            "format": fmt,
            "merge_output_format": "mp4",
            "postprocessors": [{
                "key": "FFmpegVideoConvertor",
                "preferedformat": "mp4",
            }],
        })

    return ydl_opts


# ==========================================================
# ROUTES: AUTH
# ==========================================================

@app.route("/")
def index():
    if not session.get("authenticated"):
        return render_template("login.html")

    return render_template("index.html")


@app.route("/login", methods=["POST"])
def login():
    data = request.json or {}
    pin = data.get("pin", "")

    if pin == APP_PIN:
        session["authenticated"] = True
        return jsonify({"success": True})

    return jsonify({
        "success": False,
        "error": "PIN incorrecto"
    }), 401


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"success": True})


# ==========================================================
# ROUTES: INFO + DOWNLOAD
# ==========================================================

@app.route("/info", methods=["POST"])
def get_video_info():
    if not session.get("authenticated"):
        return jsonify({"error": "No autorizado"}), 401

    data = request.json or {}
    url = data.get("url", "").strip()

    if not url:
        return jsonify({"error": "URL requerida"}), 400

    try:
        quick_info = quick_classify_url(url)

        if quick_info:
            return jsonify(quick_info)

        opts = base_ydl_opts()
        opts.update({
            "skip_download": True,
            "noplaylist": True,
        })

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

        link_data = classify_link(url, info)
        qualities = extract_available_qualities(info)

        return jsonify({
            "title": info.get("title", "Sin título"),
            "thumbnail": get_best_thumbnail(info),
            "uploader": info.get("uploader", "Desconocido"),
            "duration": seconds_to_time(info.get("duration")),
            "webpage_url": info.get("webpage_url", url),
            "qualities": qualities,
            **link_data
        })

    except Exception as e:
        return jsonify({"error": clean_error(e)}), 500


@app.route("/start", methods=["POST"])
def start_download():
    if not session.get("authenticated"):
        return jsonify({"error": "No autorizado"}), 401

    data = request.json or {}

    url = data.get("url", "").strip()
    download_type = data.get("type", "video")
    quality = data.get("quality", "best")
    title = data.get("title", "")

    if not url:
        return jsonify({"error": "URL requerida"}), 400

    job_id = str(uuid.uuid4())

    jobs[job_id] = {
        "status": "starting",
        "progress": 0,
        "message": "Preparando descarga...",
        "filename": None,
        "file_size": "",
        "speed": "",
        "eta": "",
        "title": title,
        "type": download_type,
        "url": url,
    }

    socketio.start_background_task(
        download_task,
        job_id,
        url,
        download_type,
        quality,
        title
    )

    return jsonify({"job_id": job_id})


@app.route("/start-queue", methods=["POST"])
def start_queue():
    if not session.get("authenticated"):
        return jsonify({"error": "No autorizado"}), 401

    data = request.json or {}
    items = data.get("items", [])

    if not items:
        return jsonify({"error": "No hay enlaces en la cola"}), 400

    queue_id = str(uuid.uuid4())
    queue_jobs = []

    for item in items:
        url = item.get("url", "").strip()
        download_type = item.get("type", "video")
        quality = item.get("quality", "best")
        title = item.get("title", "")

        if not url:
            continue

        job_id = str(uuid.uuid4())

        jobs[job_id] = {
            "status": "queued",
            "progress": 0,
            "message": "En cola...",
            "filename": None,
            "file_size": "",
            "speed": "",
            "eta": "",
            "title": title,
            "type": download_type,
            "url": url,
            "queue_id": queue_id,
        }

        queue_jobs.append({
            "job_id": job_id,
            "url": url,
            "type": download_type,
            "quality": quality,
            "title": title,
        })

    if not queue_jobs:
        return jsonify({"error": "No hay enlaces válidos"}), 400

    socketio.start_background_task(process_queue, queue_id, queue_jobs)

    return jsonify({
        "queue_id": queue_id,
        "jobs": queue_jobs
    })


@app.route("/download/<job_id>")
def download_file(job_id):
    if not session.get("authenticated"):
        return redirect("/")

    job = jobs.get(job_id)

    if not job or not job.get("filename"):
        return "Archivo no encontrado", 404

    return send_from_directory(
        DOWNLOAD_DIR,
        job["filename"],
        as_attachment=True
    )


# ==========================================================
# ROUTES: HISTORY + STATUS
# ==========================================================

@app.route("/history")
def history():
    if not session.get("authenticated"):
        return jsonify({"error": "No autorizado"}), 401

    return jsonify(load_history())


@app.route("/clear-history", methods=["POST"])
def clear_history():
    if not session.get("authenticated"):
        return jsonify({"error": "No autorizado"}), 401

    save_history([])
    return jsonify({"success": True})


@app.route("/clear-downloads", methods=["POST"])
def clear_downloads():
    if not session.get("authenticated"):
        return jsonify({"error": "No autorizado"}), 401

    for filename in os.listdir(DOWNLOAD_DIR):
        path = os.path.join(DOWNLOAD_DIR, filename)

        if os.path.isfile(path):
            os.remove(path)

    return jsonify({"success": True})


@app.route("/server-status")
def server_status():
    if not session.get("authenticated"):
        return jsonify({"error": "No autorizado"}), 401

    return jsonify({
        "yt_dlp": check_command(["yt-dlp", "--version"]),
        "ffmpeg": check_command(["ffmpeg", "-version"]),
        "downloads_folder": os.path.exists(DOWNLOAD_DIR),
        "downloads_count": len([
            f for f in os.listdir(DOWNLOAD_DIR)
            if os.path.isfile(os.path.join(DOWNLOAD_DIR, f))
        ]),
    })


# ==========================================================
# BACKGROUND TASKS
# ==========================================================

def process_queue(queue_id, queue_jobs):
    total = len(queue_jobs)

    for index, item in enumerate(queue_jobs, start=1):
        job_id = item["job_id"]

        emit_progress(job_id, {
            "status": "starting",
            "progress": 0,
            "message": f"Descarga {index} de {total} iniciando...",
        })

        download_task(
            job_id,
            item["url"],
            item["type"],
            item["quality"],
            item.get("title", "")
        )

        socketio.sleep(0.5)

    socketio.emit("queue_done", {
        "queue_id": queue_id,
        "message": "Cola finalizada"
    })


def download_task(job_id, url, download_type, quality, title=""):
    try:
        before_files = set(os.listdir(DOWNLOAD_DIR))

        ydl_opts = build_ydl_options(job_id, download_type, quality)

        emit_progress(job_id, {
            "status": "starting",
            "progress": 0,
            "message": "Iniciando descarga...",
        })

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        filename = get_newest_file(before_files)

        if not filename:
            raise Exception("No se generó ningún archivo.")

        file_size = get_file_size(filename)

        jobs[job_id]["filename"] = filename
        jobs[job_id]["file_size"] = file_size

        add_history({
            "title": title or filename,
            "url": url,
            "type": download_type,
            "quality": quality,
            "filename": filename,
            "size": file_size,
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        })

        emit_progress(job_id, {
            "status": "done",
            "progress": 100,
            "message": "Descarga lista",
            "filename": filename,
            "file_size": file_size,
        })

    except Exception as e:
        emit_progress(job_id, {
            "status": "error",
            "progress": 0,
            "message": f"ERROR: {clean_error(e)}",
        })


# ==========================================================
# APP START
# ==========================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))

    print("")
    print("Servidor iniciado correctamente")
    print(f"Abre en tu Mac: http://127.0.0.1:{port}")
    print(f"Para celular usa: http://IP-DE-TU-MAC:{port}")
    print(f"PIN: {APP_PIN}")
    print("")

    socketio.run(
        app,
        host="0.0.0.0",
        port=port
    )