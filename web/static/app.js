// Frontend mínimo: subida múltiple, barra de progreso por polling y descarga.
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

  const clipsGrid = $("clips-grid");
  const downloadAll = $("download-all");

  let pollTimer = null;

  const STATUS_TEXT = {
    queued: "En cola…",
    extracting: "Extrayendo audio…",
    transcribing: "Transcribiendo (OpenAI)…",
    analyzing: "Detectando ganchos…",
    rendering: "Renderizando los clips…",
    done: "¡Listo!",
    error: "Error",
  };

  function show(card) {
    [uploadCard, progressCard, resultCard, errorCard].forEach((c) =>
      c.classList.add("hidden")
    );
    card.classList.remove("hidden");
  }

  function describeSelection(files) {
    if (!files || !files.length) return "";
    if (files.length === 1) return files[0].name;
    return `${files.length} videos seleccionados`;
  }

  fileInput.addEventListener("change", () => {
    filenameEl.textContent = describeSelection(fileInput.files);
    submitBtn.disabled = !fileInput.files.length;
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
    if (e.dataTransfer.files.length) {
      fileInput.files = e.dataTransfer.files;
      filenameEl.textContent = describeSelection(fileInput.files);
      submitBtn.disabled = false;
    }
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const files = fileInput.files;
    if (!files.length) return;

    const data = new FormData();
    for (const f of files) data.append("files", f);
    const music = $("music").files[0];
    if (music) data.append("music", music);

    show(progressCard);
    setProgress("queued", 2, "Subiendo videos…");

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

  // Tolera cortes de red/luz: no se rinde al primer fallo. Mientras tanto, el
  // trabajo sigue en el servidor (persistido en SQLite) y se reanuda al volver.
  const MAX_POLL_FAILS = 90; // ~3 min de cortes tolerados (intervalo 2s)
  let pollFails = 0;

  function poll(jobId) {
    clearInterval(pollTimer);
    localStorage.setItem("clipgen_job", jobId); // para reanudar tras recargar
    pollFails = 0;
    pollTimer = setInterval(async () => {
      try {
        const res = await fetch(`/api/jobs/${jobId}`, { cache: "no-store" });
        if (res.status === 404) {
          // El servidor responde pero no conoce el trabajo: no insistir.
          clearInterval(pollTimer);
          localStorage.removeItem("clipgen_job");
          showError("No se encontró el trabajo. Vuelve a empezar.");
          return;
        }
        if (!res.ok) throw new Error(`Error ${res.status}`);
        const job = await res.json();
        pollFails = 0;
        setProgress(job.status, job.progress, job.message);

        if (job.status === "done") {
          clearInterval(pollTimer);
          localStorage.removeItem("clipgen_job");
          finish(jobId, job);
        } else if (job.status === "error") {
          clearInterval(pollTimer);
          localStorage.removeItem("clipgen_job");
          showError(job.error || "Error en el procesamiento");
        }
      } catch (err) {
        // Fallo de red (corte de luz/internet): reintentar sin rendirse.
        pollFails++;
        if (pollFails >= MAX_POLL_FAILS) {
          clearInterval(pollTimer);
          showError(
            "Se perdió la conexión y no volvió. Tu trabajo sigue en el servidor: " +
            "recarga esta página para reanudarlo."
          );
        } else {
          statusLabel.textContent = "Reconectando…";
          progressMsg.textContent =
            `Conexión interrumpida, reintentando… (${pollFails})`;
        }
      }
    }, 2000);
  }

  function finish(jobId, job) {
    clipsGrid.innerHTML = "";
    (job.clips || []).forEach((url, i) => {
      const cell = document.createElement("div");
      cell.className = "clip-cell";
      const v = document.createElement("video");
      v.src = url;
      v.controls = true;
      v.playsInline = true;
      const a = document.createElement("a");
      a.href = url;
      a.className = "clip-dl";
      a.textContent = `⬇️ Clip ${i + 1}`;
      cell.append(v, a);
      clipsGrid.append(cell);
    });
    $("result-title").textContent = `✅ ${job.clips.length} clips listos`;
    downloadAll.href = `/api/jobs/${jobId}/download`;
    if (job.aviso) {
      avisoEl.textContent = job.aviso;
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
    localStorage.removeItem("clipgen_job");
    form.reset();
    filenameEl.textContent = "";
    submitBtn.disabled = true;
    avisoEl.classList.add("hidden");
    clipsGrid.innerHTML = "";
    show(uploadCard);
  }

  // Al cargar la página: si había un trabajo en curso (p.ej. se cortó la luz),
  // reanuda el seguimiento automáticamente.
  const pending = localStorage.getItem("clipgen_job");
  if (pending) {
    show(progressCard);
    setProgress("queued", 2, "Reanudando trabajo anterior…");
    poll(pending);
  }
})();
