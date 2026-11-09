"use strict";
const feedback = globalThis.NeocoudeFeedback;
const byId = id => document.getElementById(id);
let socket = null, generation = 0, clockStart = 0, stopTimer = null, connectTimer = null, report = null, frames = [], events = [], bytes = 0;
let dirty = true, lastRender = 0, endedMs = null;
function localIPv4(value) {
  if (!/^\d{1,3}(\.\d{1,3}){3}$/.test(value)) return false;
  const p = value.split(".").map(Number); if (p.some(part => part > 255)) return false;
  return p[0] === 10 || p[0] === 127 || (p[0] === 192 && p[1] === 168) ||
    (p[0] === 172 && p[1] >= 16 && p[1] <= 31) || (p[0] === 169 && p[1] === 254);
}
function event(text) {
  events.push(`${new Date().toISOString()} · ${text}`); events = events.slice(-100); dirty = true;
}
function finish(status, text) {
  clearTimeout(stopTimer); clearTimeout(connectTimer);
  const connection = socket; socket = null; generation++;
  if (connection) { connection.onopen = connection.onmessage = connection.onerror = connection.onclose = null; connection.close(); }
  if (report) {
    endedMs = performance.now() - clockStart;
    Object.assign(report.checks.websocket, {status, elapsed_seconds: endedMs / 1000, ended_at: new Date().toISOString(), frames});
  }
  byId("connect").disabled = false; byId("stop").disabled = true;
  byId("save").disabled = !report; byId("live-status").textContent = text;
  event(text);
}
function metric(label, value, note) {
  const article = document.createElement("article"); article.className = "card";
  for (const [css, text] of [["label", label], ["value", value ?? "Não disponível"], ["note", note]]) {
    const part = document.createElement("div"); part.className = css; part.textContent = text; article.appendChild(part);
  }
  byId("live-metrics").appendChild(article);
}
function draw() {
  const now = performance.now(); if (!dirty && (!socket || now - lastRender < 1000)) return;
  dirty = false; lastRender = now;
  const summary = feedback.summarize(frames, endedMs ?? (report ? now - clockStart : null));
  const raw = summary.rows.find(row => row.key === "encoder_raw"), angle = summary.rows.find(row => row.key === "encoder_degrees");
  byId("live-metrics").replaceChildren();
  metric("Encoder bruto", feedback.format(raw), "Último valor publicado; não certifica leitura válida");
  metric("Ângulo informado", feedback.format(angle), "Conversão do backend; calibração física pendente");
  metric("Mensagens de estado", summary.state_messages, "Recebidas por este notebook");
  metric("Frequência de mensagens", summary.message_hz === null ? null : summary.message_hz.toFixed(2) + " Hz", "Não é frequência de leitura do encoder");
  metric("Ciclos de polling informados", summary.poll_attempt_hz === null ? null : summary.poll_attempt_hz.toFixed(2) + " Hz", "Incluem tentativas que podem ter falhado");
  metric("Silêncio desde último estado", summary.silence_ms === null ? null : (summary.silence_ms / 1000).toFixed(1) + " s", socket ? "Observação em andamento" : "Medido até o encerramento da coleta");
  metric("Maior intervalo entre estados", summary.max_message_gap_ms === null ? null : summary.max_message_gap_ms.toFixed(0) + " ms", "Intervalo no notebook; não é latência RTU");
  metric("Leituras OK do encoder", summary.successful_encoder_read_hz === null ? null : summary.successful_encoder_read_hz.toFixed(2) + " Hz", "Taxa entre contadores do backend; não certifica calibração");
  metric("Erros de leitura do encoder", summary.encoder_error_count, "Contador desde o início desta instância do backend");
  metric("Estado informado", summary.machine_state_name, summary.machine_state_error || "Exige leitura completa e um único estado ativo no backend corrigido");
  metric("Conexão CLP informada", summary.modbus_connected === null ? null : (summary.modbus_connected ? "Declarada conectada" : "Desconectada"), "Flag do backend; não comprova leitura válida");
  metric("Mensagens inválidas", report?.checks.websocket.malformed ?? 0, "Erros de formato observados no notebook");
  feedback.renderTable(byId("signals"), summary);
  byId("events").textContent = events.join("\n") || "Nenhum evento.";
  if (socket?.readyState === WebSocket.OPEN && (summary.silence_ms ?? (now - clockStart)) > 5000)
    byId("live-status").textContent = "Conexão aberta, sem novos estados há mais de 5 s. Valores exibidos podem estar antigos.";
  else if (socket?.readyState === WebSocket.OPEN && summary.modbus_connected === false)
    byId("live-status").textContent = "O backend informa CLP desconectado. Valores exibidos podem estar antigos.";
  else if (socket?.readyState === WebSocket.OPEN && summary.poll_ok === false)
    byId("live-status").textContent = "O backend informa falha de leitura. Confira a qualidade de cada sinal.";
}
byId("connect").addEventListener("click", () => {
  const address = byId("address").value.trim(), port = Number(byId("port").value), seconds = Number(byId("seconds").value);
  if (!localIPv4(address) || !Number.isInteger(port) || port < 1 || port > 65535 || !Number.isInteger(seconds) || seconds < 5 || seconds > 120) {
    byId("live-status").textContent = "Informe um IPv4 local, porta 1–65535 e duração de 5–120 segundos."; return;
  }
  if (socket) return;
  const run = ++generation; frames = []; events = []; bytes = 0; endedMs = null; clockStart = performance.now();
  report = {schema_version: 1, kind: "windows_probe", tool_version: "0.3.0", read_only: true, collected_at: new Date().toISOString(),
    scope: {target: address, transport: "browser_receive_only", observer: "Navegador do notebook"},
    checks: {websocket: {status: "connecting", connected: false, frames, messages: 0, malformed: 0, elapsed_seconds: 0,
      successful_encoder_read_hz: null, rtu_latency_ms: null}},
    limitations: ["Qualidade individual depende dos metadados do backend; versões antigas não os publicam.", "Sem payload de aplicação enviado. Sem acesso direto à serial.", "Uma entrada 0/1 não certifica o estado físico; polaridade e Ladder ainda precisam de validação."]};
  byId("connect").disabled = true; byId("stop").disabled = false; byId("save").disabled = true;
  byId("live-status").textContent = "Conectando ao serviço de estados…"; event("Tentativa de conexão iniciada");
  try { socket = new WebSocket(`ws://${address}:${port}/`); }
  catch (error) { finish("error", `Conexão indisponível: ${error.message}`); return; }
  connectTimer = setTimeout(() => { if (run === generation) finish("timeout", "Servidor não completou a conexão em 4 s."); }, 4000);
  socket.onopen = () => {
    if (run !== generation) return;
    clearTimeout(connectTimer); report.checks.websocket.connected = true; report.checks.websocket.status = "connected";
    byId("live-status").textContent = "Conectado. Aguardando estados publicados pela IHM."; event("WebSocket conectado");
    stopTimer = setTimeout(() => { if (run === generation) finish("observation_complete", "Observação encerrada no tempo previsto. Exporte a coleta."); }, seconds * 1000);
  };
  socket.onmessage = received => {
    if (run !== generation) return;
    if (typeof received.data !== "string") { report.checks.websocket.malformed++; return; }
    // The browser allocates the frame before this handler; the limits bound retained data.
    const size = new TextEncoder().encode(received.data).byteLength; bytes += size;
    if (size > 65536 || bytes > 2097152) { finish("byte_limit", "Limite de tamanho da observação atingido."); return; }
    report.checks.websocket.messages++;
    try {
      const message = JSON.parse(received.data);
      if (!message || !["full_state", "state_update"].includes(message.type)) return;
      const data = feedback.sanitize(message.data); if (!data) throw new Error("Formato de estado inválido");
      frames.push({received_at: new Date().toISOString(), elapsed_ms: performance.now() - clockStart, type: message.type, data});
      if (frames.length >= 1000) { finish("sample_limit", "Limite de 1.000 estados atingido. Exporte a coleta."); return; }
      byId("live-status").textContent = "Recebendo estados. Consulte a qualidade e a última leitura de cada sinal."; dirty = true;
    } catch { report.checks.websocket.malformed++; event("Mensagem inválida recebida"); }
  };
  socket.onerror = () => { if (run === generation) finish("error", "Falha de conexão. Confira rede, porta 8765 e eventual permissão de rede local do navegador."); };
  socket.onclose = () => { if (run === generation) finish("closed_by_server", "Servidor encerrou a conexão. Valores preservados como históricos."); };
});
byId("stop").addEventListener("click", () => finish("stopped", "Observação encerrada manualmente. Exporte a coleta."));
byId("save").addEventListener("click", () => {
  if (!report || socket) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], {type: "application/json"}));
  const link = document.createElement("a"); link.href = url; link.download = `neocoude-feedback-${new Date().toISOString().replace(/[:.]/g, "-")}.json`; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
window.addEventListener("beforeunload", () => { if (socket) socket.close(); });
setInterval(draw, 250); draw();
