/* IoTS MqttClient - pretplata na topic sa događajima preko MQTT-a nad WebSocket-om. */
(function () {
  "use strict";

  // Broker se čita iz query parametara da bi ista slika radila i van Compose-a:
  //   index.html?host=localhost&port=9001
  var params = new URLSearchParams(location.search);
  var HOST = params.get("host") || location.hostname || "localhost";
  var PORT = params.get("port") || "9001";
  var TOPIC = params.get("topic") || "iots/events/#";
  var MAX_ROWS = 200;

  var els = {
    status: document.getElementById("mqtt-status"),
    
    topic: document.getElementById("mqtt-topic"),
    rows: document.getElementById("rows"),
    empty: document.getElementById("empty"),
    filter: document.getElementById("filter"),
    severity: document.getElementById("severity"),
    pause: document.getElementById("pause"),
    clear: document.getElementById("clear"),
    total: document.getElementById("cnt-total"),
    critical: document.getElementById("cnt-critical"),
    warning: document.getElementById("cnt-warning"),
    devices: document.getElementById("cnt-devices")
  };

  var events = [];
  var devices = new Set();
  var counts = { total: 0, CRITICAL: 0, WARNING: 0 };
  var paused = false;

  els.topic.textContent = TOPIC;

  function setStatus(text, ok) {
    els.status.textContent = "MQTT: " + text;
    els.status.className = "badge " + (ok ? "on" : "off");
  }

  function fmtTime(iso) {
    if (!iso) return "-";
    var d = new Date(iso);
    return isNaN(d) ? iso : d.toLocaleString("sr-RS", { hour12: false });
  }

  function fmtNum(v) {
    if (v === null || v === undefined) return "-";
    return typeof v === "number" ? String(Math.round(v * 10000) / 10000) : String(v);
  }

  function matches(ev) {
    var sev = els.severity.value;
    if (sev && ev.severity !== sev) return false;
    var q = els.filter.value.trim().toLowerCase();
    if (!q) return true;
    return [ev.deviceId, ev.field, ev.severity, ev.type, ev._topic]
      .filter(Boolean).join(" ").toLowerCase().indexOf(q) !== -1;
  }

  function rowFor(ev, isNew) {
    var tr = document.createElement("tr");
    if (isNew) {
      tr.className = "new";
    }
    var loc = ev.location
      ? ev.location.lat.toFixed(4) + ", " + ev.location.lon.toFixed(4)
      : "-";
    var cells = [
      fmtTime(ev.detectedAt),
      null, // severity - poseban element
      ev.deviceId || "-",
      ev.field || "-",
      fmtNum(ev.value) + (ev.unit ? " " + ev.unit : ""),
      fmtNum(ev.threshold),
      loc,
      ev._topic || "-"
    ];
    cells.forEach(function (value, i) {
      var td = document.createElement("td");
      if (i === 1) {
        var span = document.createElement("span");
        span.className = "sev " + (ev.severity || "");
        span.textContent = ev.severity || "-";
        td.appendChild(span);
      } else {
        td.textContent = value;
      }
      if (i === 4 || i === 5) td.className = "num-col";
      if (i === 7) td.className = "topic";
      tr.appendChild(td);
    });
    return tr;
  }

  function render() {
    els.rows.textContent = "";
    var shown = events.filter(matches);
    shown.forEach(function (ev) { els.rows.appendChild(rowFor(ev, false)); });
    els.empty.style.display = shown.length ? "none" : "block";
    if (events.length && !shown.length) {
      els.empty.textContent = "Nijedan događaj ne odgovara filteru.";
    }
  }

  function addEvent(ev) {
    events.unshift(ev);
    if (events.length > MAX_ROWS) events.pop();
    counts.total += 1;
    if (ev.severity === "CRITICAL") counts.CRITICAL += 1;
    if (ev.severity === "WARNING") counts.WARNING += 1;
    if (ev.deviceId) devices.add(ev.deviceId);

    els.total.textContent = counts.total;
    els.critical.textContent = counts.CRITICAL;
    els.warning.textContent = counts.WARNING;
    els.devices.textContent = devices.size;

    if (matches(ev)) {
      els.empty.style.display = "none";
      els.rows.insertBefore(rowFor(ev, true), els.rows.firstChild);
      while (els.rows.children.length > MAX_ROWS) {
        els.rows.removeChild(els.rows.lastChild);
      }
    }
  }

  els.filter.addEventListener("input", render);
  els.severity.addEventListener("change", render);
  els.clear.addEventListener("click", function () {
    events = [];
    els.rows.textContent = "";
    els.empty.textContent = "Lista je očišćena. Čeka se sledeći događaj…";
    els.empty.style.display = "block";
  });
  els.pause.addEventListener("click", function () {
    paused = !paused;
    els.pause.textContent = paused ? "nastavi" : "pauza";
    els.pause.className = paused ? "active" : "";
  });


  // ---- prebacivanje tabova (deljeno sa nats-app.js preko DOM-a) ----
  Array.prototype.forEach.call(document.querySelectorAll(".tab"), function (btn) {
    btn.addEventListener("click", function () {
      Array.prototype.forEach.call(document.querySelectorAll(".tab"), function (b) {
        b.classList.toggle("active", b === btn);
      });
      Array.prototype.forEach.call(document.querySelectorAll(".panel"), function (p) {
        p.hidden = p.id !== btn.dataset.panel;
      });
    });
  });

  setStatus("povezivanje…", false);
  var client = mqtt.connect("ws://" + HOST + ":" + PORT, {
    clientId: "mqtt-client-" + Math.random().toString(16).slice(2, 10),
    reconnectPeriod: 2000,
    connectTimeout: 8000,
    clean: true
  });

  client.on("connect", function () {
    setStatus("povezan", true);
    client.subscribe(TOPIC, { qos: 1 }, function (err) {
      if (err) setStatus("greška u pretplati", false);
    });
  });
  client.on("reconnect", function () { setStatus("ponovno povezivanje…", false); });
  client.on("offline", function () { setStatus("veza prekinuta", false); });
  client.on("error", function (err) {
    setStatus("greška: " + (err && err.message ? err.message : err), false);
  });
  client.on("message", function (topic, payload) {
    if (paused) return;
    var ev;
    try {
      ev = JSON.parse(payload.toString());
    } catch (e) {
      return;   // poruka koja nije JSON se ignoriše
    }
    ev._topic = topic;
    addEvent(ev);
  });
})();
