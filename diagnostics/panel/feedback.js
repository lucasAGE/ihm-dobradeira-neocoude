/* Pure feedback interpretation, shared by offline reports and the receive-only monitor. */
(function (root) {
  "use strict";
  const channels = [];
  const add = (key, label, type = "number", unit = "") => channels.push({key, label, type, unit});
  add("encoder_raw", "Encoder · bruto 16 bits", "raw");
  add("encoder_pulses", "Encoder · pulsos normalizados", "raw");
  add("encoder_degrees", "Encoder · ângulo informado", "number", "°");
  add("encoder_degrees_disco", "Encoder · ângulo do disco informado", "number", "°");
  ["Zero", "Reserva / carenagem", "Pedal avanço", "Pedal parada", "Pedal recuo", "Segurança (NF no mapa)", "Emergência (NF no mapa)", "Reserva"]
    .forEach((label, i) => add(`inputs.E${i}`, `E${i} · ${label}`, "bit"));
  ["Comando avanço", "Comando recuo", "Habilita inversor", "Reserva", "LED dobra 1", "LED dobra 2", "LED dobra 3", "Reserva"]
    .forEach((label, i) => add(`outputs.S${i}`, `S${i} · ${label}`, "bit"));
  for (const key of ["DIR_AVANCO", "DIR_RECUO", "MODO_AUTO", "MODO_MANUAL", "PEDAL_SEGURA", "NA_POSICAO_ZERO", "ATINGIU_ANGULO", "HABILITADO"])
    add(`control_bits.${key}`, `CLP · ${key}`, "bit");
  for (const key of ["ST_IDLE", "ST_AGUARDA_DIRECAO", "ST_DOBRANDO", "ST_RETORNANDO", "ST_AGUARDA_PROXIMA", "ST_COMPLETO", "ST_EMERGENCIA", "ST_MANUAL", "ST_CALIBRACAO"])
    add(`states.${key}`, `Estado · ${key}`, "bit");
  for (let i = 1; i <= 3; i++) add(`angles.bend_${i}`, `Ângulo programado · dobra ${i}`, "number", "°");
  add("target_angle", "Ângulo alvo informado", "number", "°");
  add("dobra_atual", "Dobra selecionada"); add("contador_pecas", "Contador de peças");
  add("velocidade_rpm", "RPM estimado do comando do inversor", "number", " rpm");
  const numericKeys = new Set(channels.filter(c => !c.key.includes(".")).map(c => c.key).concat(["poll_count", "timestamp", "machine_state_address", "feedback_version"]));
  const booleans = new Set(["encoder_moving", "modbus_connected", "heartbeat", "poll_ok"]);
  const texts = new Set(["last_update", "encoder_direction", "machine_state_name", "machine_state_error", "feedback_session"]);
  const qualityKeys = new Set(channels.map(channel => channel.key));
  function sanitizeQuality(source) {
    if (!source || typeof source !== "object" || Array.isArray(source)) return {};
    const result = {};
    for (const [key, item] of Object.entries(source)) {
      if (!qualityKeys.has(key) || !item || typeof item !== "object" || Array.isArray(item)) continue;
      const entry = {status: ["ok", "error", "not_read"].includes(item.status) ? item.status : "error"};
      for (const name of ["last_attempt_at", "last_success_at", "last_error"])
        entry[name] = typeof item[name] === "string" ? item[name].slice(0, 160) : null;
      for (const name of ["success_count", "error_count"])
        entry[name] = Number.isSafeInteger(item[name]) && item[name] >= 0 ? item[name] : null;
      result[key] = entry;
    }
    return result;
  }
  const nested = new Map(["inputs", "outputs", "control_bits", "states", "angles"].map(group =>
    [group, new Set(channels.filter(c => c.key.startsWith(group + ".")).map(c => c.key.split(".")[1]))]));
  function valid(value, type) {
    return type === "bit" ? typeof value === "boolean" : typeof value === "number" && Number.isFinite(value) &&
      (type !== "raw" || (Number.isInteger(value) && value >= 0 && value <= 65535));
  }
  function sanitize(data) {
    if (!data || typeof data !== "object" || Array.isArray(data)) return null;
    const safe = {};
    for (const [key, value] of Object.entries(data)) {
      if (key === "read_quality") safe[key] = sanitizeQuality(value);
      else if (numericKeys.has(key)) safe[key] = typeof value === "number" && Number.isFinite(value) ? value : null;
      else if (booleans.has(key)) safe[key] = typeof value === "boolean" ? value : null;
      else if (texts.has(key)) safe[key] = typeof value === "string" ? value.slice(0, 160) : null;
      else if (nested.has(key) && value && typeof value === "object" && !Array.isArray(value)) {
        safe[key] = {};
        for (const child of nested.get(key)) if (Object.hasOwn(value, child)) {
          const type = key === "angles" ? "number" : "bit";
          safe[key][child] = valid(value[child], type) ? value[child] : null;
        }
      } else if (nested.has(key)) safe[key] = null;
    }
    return safe;
  }
  function get(data, key) {
    const pieces = key.split(".");
    if (!Object.hasOwn(data, pieces[0])) return {present: false};
    if (pieces.length === 1) return {present: true, value: data[pieces[0]]};
    const group = data[pieces[0]];
    if (group === null) return {present: true, value: null};
    return group && Object.hasOwn(group, pieces[1]) ? {present: true, value: group[pieces[1]]} : {present: false};
  }
  function summarize(frames, endedMs = null) {
    const rows = channels.map(channel => ({...channel, value: null, last_good_value: null, updates: 0, changes: 0,
      invalid: 0, last_received_at: null, last_elapsed_ms: null, quality: "missing"}));
    let previousTime = null, firstTime = null, lastTime = null, maxGap = 0, count = 0, timedCount = 0, timeErrors = 0;
    let pollFirst = null, pollLast = null, pollResets = 0, pollSegments = 0, modbus = null;
    let quality = {}, machineState = null, machineError = null, pollOk = null;
    let session = null, encoderFirst = null, encoderLast = null, encoderReset = false;
    const encoderSeries = [];
    for (const frame of Array.isArray(frames) ? frames : []) {
      if (!frame || !["full_state", "state_update"].includes(frame.type)) continue;
      const data = sanitize(frame.data); if (!data) continue;
      let instant = Number.isFinite(frame.elapsed_ms) ? frame.elapsed_ms : null;
      if (instant !== null && (instant < 0 || (previousTime !== null && instant < previousTime))) { timeErrors++; instant = null; }
      if (instant !== null) {
        timedCount++;
        if (firstTime === null) firstTime = instant;
        if (previousTime !== null) maxGap = Math.max(maxGap, instant - previousTime);
        previousTime = lastTime = instant;
      }
      count++;
      if (frame.type === "full_state") {
        // A complete snapshot starts a new baseline: missing values must not survive a reconnect.
        for (const row of rows) { row.value = null; row.quality = "missing"; row.last_received_at = null; row.last_elapsed_ms = null; }
        modbus = null;
        quality = {}; machineState = machineError = pollOk = null;
        if (encoderLast) encoderReset = true;
        if (pollLast !== null) pollSegments++;
      }
      if (Object.hasOwn(data, "modbus_connected")) modbus = data.modbus_connected;
      if (Object.hasOwn(data, "machine_state_name")) machineState = data.machine_state_name;
      if (Object.hasOwn(data, "machine_state_error")) machineError = data.machine_state_error;
      if (Object.hasOwn(data, "poll_ok")) pollOk = data.poll_ok;
      if (Object.hasOwn(data, "feedback_session")) {
        if (session !== null && session !== data.feedback_session) encoderReset = true;
        session = data.feedback_session;
      }
      if (data.read_quality) {
        Object.assign(quality, data.read_quality);
        const counter = data.read_quality.encoder_raw?.success_count;
        if (Number.isSafeInteger(counter) && instant !== null) {
          if (encoderLast && counter < encoderLast.value) encoderReset = true;
          const point = {value: counter, time: instant};
          if (!encoderFirst) encoderFirst = point;
          encoderLast = point;
        }
      }
      if (Number.isInteger(data.poll_count) && data.poll_count >= 0 && instant !== null) {
        if (pollLast && data.poll_count < pollLast.value) pollResets++;
        const point = {value: data.poll_count, time: instant};
        if (pollFirst === null) pollFirst = point;
        pollLast = point;
      }
      for (const row of rows) {
        const field = get(data, row.key); if (!field.present) continue;
        row.updates++; row.last_received_at = frame.received_at || null; row.last_elapsed_ms = instant;
        if (!valid(field.value, row.type)) { row.value = null; row.quality = "invalid"; row.invalid++; continue; }
        if (row.last_good_value !== null && row.last_good_value !== field.value) row.changes++;
        row.value = row.last_good_value = field.value; row.quality = "backend_unverified";
        if (row.key === "encoder_raw") encoderSeries.push({elapsed_ms: instant, value: field.value});
      }
    }
    const end = Number.isFinite(endedMs) && endedMs >= (lastTime || 0) ? endedMs : lastTime;
    for (const row of rows) {
      row.since_field_received_ms = end !== null && row.last_elapsed_ms !== null ? end - row.last_elapsed_ms : null;
      const key = row.key.startsWith("encoder_") ? "encoder_raw" : row.key;
      const entry = quality[key];
      row.read_quality = entry || null;
      if (entry?.status === "error") { row.value = null; row.quality = "read_error"; }
      else if (entry?.status === "not_read") { row.value = null; row.quality = "missing"; }
      else if (entry?.status === "ok" && row.value !== null) row.quality = "backend_read_ok";
    }
    const span = firstTime !== null && lastTime > firstTime ? (lastTime - firstTime) / 1000 : null;
    const pollSpan = pollFirst && pollLast && pollLast.time > pollFirst.time ? (pollLast.time - pollFirst.time) / 1000 : null;
    const encoderSpan = encoderFirst && encoderLast && encoderLast.time > encoderFirst.time ? (encoderLast.time - encoderFirst.time) / 1000 : null;
    return {rows, state_messages: count, message_hz: span && !timeErrors && timedCount === count ? (count - 1) / span : null,
      poll_attempt_hz: pollSpan && !pollResets && !pollSegments && !timeErrors && timedCount === count ? (pollLast.value - pollFirst.value) / pollSpan : null,
      successful_encoder_read_hz: encoderSpan && !encoderReset && !timeErrors && timedCount === count ? (encoderLast.value - encoderFirst.value) / encoderSpan : null,
      encoder_success_count: quality.encoder_raw?.success_count ?? null, encoder_error_count: quality.encoder_raw?.error_count ?? null,
      machine_state_name: machineState, machine_state_error: machineError, poll_ok: pollOk,
      rtu_latency_ms: null, poll_resets: pollResets, timing_errors: timeErrors,
      max_message_gap_ms: count > 1 && !timeErrors && timedCount === count ? maxGap : null,
      silence_ms: end !== null && lastTime !== null && !timeErrors && timedCount === count ? end - lastTime : null,
      modbus_connected: modbus, encoder_series: encoderSeries.slice(-600)};
  }
  function format(row) {
    if (row.value === null) return row.quality === "read_error" ? "Falha de leitura" : row.quality === "invalid" ? "Inválido / sem leitura" : "Não recebido";
    return row.type === "bit" ? (row.value ? "1" : "0") : `${row.value}${row.unit}`;
  }
  function renderTable(target, summary) {
    target.replaceChildren();
    const table = document.createElement("table"), head = document.createElement("thead"), body = document.createElement("tbody"), tr = document.createElement("tr");
    for (const title of ["Sinal conforme o código", "Valor recebido", "Mudanças observadas", "Última recepção do campo", "Qualidade", "Última leitura OK no backend"] ) {
      const th = document.createElement("th"); th.scope = "col"; th.textContent = title; tr.appendChild(th);
    }
    head.appendChild(tr); table.append(head, body);
    for (const row of summary.rows) {
      const line = document.createElement("tr"); line.dataset.signal = row.key;
      for (const value of [row.label, format(row), row.changes, row.last_received_at || "—",
        row.quality === "backend_read_ok" ? "Leitura OK informada pelo backend" : row.quality === "read_error" ? `Erro: ${row.read_quality.last_error || "não informado"}` :
          row.quality === "backend_unverified" ? "Validade da leitura não informada" : row.quality === "invalid" ? "Nulo ou tipo inválido" : "Ausente no feedback",
        row.read_quality?.last_success_at || "—"]) {
        const td = document.createElement("td"); td.textContent = value; line.appendChild(td);
      }
      body.appendChild(line);
    }
    target.appendChild(table);
  }
  const api = {channels, sanitize, summarize, format, renderTable};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.NeocoudeFeedback = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
