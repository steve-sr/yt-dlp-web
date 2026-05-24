import eventlet
eventlet.monkey_patch()

import os
import re
import uuid
import yt_dlp
from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_socketio import SocketIO

app = Flask(__name__)
app.config["SECRET_KEY"] = "yt-dlp-local-secret"

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="eventlet"
)

DOWNLOAD_DIR = os.path.join(os.getcwd(), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

jobs = {}


def seconds_to_time(seconds):
    if not seconds:
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
        return "El formato solicitado no está disponible. Prueba con otra calidad o con MP3."

    if "Sign in to confirm" in msg or "not a bot" in msg:
        return "YouTube está pidiendo verificación. Prueba otro video o actualiza yt-dlp."

    return msg


def emit_progress(job_id, payload):
    jobs[job_id].update(payload)

    socketio.emit("progress", {
        "job_id": job_id,
        **jobs[job_id]
    })

    socketio.sleep(0)


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


def get_newest_file(before_files):
    after_files = set(os.listdir(DOWNLOAD_DIR))
    new_files = list(after_files - before_files)

    candidates = new_files

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


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/info", methods=["POST"])
def get_video_info():
    data = request.json or {}
    url = data.get("url", "").strip()

    if not url:
        return jsonify({"error": "URL requerida"}), 400

    try:
        opts = base_ydl_opts()
        opts.update({
            "skip_download": True,
            "noplaylist": True,
        })

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

        return jsonify({
            "title": info.get("title", "Sin título"),
            "thumbnail": info.get("thumbnail"),
            "uploader": info.get("uploader", "Desconocido"),
            "duration": seconds_to_time(info.get("duration")),
            "webpage_url": info.get("webpage_url", url),
        })

    except Exception as e:
        return jsonify({"error": clean_error(e)}), 500


@app.route("/start", methods=["POST"])
def start_download():
    data = request.json or {}

    url = data.get("url", "").strip()
    download_type = data.get("type", "video")
    quality = data.get("quality", "best")

    if not url:
        return jsonify({"error": "URL requerida"}), 400

    job_id = str(uuid.uuid4())

    jobs[job_id] = {
        "status": "starting",
        "progress": 0,
        "message": "Preparando descarga...",
        "filename": None,
        "speed": "",
        "eta": "",
    }

    socketio.start_background_task(
        download_task,
        job_id,
        url,
        download_type,
        quality
    )

    return jsonify({"job_id": job_id})


@app.route("/download/<job_id>")
def download_file(job_id):
    job = jobs.get(job_id)

    if not job or not job.get("filename"):
        return "Archivo no encontrado", 404

    return send_from_directory(
        DOWNLOAD_DIR,
        job["filename"],
        as_attachment=True
    )


def download_task(job_id, url, download_type, quality):
    try:
        before_files = set(os.listdir(DOWNLOAD_DIR))

        ydl_opts = base_ydl_opts()
        ydl_opts.update({
            "outtmpl": os.path.join(DOWNLOAD_DIR, "%(title).160s.%(ext)s"),
            "progress_hooks": [progress_hook(job_id)],
            "noplaylist": download_type != "playlist",
            "ignoreerrors": False,
        })

        if download_type == "mp3":
            ydl_opts.update({
                "format": "bestaudio/best",
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "320",
                }],
            })

        else:
            if quality == "1080p":
                fmt = "bv*[height<=1080]+ba/b[height<=1080]/best[height<=1080]/best"
            elif quality == "720p":
                fmt = "bv*[height<=720]+ba/b[height<=720]/best[height<=720]/best"
            elif quality == "480p":
                fmt = "bv*[height<=480]+ba/b[height<=480]/best[height<=480]/best"
            else:
                fmt = "bv*+ba/best"

            ydl_opts.update({
                "format": fmt,
                "merge_output_format": "mp4",
            })

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

        emit_progress(job_id, {
            "status": "done",
            "progress": 100,
            "message": "Descarga lista",
            "filename": filename,
        })

    except Exception as e:
        emit_progress(job_id, {
            "status": "error",
            "progress": 0,
            "message": f"ERROR: {clean_error(e)}",
        })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))

    print("")
    print("Servidor iniciado correctamente")
    print(f"Abre en tu Mac: http://127.0.0.1:{port}")
    print(f"Para celular usa: http://IP-DE-TU-MAC:{port}")
    print("")

    socketio.run(
        app,
        host="0.0.0.0",
        port=port
    )