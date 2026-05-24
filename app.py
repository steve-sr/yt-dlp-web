import os
import uuid
import threading
from flask import Flask, render_template, request, jsonify, send_from_directory
import yt_dlp

app = Flask(__name__)

DOWNLOAD_DIR = os.path.join(os.getcwd(), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

jobs = {}


def progress_hook(job_id):
    def hook(d):
        if d["status"] == "downloading":
            percent = d.get("_percent_str", "0%").replace("%", "").strip()
            speed = d.get("_speed_str", "")
            eta = d.get("_eta_str", "")

            try:
                percent = float(percent)
            except:
                percent = 0

            jobs[job_id]["progress"] = percent
            jobs[job_id]["status"] = "downloading"
            jobs[job_id]["message"] = f"Descargando... {percent:.1f}%"
            jobs[job_id]["speed"] = speed
            jobs[job_id]["eta"] = eta

        elif d["status"] == "finished":
            jobs[job_id]["progress"] = 100
            jobs[job_id]["status"] = "processing"
            jobs[job_id]["message"] = "Procesando archivo..."

    return hook


def download_task(job_id, url, download_type, quality):
    try:
        folder = DOWNLOAD_DIR

        ydl_opts = {
            "outtmpl": os.path.join(folder, "%(title)s.%(ext)s"),
            "progress_hooks": [progress_hook(job_id)],
            "noplaylist": download_type != "playlist",
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

        before_files = set(os.listdir(folder))

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        after_files = set(os.listdir(folder))
        new_files = list(after_files - before_files)

        if new_files:
            filename = new_files[0]
        else:
            files = sorted(
                os.listdir(folder),
                key=lambda f: os.path.getmtime(os.path.join(folder, f)),
                reverse=True
            )
            filename = files[0] if files else None

        jobs[job_id]["status"] = "done"
        jobs[job_id]["progress"] = 100
        jobs[job_id]["message"] = "Descarga lista"
        jobs[job_id]["filename"] = filename

    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["message"] = str(e)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/start", methods=["POST"])
def start_download():
    data = request.json

    url = data.get("url")
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
        "eta": ""
    }

    thread = threading.Thread(
        target=download_task,
        args=(job_id, url, download_type, quality),
        daemon=True
    )
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/progress/<job_id>")
def progress(job_id):
    job = jobs.get(job_id)

    if not job:
        return jsonify({"error": "Trabajo no encontrado"}), 404

    return jsonify(job)


@app.route("/download/<filename>")
def download_file(filename):
    return send_from_directory(DOWNLOAD_DIR, filename, as_attachment=True)


if __name__ == "__main__":
    app.run(debug=True, port=5000)