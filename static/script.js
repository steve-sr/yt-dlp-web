const socket = io();

let selectedType = null;
let currentJob = null;
let currentVideoTitle = "";
let currentInfo = null;
let debounceTimer = null;

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

function setAutoStatus(type, text) {
  const status = $("autoInfoStatus");

  status.className = "auto-info-status";

  if (type) {
    status.classList.add(type);
  }

  status.textContent = text;
}

function resetFlow() {
  currentInfo = null;
  currentVideoTitle = "";
  selectedType = null;

  $("preview").classList.add("hidden");
  $("progressBox").classList.add("hidden");
  $("readyCard")?.classList.add("hidden");

  disableTypeButtons();
  resetQualityOptions();
  disableDownload();

  setAutoStatus("", "Esperando enlace...");
}

function disableTypeButtons() {
  document.querySelectorAll(".type").forEach((btn) => {
    btn.disabled = true;
    btn.classList.remove("active");
  });
}

function enableAllowedTypes(allowedTypes, defaultType) {
  document.querySelectorAll(".type").forEach((btn) => {
    const type = btn.dataset.type;

    if (allowedTypes.includes(type)) {
      btn.disabled = false;
    } else {
      btn.disabled = true;
    }

    btn.classList.remove("active");
  });

  const defaultButton = document.querySelector(`.type[data-type="${defaultType}"]`);

  if (defaultButton && !defaultButton.disabled) {
    defaultButton.classList.add("active");
    selectedType = defaultType;
  } else {
    const firstAllowed = document.querySelector(`.type:not(:disabled)`);
    if (firstAllowed) {
      firstAllowed.classList.add("active");
      selectedType = firstAllowed.dataset.type;
    }
  }

  updateQualityMode();
  enableDownload();
}

function resetQualityOptions() {
  const quality = $("quality");

  quality.disabled = true;
  quality.innerHTML = `<option value="">Primero pega un enlace</option>`;
}

function updateQualityOptions(qualities) {
  const qualitySelect = $("quality");

  qualitySelect.innerHTML = `
    <option value="best">Máxima calidad disponible</option>
  `;

  if (!qualities || !qualities.length) {
    const option = document.createElement("option");
    option.value = "best";
    option.textContent = "Automática";
    qualitySelect.appendChild(option);
    return;
  }

  qualities.forEach((quality) => {
    const option = document.createElement("option");
    option.value = quality.value;
    option.textContent = quality.label;
    qualitySelect.appendChild(option);
  });
}

function updateAudioQualityOptions() {
  const qualitySelect = $("quality");

  qualitySelect.innerHTML = `
    <option value="320">MP3 320 kbps</option>
    <option value="192">MP3 192 kbps</option>
    <option value="128">MP3 128 kbps</option>
  `;
}

function updateReelsQualityOptions() {
  const qualitySelect = $("quality");

  qualitySelect.innerHTML = `
    <option value="best">Calidad automática</option>
  `;
}

function updatePreviewThumbnail(data) {
  const thumbnail = $("thumbnail");
  const fallback = $("platformFallback");
  const icon = $("platformIcon");
  const label = $("platformLabel");

  function showFallback() {
    thumbnail.src = "";
    thumbnail.classList.add("hidden");

    icon.setAttribute("data-lucide", data.platform_icon || "video");
    label.textContent = data.platform_label || "Video";

    fallback.className = `platform-fallback ${data.platform || "generic"}`;
    fallback.classList.remove("hidden");

    lucide.createIcons();
  }

  if (data.thumbnail) {
    thumbnail.onload = () => {
      fallback.classList.add("hidden");
      thumbnail.classList.remove("hidden");
    };

    thumbnail.onerror = () => {
      showFallback();
    };

    fallback.classList.add("hidden");
    thumbnail.classList.remove("hidden");
    thumbnail.src = data.thumbnail;

    return;
  }

  showFallback();
}

function updateQualityMode() {
  const qualitySelect = $("quality");

  if (!currentInfo || !selectedType) {
    resetQualityOptions();
    return;
  }

  qualitySelect.disabled = false;

  if (selectedType === "mp3") {
    updateAudioQualityOptions();
    return;
  }

  if (selectedType === "reels") {
    updateReelsQualityOptions();
    return;
  }

  if (selectedType === "playlist") {
    updateQualityOptions(currentInfo.qualities);
    return;
  }

  if (selectedType === "video") {
    updateQualityOptions(currentInfo.qualities);
    return;
  }
}

function enableDownload() {
  const btn = $("downloadBtn");
  btn.disabled = !currentInfo || !selectedType;
}

function disableDownload() {
  $("downloadBtn").disabled = true;
}

document.querySelectorAll(".type").forEach((btn) => {
  btn.addEventListener("click", () => {
    if (btn.disabled) return;

    document.querySelectorAll(".type").forEach((b) => b.classList.remove("active"));

    btn.classList.add("active");
    selectedType = btn.dataset.type;

    updateQualityMode();
    enableDownload();
  });
});

$("url").addEventListener("input", () => {
  const url = $("url").value.trim();

  clearTimeout(debounceTimer);

  if (!url) {
    resetFlow();
    return;
  }

  if (!isValidUrl(url)) {
    resetFlow();
    setAutoStatus("error", "URL inválida. Debe iniciar con http:// o https://");
    return;
  }

  setAutoStatus("loading", "Detectando información...");

  debounceTimer = setTimeout(() => {
    loadInfoAutomatically(url);
  }, 800);
});

async function loadInfoAutomatically(url) {
  try {
    disableDownload();
    disableTypeButtons();
    resetQualityOptions();

    const res = await fetch("/info", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ url }),
    });

    const data = await res.json();

    if (data.error) {
      resetFlow();

      if (data.error.includes("429") || data.error.includes("Too Many Requests")) {
        setAutoStatus("error", "La plataforma limitó las solicitudes. Intenta de nuevo más tarde.");
        showModal(
          "warning",
          "Demasiadas solicitudes",
          "TikTok o Instagram limitó temporalmente las solicitudes. Espera unos minutos o prueba con otro enlace."
        );
        return;
      }

      setAutoStatus("error", "No se pudo leer el enlace.");
      showModal("error", "No se pudo obtener la información", data.error);
      return;
    }

    currentInfo = data;
    currentVideoTitle = data.title || "";

    updatePreviewThumbnail(data);

    $("videoTitle").textContent = data.title || "Sin título";
    $("uploader").textContent = data.uploader || "Desconocido";
    $("duration").textContent = data.duration || "Desconocido";

    $("preview").classList.remove("hidden");

    enableAllowedTypes(
      data.allowed_types || ["video", "mp3"],
      data.default_type || "video"
    );

    setAutoStatus(
      "success",
      data.label || "Información detectada correctamente."
    );

    lucide.createIcons();

  } catch {
    resetFlow();
    setAutoStatus("error", "Error de conexión.");
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

  if (!currentInfo) {
    showModal("warning", "Espera la detección", "Primero espera a que la app detecte el tipo de enlace.");
    return;
  }

  if (!selectedType) {
    showModal("warning", "Selecciona un tipo", "Selecciona una opción disponible para este enlace.");
    return;
  }

  currentJob = null;

  $("readyCard")?.classList.add("hidden");
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
        title: currentVideoTitle,
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
    showDownload(data);
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

function showDownload(data = {}) {
  const link = $("downloadLink");
  const ready = $("readyCard");
  const info = $("readyFileInfo");

  link.href = `/download/${currentJob}`;
  ready.classList.remove("hidden");

  info.textContent = data.file_size
    ? `Tu archivo está listo. Tamaño aproximado: ${data.file_size}.`
    : "Tu archivo está listo. Puedes descargarlo o iniciar una nueva descarga.";
}

function resetButton() {
  const btn = $("downloadBtn");

  btn.disabled = false;
  btn.innerHTML = `<i data-lucide="download"></i> Iniciar descarga`;

  enableDownload();
  lucide.createIcons();
}

async function loadStatus() {
  const panel = $("statusPanel");
  panel.classList.toggle("hidden");

  if (panel.classList.contains("hidden")) return;

  try {
    const res = await fetch("/server-status");
    const data = await res.json();

    $("statusYtdlp").textContent = data.yt_dlp ? "OK" : "Error";
    $("statusYtdlp").className = data.yt_dlp ? "status-ok" : "status-bad";

    $("statusFfmpeg").textContent = data.ffmpeg ? "OK" : "Error";
    $("statusFfmpeg").className = data.ffmpeg ? "status-ok" : "status-bad";

    $("statusFolder").textContent = data.downloads_folder ? "OK" : "Error";
    $("statusFolder").className = data.downloads_folder ? "status-ok" : "status-bad";

    $("statusFiles").textContent = data.downloads_count ?? 0;

  } catch {
    showModal("error", "Error", "No se pudo revisar el estado del servidor.");
  }
}

async function loadHistory() {
  const panel = $("historyPanel");
  panel.classList.toggle("hidden");

  if (panel.classList.contains("hidden")) return;

  try {
    const res = await fetch("/history");
    const history = await res.json();

    const list = $("historyList");
    list.innerHTML = "";

    if (!history.length) {
      list.innerHTML = `<p style="color:#94a3b8;">No hay descargas recientes.</p>`;
      return;
    }

    history.forEach((item) => {
      const div = document.createElement("div");
      div.className = "history-item";

      div.innerHTML = `
        <strong>${item.title || "Sin título"}</strong>
        <div class="history-meta">
          Tipo: ${item.type} · Calidad: ${item.quality}<br>
          Tamaño: ${item.size || "Desconocido"}<br>
          Fecha: ${item.date}<br>
          <button class="preview-btn" style="margin-top:10px;" onclick="repeatDownload('${encodeURIComponent(item.url)}')">
            Repetir descarga
          </button>
        </div>
      `;

      list.appendChild(div);
    });

  } catch {
    showModal("error", "Error", "No se pudo cargar el historial.");
  }
}

function repeatDownload(encodedUrl) {
  $("url").value = decodeURIComponent(encodedUrl);

  const event = new Event("input");
  $("url").dispatchEvent(event);

  showModal("success", "URL cargada", "El enlace se colocó en el campo de URL.");
}

async function clearHistory() {
  const res = await fetch("/clear-history", {
    method: "POST"
  });

  if (res.ok) {
    showModal("success", "Historial limpio", "Se eliminó el historial.");
    loadHistory();
  }
}

async function clearDownloads() {
  const res = await fetch("/clear-downloads", {
    method: "POST"
  });

  if (res.ok) {
    showModal("success", "Descargas eliminadas", "La carpeta de descargas quedó limpia.");
  } else {
    showModal("error", "Error", "No se pudieron eliminar las descargas.");
  }
}

function newDownload() {
  $("url").value = "";
  resetFlow();
}

resetFlow();
lucide.createIcons();