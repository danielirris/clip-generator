// Frontend mínimo: subida, barra de progreso por polling y descarga.
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);

  const fileInput = $("file");
  const dropzone = $("dropzone");
  const filenameEl = $("filename");
  const submitBtn = $("submit-btn");
  const form = $("upload-form");

  const uploadCard = $("upload-card");
  const progressCard = $("progress-card");
  const resultCard = $("result-card");
  const errorCard = $("error-card");

  const statusLabel = $("status-label");
  const progressFill = $("progress-fill");
  const progressMsg = $("progress-msg");
  const avisoEl = $("aviso");

  const preview = $("preview");
  const downloadLink = $("download-link");

  let pollTimer = null;

  const STATUS_TEXT = {
    queued: "En cola…",
    extracting: "Extrayendo audio…",
    transcribing: "Transcribiendo (Groq)…",
    analyzing: "Analizando momentos (Gemini)…",
    rendering: "Renderizando clip vertical…",
    done: "¡Listo!",
    error: "Error",
  };

  function show(card) {
    [uploadCard, progressCard, resultCard, errorCard].forEach((c) =>
      c.classList.add("hidden")
    );
    card.classList.remove("hidden");
  }

  function pickFile(file) {
    if (!file) return;
    fileInput.files = createFileList(file);
    filenameEl.textContent = file.name;
    submitBtn.disabled = false;
  }

  // Helper para asignar un File arrastrado al input.
  function createFileList(file) {
    const dt = new DataTransfer();
    dt.items.add(file);
    return dt.files;
  }

  fileInput.addEventListener("change", () => {
    const f = fileInput.files[0];
    filenameEl.textContent = f ? f.name : "";
    submitBtn.disabled = !f;
  });

  ["dragover", "dragenter"].forEach((ev) =>
    dropzone.addEventListener(ev, (e) => {
      e.preventDefault();
      dropzone.classList.add("drag");
    })
  );
  ["dragleave", "drop"].forEach((ev) =>
    dropzone.addEventListener(ev, (e) => {
      e.preventDefault();
      dropzone.classList.remove("drag");
    })
  );
  dropzone.addEventListener("drop", (e) => {
    const f = e.dataTransfer.files[0];
    if (f) pickFile(f);
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const file = fileInput.files[0];
    if (!file) return;

    const data = new FormData();
    data.append("file", file);

    show(progressCard);
    setProgress("queued", 2, "Subiendo video…");

    try {
      const res = await fetch("/api/jobs", { method: "POST", body: data });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Error ${res.status}`);
      }
      const { job_id } = await res.json();
      poll(job_id);
    } catch (err) {
      showError(err.message);
    }
  });

  function setProgress(status, pct, msg) {
    statusLabel.textContent = STATUS_TEXT[status] || "Procesando…";
    progressFill.style.width = `${pct}%`;
    progressMsg.textContent = msg || "";
  }

  function poll(jobId) {
    clearInterval(pollTimer);
    pollTimer = setInterval(async () => {
      try {
        const res = await fetch(`/api/jobs/${jobId}`);
        if (!res.ok) throw new Error(`Error ${res.status}`);
        const job = await res.json();
        setProgress(job.status, job.progress, job.message);

        if (job.status === "done") {
          clearInterval(pollTimer);
          finish(jobId, job.aviso);
        } else if (job.status === "error") {
          clearInterval(pollTimer);
          showError(job.error || "Error en el procesamiento");
        }
      } catch (err) {
        clearInterval(pollTimer);
        showError(err.message);
      }
    }, 2000);
  }

  function finish(jobId, aviso) {
    const url = `/api/jobs/${jobId}/download`;
    preview.src = url;
    downloadLink.href = url;
    if (aviso) {
      avisoEl.textContent = aviso;
      avisoEl.classList.remove("hidden");
    }
    show(resultCard);
  }

  function showError(msg) {
    $("error-msg").textContent = msg || "Error desconocido";
    show(errorCard);
  }

  $("new-btn").addEventListener("click", reset);
  $("retry-btn").addEventListener("click", reset);

  function reset() {
    clearInterval(pollTimer);
    form.reset();
    filenameEl.textContent = "";
    submitBtn.disabled = true;
    avisoEl.classList.add("hidden");
    preview.removeAttribute("src");
    show(uploadCard);
  }
})();
