const modeInputs = Array.from(document.querySelectorAll('input[name="modo-periodo"]'));
const periodFields = Array.from(document.querySelectorAll("[data-period-field]"));
const monthInput = document.querySelector("#mes");
const yearInput = document.querySelector("#anio");
const startDateInput = document.querySelector("#fecha-inicio");
const endDateInput = document.querySelector("#fecha-fin");
const runButton = document.querySelector("#ejecutar");
const excelLink = document.querySelector("#descargar-excel");
const statusBox = document.querySelector("#estado");
const errorBox = document.querySelector("#errores");
const resultsBody = document.querySelector("#resultados tbody");
const backgroundCanvas = document.querySelector("#flow-bg");
const hasExtractor = Boolean(
  monthInput &&
    yearInput &&
    startDateInput &&
    endDateInput &&
    runButton &&
    statusBox &&
    errorBox &&
    resultsBody &&
    excelLink,
);

if (hasExtractor) {
  const now = new Date();
  const currentMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  monthInput.value = currentMonth;
  yearInput.value = String(now.getFullYear());
  startDateInput.value = `${currentMonth}-01`;
  endDateInput.value = toDateInputValue(now);

  modeInputs.forEach((input) => {
    input.addEventListener("change", updatePeriodFields);
  });

  excelLink.addEventListener("click", (event) => {
    if (excelLink.classList.contains("is-disabled")) {
      event.preventDefault();
    }
  });

  runButton.addEventListener("click", async () => {
    const requestPayload = buildRequestPayload();
    if (!requestPayload) {
      return;
    }

    runButton.disabled = true;
    updateExcelLink("", 0);
    setStatus("Ejecutando...", "info");
    errorBox.innerHTML = "";
    renderRows([]);

    try {
      const response = await fetch("/ejecutar", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(requestPayload),
      });
      const payload = await response.json();

      if (!response.ok) {
        throw new Error(formatApiError(payload.detail) || "No se pudo ejecutar el extractor.");
      }

      setStatus(`${payload.estado} - ${payload.count} factura(s) procesada(s)`, "ok");
      renderRows(payload.resultados || []);
      updateExcelLink(payload.periodo || payload.mes || "", payload.resultados?.length || 0);
      renderErrors(payload.errores || []);
    } catch (error) {
      setStatus(error.message, "error");
    } finally {
      runButton.disabled = false;
    }
  });
}

function updateExcelLink(period, count) {
  if (!excelLink) {
    return;
  }

  if (!period || !count) {
    excelLink.href = "#";
    excelLink.classList.add("is-disabled");
    excelLink.setAttribute("aria-disabled", "true");
    return;
  }

  excelLink.href = `/resultados/excel?periodo=${encodeURIComponent(period)}`;
  excelLink.classList.remove("is-disabled");
  excelLink.setAttribute("aria-disabled", "false");
}

function selectedMode() {
  return modeInputs.find((input) => input.checked)?.value || "mes";
}

function updatePeriodFields() {
  const mode = selectedMode();
  periodFields.forEach((field) => {
    field.hidden = field.dataset.periodField !== mode;
  });
}

function buildRequestPayload() {
  const mode = selectedMode();

  if (mode === "mes") {
    if (!monthInput.value) {
      setStatus("Selecciona un mes.", "warn");
      return null;
    }
    return { modo: "mes", mes: monthInput.value };
  }

  if (mode === "anio") {
    const year = Number(yearInput.value);
    if (!Number.isInteger(year) || year < 1900 || year > 9998) {
      setStatus("Selecciona un periodo anual valido.", "warn");
      return null;
    }
    return { modo: "anio", anio: year };
  }

  if (!startDateInput.value || !endDateInput.value) {
    setStatus("Selecciona fecha inicial y fecha final.", "warn");
    return null;
  }

  if (startDateInput.value > endDateInput.value) {
    setStatus("La fecha inicial no puede ser posterior a la fecha final.", "warn");
    return null;
  }

  return {
    modo: "rango",
    fecha_inicio: startDateInput.value,
    fecha_fin: endDateInput.value,
  };
}

function renderRows(rows) {
  resultsBody.innerHTML = "";

  if (!rows.length) {
    const row = document.createElement("tr");
    row.innerHTML = `<td colspan="11" class="empty">Sin resultados</td>`;
    resultsBody.appendChild(row);
    return;
  }

  for (const item of rows) {
    const row = document.createElement("tr");
    const totalNeto = firstFilled(item.total_neto, item.valor);
    row.innerHTML = `
      <td>${escapeHtml(item.fecha || "")}</td>
      <td>${escapeHtml(item.nit_tercero || "")}</td>
      <td>${escapeHtml(item.nombre_tercero || item.proveedor || "")}</td>
      <td>${escapeHtml(item.numero || "")}</td>
      <td class="description-cell">${escapeHtml(item.descripcion || "")}</td>
      <td class="money">${formatMoney(item.valor_bruto, item.moneda)}</td>
      <td class="money">${formatMoney(item.iva_19, item.moneda)}</td>
      <td class="money">${formatMoney(item.iva_5, item.moneda)}</td>
      <td class="money">${formatMoney(item.impo_8, item.moneda)}</td>
      <td class="money">${formatMoney(totalNeto, item.moneda)}</td>
      <td>${renderPdfCell(item)}</td>
    `;
    resultsBody.appendChild(row);
  }
}

function renderPdfCell(item) {
  if (!item.id || !item.ruta_pdf) {
    return '<span class="pdf-missing">Sin PDF</span>';
  }

  return `
    <a class="download-link" href="/facturas/${encodeURIComponent(item.id)}/pdf" download>
      Descargar PDF
    </a>
    <span class="pdf-path">Guardada en: ${escapeHtml(item.ruta_pdf)}</span>
  `;
}

function renderErrors(errors) {
  errorBox.innerHTML = "";
  for (const item of errors) {
    const entry = document.createElement("div");
    entry.className = "error-item";
    entry.textContent = `${item.extractor}: ${item.error}`;
    errorBox.appendChild(entry);
  }
}

function setStatus(text, state) {
  statusBox.textContent = text;
  statusBox.dataset.state = state;
}

function formatMoney(value, currency) {
  if (value === null || value === undefined || value === "") {
    return "";
  }
  const number = Number(value);
  if (Number.isNaN(number)) {
    return escapeHtml(String(value));
  }
  return `${currency || ""} ${number.toLocaleString("es-CO")}`.trim();
}

function firstFilled(...values) {
  const found = values.find((value) => value !== null && value !== undefined && value !== "");
  return found === undefined ? "" : found;
}

function formatApiError(detail) {
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    return detail.map((item) => item.msg).filter(Boolean).join(" ");
  }
  return "";
}

function toDateInputValue(value) {
  return [
    value.getFullYear(),
    String(value.getMonth() + 1).padStart(2, "0"),
    String(value.getDate()).padStart(2, "0"),
  ].join("-");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function initInteractiveBackground() {
  if (!backgroundCanvas) {
    return;
  }

  const context = backgroundCanvas.getContext("2d");
  const pointer = { x: 0, y: 0, active: false };
  let width = 0;
  let height = 0;
  let points = [];

  function resize() {
    const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
    width = window.innerWidth;
    height = window.innerHeight;
    backgroundCanvas.width = Math.floor(width * pixelRatio);
    backgroundCanvas.height = Math.floor(height * pixelRatio);
    backgroundCanvas.style.width = `${width}px`;
    backgroundCanvas.style.height = `${height}px`;
    context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
    spawn();
  }

  function spawn() {
    const count = Math.min(150, Math.max(70, Math.floor((width * height) / 13000)));
    points = Array.from({ length: count }, () => ({
      x: Math.random() * width,
      y: Math.random() * height,
      vx: (Math.random() - 0.5) * 0.55,
      vy: (Math.random() - 0.5) * 0.55,
      r: Math.random() * 1.7 + 0.45,
      a: Math.random() * 0.42 + 0.14,
    }));
  }

  function movePoint(point) {
    if (pointer.active) {
      const dx = point.x - pointer.x;
      const dy = point.y - pointer.y;
      const distance = Math.sqrt(dx * dx + dy * dy) || 1;
      if (distance < 180) {
        const force = (1 - distance / 180) * 0.045;
        point.vx += (dx / distance) * force;
        point.vy += (dy / distance) * force;
      }
    }

    point.vx *= 0.992;
    point.vy *= 0.992;
    point.x += point.vx;
    point.y += point.vy;

    if (point.x < -12) {
      point.x = width + 12;
    }
    if (point.x > width + 12) {
      point.x = -12;
    }
    if (point.y < -12) {
      point.y = height + 12;
    }
    if (point.y > height + 12) {
      point.y = -12;
    }
  }

  function drawPointerGlow() {
    if (!pointer.active) {
      return;
    }

    const glow = context.createRadialGradient(
      pointer.x,
      pointer.y,
      0,
      pointer.x,
      pointer.y,
      220,
    );
    glow.addColorStop(0, "rgba(74,127,212,0.18)");
    glow.addColorStop(0.45, "rgba(210,35,42,0.08)");
    glow.addColorStop(1, "rgba(210,35,42,0)");
    context.fillStyle = glow;
    context.beginPath();
    context.arc(pointer.x, pointer.y, 220, 0, Math.PI * 2);
    context.fill();
  }

  function draw() {
    context.clearRect(0, 0, width, height);
    drawPointerGlow();

    for (const point of points) {
      movePoint(point);
      context.beginPath();
      context.arc(point.x, point.y, point.r, 0, Math.PI * 2);
      context.fillStyle = `rgba(255,255,255,${point.a})`;
      context.fill();
    }

    for (let i = 0; i < points.length; i += 1) {
      for (let j = i + 1; j < points.length; j += 1) {
        const dx = points[i].x - points[j].x;
        const dy = points[i].y - points[j].y;
        const distance = Math.sqrt(dx * dx + dy * dy);
        if (distance < 118) {
          context.beginPath();
          context.moveTo(points[i].x, points[i].y);
          context.lineTo(points[j].x, points[j].y);
          context.strokeStyle = `rgba(255,255,255,${(1 - distance / 118) * 0.12})`;
          context.lineWidth = 0.7;
          context.stroke();
        }
      }

      if (pointer.active) {
        const dx = points[i].x - pointer.x;
        const dy = points[i].y - pointer.y;
        const distance = Math.sqrt(dx * dx + dy * dy);
        if (distance < 170) {
          context.beginPath();
          context.moveTo(points[i].x, points[i].y);
          context.lineTo(pointer.x, pointer.y);
          context.strokeStyle = `rgba(74,127,212,${(1 - distance / 170) * 0.22})`;
          context.lineWidth = 0.8;
          context.stroke();
        }
      }
    }

    requestAnimationFrame(draw);
  }

  window.addEventListener("pointermove", (event) => {
    pointer.x = event.clientX;
    pointer.y = event.clientY;
    pointer.active = true;
  });
  window.addEventListener("pointerleave", () => {
    pointer.active = false;
  });
  window.addEventListener("resize", resize);

  resize();
  draw();
}

initInteractiveBackground();
if (hasExtractor) {
  updatePeriodFields();
  renderRows([]);
}
