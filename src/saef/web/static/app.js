const monthInput = document.querySelector("#mes");
const runButton = document.querySelector("#ejecutar");
const statusBox = document.querySelector("#estado");
const errorBox = document.querySelector("#errores");
const resultsBody = document.querySelector("#resultados tbody");

const now = new Date();
monthInput.value = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;

runButton.addEventListener("click", async () => {
  const mes = monthInput.value;
  if (!mes) {
    setStatus("Selecciona un mes.", "warn");
    return;
  }

  runButton.disabled = true;
  setStatus("Ejecutando...", "info");
  errorBox.innerHTML = "";
  renderRows([]);

  try {
    const response = await fetch("/ejecutar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mes }),
    });
    const payload = await response.json();

    if (!response.ok) {
      throw new Error(payload.detail || "No se pudo ejecutar el extractor.");
    }

    setStatus(`${payload.estado} · ${payload.count} factura(s) procesada(s)`, "ok");
    renderRows(payload.resultados || []);
    renderErrors(payload.errores || []);
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    runButton.disabled = false;
  }
});

function renderRows(rows) {
  resultsBody.innerHTML = "";

  if (!rows.length) {
    const row = document.createElement("tr");
    row.innerHTML = `<td colspan="7" class="empty">Sin resultados</td>`;
    resultsBody.appendChild(row);
    return;
  }

  for (const item of rows) {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${escapeHtml(item.proveedor || "")}</td>
      <td>${escapeHtml(item.numero || "")}</td>
      <td>${escapeHtml(item.fecha || "")}</td>
      <td>${formatMoney(item.valor, item.moneda)}</td>
      <td><span class="status">${escapeHtml(item.estado || "")}</span></td>
      <td>${escapeHtml(item.ruta_pdf || "")}</td>
      <td>${escapeHtml(item.periodo || "")}</td>
    `;
    resultsBody.appendChild(row);
  }
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

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

renderRows([]);

