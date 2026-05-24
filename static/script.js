let selectedType = "video";
let currentJob = null;

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
    document.getElementById("url").value = text;
  } catch {
    alert("No se pudo leer el portapapeles.");
  }
}

async function startDownload() {
  const url = document.getElementById("url").value.trim();
  const quality = document.getElementById("quality").value;

  if (!url) {
    alert("Pega una URL.");
    return;
  }

  const btn = document.getElementById("downloadBtn");
  const link = document.getElementById("downloadLink");

  btn.disabled = true;
  btn.textContent = "Descargando...";
  link.style.display = "none";

  setProgress(0, "Preparando descarga...");

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
  pollProgress();
}

async function pollProgress() {
  if (!currentJob) return;

  const res = await fetch(`/progress/${currentJob}`);
  const data = await res.json();

  if (data.error) {
    setProgress(0, "Error");
    resetButton();
    return;
  }

  setProgress(data.progress || 0, data.message || "Procesando...");

  if (data.status === "done") {
    setProgress(100, "Descarga lista");
    showDownload(data.filename);
    resetButton();
    return;
  }

  if (data.status === "error") {
    setProgress(0, data.message || "Error");
    resetButton();
    return;
  }

  setTimeout(pollProgress, 800);
}

function setProgress(percent, text) {
  document.getElementById("progressFill").style.width = `${percent}%`;
  document.getElementById("progressText").textContent = `${percent.toFixed(1)}%`;
  document.getElementById("statusText").textContent = text;
}

function showDownload(filename) {
  const link = document.getElementById("downloadLink");

  if (!filename) return;

  link.href = `/download/${encodeURIComponent(filename)}`;
  link.style.display = "block";
}

function resetButton() {
  const btn = document.getElementById("downloadBtn");
  btn.disabled = false;
  btn.textContent = "Iniciar descarga";
}