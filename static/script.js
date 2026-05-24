const socket = io();

let selectedType = "video";
let currentJob = null;

const $ = (id) => document.getElementById(id);

function showModal(type, title, message) {
  const overlay = $("modalOverlay");
  const iconBox = $("modalIcon");
  const titleBox = $("modalTitle");
  const messageBox = $("modalMessage");

  let icon = "info";

  if (type === "success") icon = "check-circle";
  if (type === "error") icon = "circle-x";
  if (type === "warning") icon = "triangle-alert";

  iconBox.className = `modal-icon ${type}`;
  iconBox.innerHTML = `<i data-lucide="${icon}"></i>`;

  titleBox.textContent = title;
  messageBox.textContent = message;

  overlay.classList.remove("hidden");
  lucide.createIcons();
}

function closeModal() {
  $("modalOverlay").classList.add("hidden");
}

function isValidUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

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

    if (!text) {
      showModal("warning", "Portapapeles vacío", "No hay ningún enlace copiado.");
      return;
    }

    $("url").value = text;
  } catch {
    showModal(
      "error",
      "Portapapeles bloqueado",
      "No se pudo leer el portapapeles. Pega la URL manualmente."
    );
  }
}

async function loadInfo() {
  const url = $("url").value.trim();

  if (!url) {
    showModal("warning", "Falta la URL", "Pega una URL antes de obtener la información.");
    return;
  }

  if (!isValidUrl(url)) {
    showModal("warning", "URL inválida", "Revisa que el enlace empiece con http:// o https://.");
    return;
  }

  $("preview").classList.add("hidden");

  try {
    const res = await fetch("/info", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ url }),
    });

    const data = await res.json();

    if (data.error) {
      showModal("error", "No se pudo obtener la información", data.error);
      return;
    }

    $("thumbnail").src = data.thumbnail || "";
    $("videoTitle").textContent = data.title || "Sin título";
    $("uploader").textContent = data.uploader || "Desconocido";
    $("duration").textContent = data.duration || "Desconocido";

    $("preview").classList.remove("hidden");
    lucide.createIcons();

  } catch {
    showModal(
      "error",
      "Error de conexión",
      "No se pudo conectar con el servidor. Intenta de nuevo."
    );
  }
}

async function startDownload() {
  const url = $("url").value.trim();
  const quality = $("quality").value;

  if (!url) {
    showModal("warning", "Falta la URL", "Pega una URL antes de iniciar la descarga.");
    return;
  }

  if (!isValidUrl(url)) {
    showModal("warning", "URL inválida", "Revisa que el enlace empiece con http:// o https://.");
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

  try {
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
      showModal("error", "No se pudo iniciar", data.error);
      resetButton();
      return;
    }

    currentJob = data.job_id;

  } catch {
    showModal(
      "error",
      "Error de conexión",
      "No se pudo iniciar la descarga. Revisa tu conexión."
    );
    resetButton();
  }
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
    showModal("success", "Descarga lista", "Tu archivo ya está listo para descargar.");
  }

  if (data.status === "error") {
    showModal("error", "Error durante la descarga", data.message || "Ocurrió un error inesperado.");
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