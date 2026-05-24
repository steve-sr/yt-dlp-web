import eventlet
eventlet.monkey_patch()

import os
import uuid
import yt_dlp
import re
from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_socketio import SocketIO


app = Flask(__name__)
app.config["SECRET_KEY"] = "yt-dlp-web-secret"

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


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/info", methods=["POST"])
def get_video_info():
    data = request.json
    url = data.get("url", "").strip()

    if not url:
        return jsonify({"error": "URL requerida"}), 400

    try:
        opts = {
            "quiet": True,
            "skip_download": True,
            "noplaylist": True,
        }

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
        return jsonify({"error": str(e)}), 500


@app.route("/start", methods=["POST"])
def start_download():
    data = request.json

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

def clean_text(value):
    if not value:
        return ""

    value = str(value)
    value = re.sub(r"\x1b\[[0-9;]*m", "", value)

    return value.strip()

def emit_progress(job_id, payload):
    jobs[job_id].update(payload)
    socketio.emit("progress", {
        "job_id": job_id,
        **jobs[job_id]
    })


def progress_hook(job_id):
    def hook(d):
        status = d.get("status")

        if status == "downloading":
            downloaded = d.get("downloaded_bytes") or 0
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0

            percent = 0

            if total > 0:
                percent = (downloaded / total) * 100
            else:
                raw_percent = clean_text(d.get("_percent_str", "0"))
                raw_percent = raw_percent.replace("%", "")

                try:
                    percent = float(raw_percent)
                except:
                    percent = 0

            percent = max(0, min(100, percent))

            speed = clean_text(d.get("_speed_str", ""))
            eta = clean_text(d.get("_eta_str", ""))

            emit_progress(job_id, {
                "status": "downloading",
                "progress": percent,
                "message": f"Descargando... {percent:.1f}%",
                "speed": speed,
                "eta": eta,
            })

        elif status == "finished":
            emit_progress(job_id, {
                "status": "processing",
                "progress": 100,
                "message": "Procesando archivo...",
            })

    return hook

def download_task(job_id, url, download_type, quality):
    try:
        before_files = set(os.listdir(DOWNLOAD_DIR))

        ydl_opts = {
            "outtmpl": os.path.join(DOWNLOAD_DIR, "%(title).160s.%(ext)s"),
            "progress_hooks": [progress_hook(job_id)],
            "noplaylist": download_type != "playlist",
            "quiet": True,
            "no_warnings": True,
            "noprogress": False,
            "nopart": False,
        }

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
                fmt = "bv*[height<=1080]+ba/b[height<=1080]"
            elif quality == "720p":
                fmt = "bv*[height<=720]+ba/b[height<=720]"
            elif quality == "480p":
                fmt = "bv*[height<=480]+ba/b[height<=480]"
            else:
                fmt = "bv*+ba/b"

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

        after_files = set(os.listdir(DOWNLOAD_DIR))
        new_files = list(after_files - before_files)

        if new_files:
            filename = sorted(
                new_files,
                key=lambda f: os.path.getmtime(os.path.join(DOWNLOAD_DIR, f)),
                reverse=True
            )[0]
        else:
            filename = sorted(
                os.listdir(DOWNLOAD_DIR),
                key=lambda f: os.path.getmtime(os.path.join(DOWNLOAD_DIR, f)),
                reverse=True
            )[0]

        emit_progress(job_id, {
            "status": "done",
            "progress": 100,
            "message": "Descarga lista",
            "filename": filename,
        })

    except Exception as e:
        emit_progress(job_id, {
            "status": "error",
            "message": str(e),
        })


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=10000, debug=True)