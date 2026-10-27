const fmt = (x) => (Number.isFinite(x) ? Number(x).toFixed(6) : "-");
const fmtMs = (x) => (Number.isFinite(x) ? `${x.toFixed(2)} ms` : "-");

const statusEl = document.getElementById("status");
const warningsEl = document.getElementById("warnings");
const tabButtons = [...document.querySelectorAll(".tab-btn")];
const tabPanels = [...document.querySelectorAll(".tab-panel")];
const greekButtons = [...document.querySelectorAll(".greek-btn")];

const metrics = {
  bsPrice: document.getElementById("bsPrice"),
  mcPrice: document.getElementById("mcPrice"),
  ci: document.getElementById("ci"),
  errorVsBs: document.getElementById("errorVsBs"),
  stdError: document.getElementById("stdError"),
  runtimeMetric: document.getElementById("runtimeMetric"),
  iterations: document.getElementById("iterations"),
};

const chartDefaults = {
  responsive: true,
  maintainAspectRatio: false,
  animation: { duration: 300 },
  plugins: {
    legend: { labels: { color: "#dbe7f3", font: { family: "JetBrains Mono" } } },
  },
  scales: {
    x: { ticks: { color: "#a7bdd3" }, grid: { color: "rgba(126,151,176,0.14)" } },
    y: { ticks: { color: "#a7bdd3" }, grid: { color: "rgba(126,151,176,0.14)" } },
  },
};

function createLineChart(canvasId, datasets = []) {
  return new Chart(document.getElementById(canvasId), {
    type: "line",
    data: { labels: [], datasets },
    options: chartDefaults,
  });
}

const charts = {
  spotCurve: createLineChart("spotCurveChart", [
    { label: "Analytical", data: [], borderColor: "#57c2ff", tension: 0.2, pointRadius: 0 },
    { label: "Monte Carlo", data: [], borderColor: "#6dd3a0", tension: 0.2, pointRadius: 0 },
  ]),
  ci: new Chart(document.getElementById("ciChart"), {
    type: "bar",
    data: {
      labels: ["CI Low", "MC", "CI High", "BS"],
      datasets: [{ label: "Price", data: [0, 0, 0, 0], backgroundColor: ["#2f4458", "#6dd3a0", "#2f4458", "#57c2ff"] }],
    },
    options: chartDefaults,
  }),
  convergence: new Chart(document.getElementById("convergenceChart"), {
    type: "line",
    data: { datasets: [{ label: "|MC - BS|", data: [], borderColor: "#ffb86a", parsing: false, pointRadius: 3 }] },
    options: {
      ...chartDefaults,
      scales: {
        x: { type: "logarithmic", ticks: { color: "#a7bdd3" }, grid: { color: "rgba(126,151,176,0.14)" }, title: { display: true, text: "Paths", color: "#a7bdd3" } },
        y: { type: "logarithmic", ticks: { color: "#a7bdd3" }, grid: { color: "rgba(126,151,176,0.14)" }, title: { display: true, text: "Absolute Error", color: "#a7bdd3" } },
      },
    },
  }),
  runtime: new Chart(document.getElementById("runtimeChart"), {
    type: "line",
    data: { datasets: [{ label: "Runtime (ms)", data: [], borderColor: "#9ec9ff", parsing: false, pointRadius: 3 }] },
    options: {
      ...chartDefaults,
      scales: {
        x: { type: "logarithmic", ticks: { color: "#a7bdd3" }, grid: { color: "rgba(126,151,176,0.14)" }, title: { display: true, text: "Paths", color: "#a7bdd3" } },
        y: { ticks: { color: "#a7bdd3" }, grid: { color: "rgba(126,151,176,0.14)" }, title: { display: true, text: "Runtime (ms)", color: "#a7bdd3" } },
      },
    },
  }),
  greeks: createLineChart("greeksChart", [
    { label: "Analytical", data: [], borderColor: "#57c2ff", tension: 0.2, pointRadius: 0 },
    { label: "Numerical", data: [], borderColor: "#6dd3a0", tension: 0.2, pointRadius: 0 },
  ]),
  greeksError: createLineChart("greeksErrorChart", [
    { label: "Absolute error", data: [], borderColor: "#ffb86a", tension: 0.2, pointRadius: 0 },
  ]),
  ivTrace: createLineChart("ivTraceChart", [
    { label: "Sigma", data: [], borderColor: "#f59f66", tension: 0.15, pointRadius: 3 },
  ]),
  ivResidual: createLineChart("ivResidualChart", [
    { label: "Residual", data: [], borderColor: "#d67dff", tension: 0.15, pointRadius: 3 },
  ]),
};

const cache = new Map();
let latestGreeks = null;
let selectedGreek = "delta";

function setStatus(text, type = "idle") {
  statusEl.textContent = text;
  statusEl.className = `status ${type}`;
}

function setTab(tabName) {
  for (const btn of tabButtons) {
    btn.classList.toggle("active", btn.dataset.tab === tabName);
  }
  for (const panel of tabPanels) {
    panel.classList.toggle("active", panel.id === `panel-${tabName}`);
  }
}

function setGreek(greekName) {
  selectedGreek = greekName;
  for (const btn of greekButtons) {
    btn.classList.toggle("active", btn.dataset.greek === greekName);
  }
  if (latestGreeks) {
    renderGreeks(greekName, latestGreeks);
  }
}

function parseNumber(id, { required = true } = {}) {
  const raw = document.getElementById(id).value;
  if (!required && raw === "") {
    return null;
  }
  const value = Number(raw);
  if (!Number.isFinite(value)) {
    throw new Error(`Invalid input: ${id}`);
  }
  return value;
}

function getPayloadBase() {
  const payload = {
    spot: parseNumber("spot"),
    strike: parseNumber("strike"),
    maturity: parseNumber("maturity"),
    rate: parseNumber("rate"),
    volatility: parseNumber("volatility"),
    option_type: document.getElementById("optionType").value,
  };

  if (payload.spot <= 0 || payload.strike <= 0 || payload.maturity <= 0 || payload.volatility <= 0) {
    throw new Error("Spot, strike, maturity, and volatility must be > 0.");
  }
  return payload;
}

function getSharedSettings() {
  const seed = parseNumber("seed", { required: false });
  return {
    mc_paths: Math.floor(parseNumber("mcPaths")),
    seed,
    antithetic: document.getElementById("antithetic").value === "true",
  };
}

async function apiPost(path, payload) {
  const key = `${path}:${JSON.stringify(payload)}`;
  if (cache.has(key)) {
    return cache.get(key);
  }

  const resp = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!resp.ok) {
    const detail = await resp.text();
    throw new Error(`${path} failed: ${detail}`);
  }

  const json = await resp.json();
  cache.set(key, json);
  return json;
}

function updateWarnings(warnings = []) {
  warningsEl.innerHTML = "";
  for (const w of warnings) {
    const li = document.createElement("li");
    li.textContent = w;
    warningsEl.appendChild(li);
  }
}

function updateSummary(priceResult) {
  metrics.bsPrice.textContent = fmt(priceResult.bs_price);
  metrics.mcPrice.textContent = fmt(priceResult.mc_price);
  metrics.ci.textContent = `${fmt(priceResult.confidence_interval[0])} to ${fmt(priceResult.confidence_interval[1])}`;
  metrics.errorVsBs.textContent = fmt(priceResult.error_vs_bs);
  metrics.stdError.textContent = fmt(priceResult.standard_error);
  metrics.runtimeMetric.textContent = fmtMs(priceResult.diagnostics?.mc_runtime_ms);
}

function renderGreeks(greek, result) {
  const labels = result.spot.map((s) => s.toFixed(2));
  charts.greeks.data.labels = labels;
  charts.greeks.data.datasets[0].data = result.analytic[greek];
  charts.greeks.data.datasets[1].data = result.numerical[greek];
  charts.greeks.update();

  charts.greeksError.data.labels = labels;
  charts.greeksError.data.datasets[0].data = result.analytic[greek].map((v, i) => Math.abs(v - result.numerical[greek][i]));
  charts.greeksError.update();
}

async function loadPriceAndCoreCharts() {
  const base = getPayloadBase();
  const shared = getSharedSettings();

  const [price, spotCurve, runtime] = await Promise.all([
    apiPost("/price", { ...base, ...shared }),
    apiPost("/spot-curve", { ...base, ...shared, num_points: 25, min_factor: 0.5, max_factor: 1.5 }),
    apiPost("/runtime-profile", { ...base, antithetic: shared.antithetic, seed: shared.seed, path_grid: [10000, 100000, 1000000] }),
  ]);

  updateSummary(price);
  metrics.iterations.textContent = "-";
  updateWarnings(price.diagnostics?.warnings || []);

  charts.spotCurve.data.labels = spotCurve.spot.map((x) => x.toFixed(2));
  charts.spotCurve.data.datasets[0].data = spotCurve.bs_price;
  charts.spotCurve.data.datasets[1].data = spotCurve.mc_price;
  charts.spotCurve.update();

  charts.ci.data.datasets[0].data = [
    price.confidence_interval[0],
    price.mc_price,
    price.confidence_interval[1],
    price.bs_price,
  ];
  charts.ci.update();

  charts.runtime.data.datasets[0].data = runtime.series.map((r) => ({ x: r.paths, y: r.runtime_ms }));
  charts.runtime.update();

  setTab("pricing");
  setStatus(`BS ${fmtMs(price.diagnostics.bs_runtime_ms)} | MC ${fmtMs(price.diagnostics.mc_runtime_ms)}`);
}

async function runConvergence() {
  const base = getPayloadBase();
  const shared = getSharedSettings();

  const result = await apiPost("/convergence", {
    ...base,
    seed: shared.seed,
    antithetic: shared.antithetic,
    path_grid: [1000, 2500, 5000, 10000, 25000, 50000, 100000, 250000],
  });

  charts.convergence.data.datasets[0].data = result.series.map((row) => ({ x: row.paths, y: Math.max(row.abs_error, 1e-14) }));
  charts.convergence.update();

  updateWarnings(result.diagnostics?.warnings || []);
  setTab("convergence");
  setStatus(`Convergence slope ≈ ${fmt(result.diagnostics.loglog_error_slope)}`);
}

async function runGreeks() {
  const base = getPayloadBase();
  const bumpSize = parseNumber("bumpSize");
  if (bumpSize <= 0) {
    throw new Error("Bump size must be > 0");
  }

  latestGreeks = await apiPost("/greeks", {
    ...base,
    bump_size: bumpSize,
    num_points: 41,
    spot_min_factor: 0.5,
    spot_max_factor: 1.5,
  });

  renderGreeks(selectedGreek, latestGreeks);
  setTab("greeks");
  setStatus(`Greeks computed with bump ε = ${latestGreeks.diagnostics.bump_size}`);
}

async function solveImpliedVol() {
  const base = getPayloadBase();
  const marketPrice = parseNumber("marketPrice");
  const tolerance = parseNumber("tolerance");

  if (marketPrice <= 0 || tolerance <= 0) {
    throw new Error("Market price and tolerance must be > 0");
  }

  const result = await apiPost("/implied-vol", {
    spot: base.spot,
    strike: base.strike,
    maturity: base.maturity,
    rate: base.rate,
    option_type: base.option_type,
    market_price: marketPrice,
    initial_guess: base.volatility,
    tolerance,
    max_iterations: 30,
  });

  metrics.iterations.textContent = String(result.iterations);
  charts.ivTrace.data.labels = result.trace.map((r) => r.iteration);
  charts.ivTrace.data.datasets[0].data = result.trace.map((r) => r.sigma);
  charts.ivTrace.update();

  charts.ivResidual.data.labels = result.trace.map((r) => r.iteration);
  charts.ivResidual.data.datasets[0].data = result.trace.map((r) => Math.abs(r.residual));
  charts.ivResidual.update();

  updateWarnings(result.diagnostics?.warning ? [result.diagnostics.warning] : []);
  setTab("iv");
  setStatus(
    `Implied vol ${fmt(result.implied_volatility)} | ${result.converged ? "converged" : "not converged"}`,
    result.converged ? "idle" : "error",
  );
}

async function runAction(action) {
  try {
    setStatus("Loading...", "loading");
    await action();
    if (statusEl.classList.contains("loading")) {
      setStatus("Done", "idle");
    }
  } catch (err) {
    setStatus(err.message || "Unexpected error", "error");
  }
}

for (const btn of tabButtons) {
  btn.addEventListener("click", () => setTab(btn.dataset.tab));
}

for (const btn of greekButtons) {
  btn.addEventListener("click", () => setGreek(btn.dataset.greek));
}

document.getElementById("btnPrice").addEventListener("click", () => runAction(loadPriceAndCoreCharts));
document.getElementById("btnConvergence").addEventListener("click", () => runAction(runConvergence));
document.getElementById("btnGreeks").addEventListener("click", () => runAction(runGreeks));
document.getElementById("btnImpliedVol").addEventListener("click", () => runAction(solveImpliedVol));

runAction(loadPriceAndCoreCharts);
