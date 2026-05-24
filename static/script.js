const socket = io();

let selectedType = "video";
let currentJob = null;

const $ = (id) => document.getElementById(id);

document.querySelectorAll(".type").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".type").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    selectedType = btn.dataset.type;
  });
});

async function pasteUrl() {
  try {
    const text = await navigator.clipboard.readText();
    $("url").value = text;
  } catch {
    alert("No se pudo leer el portapapeles.");
  }
}

async function loadInfo() {
  const url = $("url").value.trim();

  if (!url) {
    alert("Pega una URL.");
    return;
  }

  $("preview").classList.add("hidden");

  const res = await fetch("/info", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ url }),
  });

  const data = await res.json();

  if (data.error) {
    alert(data.error);
    return;
  }

  $("thumbnail").src = data.thumbnail || "";
  $("videoTitle").textContent = data.title || "Sin título";
  $("uploader").textContent = data.uploader || "Desconocido";
  $("duration").textContent = data.duration || "Desconocido";

  $("preview").classList.remove("hidden");

  lucide.createIcons();
}

async function startDownload() {
  const url = $("url").value.trim();
  const quality = $("quality").value;

  if (!url) {
    alert("Pega una URL.");
    return;
  }

  currentJob = null;

  $("downloadLink").classList.add("hidden");
  $("progressBox").classList.remove("hidden");

  setProgress(0, "Preparando descarga...", "", "");

  const btn = $("downloadBtn");
  btn.disabled = true;
  btn.innerHTML = `<i data-lucide="loader-circle"></i> Descargando...`;
  lucide.createIcons();

  const res = await fetch("/start", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      url,
      type: selectedType,
      quality,
    }),
  });

  const data = await res.json();

  if (data.error) {
    alert(data.error);
    resetButton();
    return;
  }

  currentJob = data.job_id;
}

socket.on("progress", (data) => {
  if (!currentJob || data.job_id !== currentJob) return;

  setProgress(
    data.progress || 0,
    data.message || "Procesando...",
    data.speed || "",
    data.eta || ""
  );

  if (data.status === "done") {
    showDownload();
    resetButton();
  }

  if (data.status === "error") {
    alert(data.message || "Error durante la descarga.");
    resetButton();
  }
});

function setProgress(percent, message, speed, eta) {
  const safePercent = Math.max(0, Math.min(100, Number(percent) || 0));

  $("progressFill").style.width = `${safePercent}%`;
  $("progressText").textContent = `${safePercent.toFixed(1)}%`;
  $("statusText").textContent = message;

  $("speedText").textContent = speed ? `Velocidad: ${speed}` : "Velocidad: --";
  $("etaText").textContent = eta ? `ETA: ${eta}` : "ETA: --";

  const circumference = 326;
  const offset = circumference - (safePercent / 100) * circumference;

  $("ringProgress").style.strokeDashoffset = offset;
}

function showDownload() {
  const link = $("downloadLink");

  link.href = `/download/${currentJob}`;
  link.classList.remove("hidden");
}

function resetButton() {
  const btn = $("downloadBtn");

  btn.disabled = false;
  btn.innerHTML = `<i data-lucide="download"></i> Iniciar descarga`;

  lucide.createIcons();
}

lucide.createIcons();