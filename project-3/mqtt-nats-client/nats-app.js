/* IoTS MqttNats - NATS deo: pretplata na subject sa rezultatima ML modela. */
import { connect, StringCodec } from "./vendor/nats.js";

const params = new URLSearchParams(location.search);
const HOST = params.get("natsHost") || location.hostname || "localhost";
const PORT = params.get("natsPort") || "9222";
const SUBJECT = params.get("subject") || "iots.analytics.predictions.>";
const MAX_ROWS = 200;

const els = {
  status: document.getElementById("nats-status"),
  subject: document.getElementById("nats-subject"),
  rows: document.getElementById("p-rows"),
  empty: document.getElementById("p-empty"),
  filter: document.getElementById("p-filter"),
  correct: document.getElementById("p-correct"),
  pause: document.getElementById("p-pause"),
  clear: document.getElementById("p-clear"),
  total: document.getElementById("p-total"),
  accuracy: document.getElementById("p-accuracy"),
  confidence: document.getElementById("p-confidence"),
  latency: document.getElementById("p-latency"),
};

els.subject.textContent = SUBJECT;

let items = [];
let stats = { total: 0, correct: 0, confSum: 0, latSum: 0 };
let paused = false;

function setStatus(text, ok) {
  els.status.textContent = "NATS: " + text;
  els.status.className = "badge " + (ok ? "on" : "off");
}

function fmtTime(iso) {
  if (!iso) return "-";
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleString("sr-RS", { hour12: false });
}

function matches(p) {
  const want = els.correct.value;
  if (want === "true" && p.correct !== true) return false;
  if (want === "false" && p.correct !== false) return false;
  const q = els.filter.value.trim().toLowerCase();
  if (!q) return true;
  return [p.deviceId, p.prediction, p._subject].filter(Boolean)
    .join(" ").toLowerCase().includes(q);
}

function rowFor(p, isNew) {
  const tr = document.createElement("tr");
  if (isNew) tr.className = "new";

  const add = (text, cls) => {
    const td = document.createElement("td");
    if (cls) td.className = cls;
    td.textContent = text;
    tr.appendChild(td);
    return td;
  };

  add(fmtTime(p.predictedAt));
  add(p.deviceId || "-");
  add(p.prediction || "-");

  // pouzdanost kao traka + broj
  const tdConf = document.createElement("td");
  const bar = document.createElement("div");
  bar.className = "bar";
  const fill = document.createElement("div");
  fill.className = "bar-fill";
  fill.style.width = Math.round((p.confidence || 0) * 100) + "%";
  bar.appendChild(fill);
  const label = document.createElement("span");
  label.className = "bar-label";
  label.textContent = ((p.confidence || 0) * 100).toFixed(1) + "%";
  tdConf.appendChild(bar);
  tdConf.appendChild(label);
  tr.appendChild(tdConf);

  const tdOk = document.createElement("td");
  const badge = document.createElement("span");
  badge.className = "sev " + (p.correct ? "OK" : "BAD");
  badge.textContent = p.correct ? "tačno" : "netačno";
  tdOk.appendChild(badge);
  tr.appendChild(tdOk);

  add(p.latencyMs != null ? p.latencyMs + " ms" : "-", "num-col");
  add(p._subject || "-", "topic");
  return tr;
}

function render() {
  els.rows.textContent = "";
  const shown = items.filter(matches);
  shown.forEach((p) => els.rows.appendChild(rowFor(p, false)));
  els.empty.style.display = shown.length ? "none" : "block";
  if (items.length && !shown.length) {
    els.empty.textContent = "Nijedna predikcija ne odgovara filteru.";
  }
}

function addPrediction(p) {
  items.unshift(p);
  if (items.length > MAX_ROWS) items.pop();

  stats.total += 1;
  if (p.correct) stats.correct += 1;
  stats.confSum += p.confidence || 0;
  stats.latSum += p.latencyMs || 0;

  els.total.textContent = stats.total;
  els.accuracy.textContent = ((stats.correct / stats.total) * 100).toFixed(1) + "%";
  els.confidence.textContent = ((stats.confSum / stats.total) * 100).toFixed(1) + "%";
  els.latency.textContent = (stats.latSum / stats.total).toFixed(0) + " ms";

  if (matches(p)) {
    els.empty.style.display = "none";
    els.rows.insertBefore(rowFor(p, true), els.rows.firstChild);
    while (els.rows.children.length > MAX_ROWS) {
      els.rows.removeChild(els.rows.lastChild);
    }
  }
}

els.filter.addEventListener("input", render);
els.correct.addEventListener("change", render);
els.clear.addEventListener("click", () => {
  items = [];
  els.rows.textContent = "";
  els.empty.textContent = "Lista je očišćena. Čeka se sledeća predikcija…";
  els.empty.style.display = "block";
});
els.pause.addEventListener("click", () => {
  paused = !paused;
  els.pause.textContent = paused ? "nastavi" : "pauza";
  els.pause.className = paused ? "active" : "";
});

async function run() {
  setStatus("povezivanje…", false);
  const sc = StringCodec();
  for (;;) {
    try {
      const nc = await connect({ servers: `ws://${HOST}:${PORT}`, name: "mqtt-nats-client" });
      setStatus("povezan", true);

      (async () => {
        for await (const status of nc.status()) {
          if (status.type === "disconnect") setStatus("veza prekinuta", false);
          if (status.type === "reconnect") setStatus("povezan", true);
        }
      })().catch(() => {});

      const sub = nc.subscribe(SUBJECT);
      for await (const msg of sub) {
        if (paused) continue;
        try {
          const p = JSON.parse(sc.decode(msg.data));
          p._subject = msg.subject;
          addPrediction(p);
        } catch (e) { /* poruka koja nije JSON se ignoriše */ }
      }
      setStatus("pretplata zatvorena", false);
    } catch (err) {
      setStatus("greška: " + (err && err.message ? err.message : err), false);
    }
    await new Promise((r) => setTimeout(r, 2000));   // pokušaj ponovo
  }
}

run();
