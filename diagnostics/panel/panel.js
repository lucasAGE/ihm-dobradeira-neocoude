"use strict";
// No fetch, WebSocket, application imports or remote assets. Render untrusted logs as text.
const reports = new Map();
const allowedKinds = new Set(["linux_snapshot", "windows_probe", "modbus_capture", "layer_manifest", "usb_inventory"]);
const el = id => document.getElementById(id);
const available = value => value !== null && value !== undefined && value !== "";
const statusLabels = {observation_complete: "Observado", connected: "Conectado", not_collected: "Não coletado",
  refused: "Recusada", open: "Aberta", timeout: "Sem resposta", error: "Erro", closed_by_server: "Servidor encerrou",
  sample_limit: "Limite da amostra", byte_limit: "Limite de dados", message_too_large: "Mensagem excessiva"};
const kindLabels = {linux_snapshot: "Coleta Linux", windows_probe: "Teste Windows", modbus_capture: "Captura Modbus", layer_manifest: "Versões por camada", usb_inventory: "Identificação USB no notebook"};
function display(value, unit = "") {
  return available(value) ? `${value}${unit}` : "Não coletado";
}
function card(parent, label, value, note) {
  const item = document.createElement("article"); item.className = "card";
  for (const [className, text] of [["label", label], ["value", display(value)], ["note", note]]) {
    const part = document.createElement("div"); part.className = className; part.textContent = text; item.appendChild(part);
  }
  parent.appendChild(item);
}
function detail(title, value) {
  const container = document.createElement("details"), summary = document.createElement("summary"), text = document.createElement("pre");
  summary.textContent = title; text.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  container.append(summary, text); el("details").appendChild(container);
}
function mergeState(frames) {
  const summary = globalThis.NeocoudeFeedback.summarize(frames);
  return {encoder_raw: summary.rows.find(row => row.key === "encoder_raw").value,
    encoder_degrees: summary.rows.find(row => row.key === "encoder_degrees").value,
    modbus_connected: summary.modbus_connected};
}
function render() {
  for (const id of ["platform", "communication", "sources", "details"]) el(id).replaceChildren();
  const linux = reports.get("linux_snapshot"), windows = reports.get("windows_probe"), modbus = reports.get("modbus_capture");
  const metrics = linux?.metrics || {}, checks = linux?.checks || {};
  const ws = windows?.checks?.websocket || {}, frames = Array.isArray(ws.frames) ? ws.frames : [];
  const feedbackSummary = globalThis.NeocoudeFeedback.summarize(frames, Number.isFinite(ws.elapsed_seconds) ? ws.elapsed_seconds * 1000 : null);
  const state = mergeState(frames);
  if (!reports.size) { const p = document.createElement("p"); p.textContent = "Sem dados da instalação real."; el("sources").appendChild(p); }
  for (const [kind, report] of reports) {
    const p = document.createElement("p");
    const age = Date.now() - Date.parse(report.collected_at);
    p.textContent = `${kindLabels[kind]} · ${report.collected_at || "data desconhecida"} · ${report.scope?.hostname || report.scope?.observer || report.scope?.target || "artefato local"} · ${Number.isFinite(age) && age < 0 ? "relógio à frente; conferir sincronização" : "coleta arquivada, sem atualização ao vivo"}`;
    el("sources").appendChild(p);
  }
  if (linux && !linux.scope?.is_raspberry_pi) {
    const p = document.createElement("p"); p.textContent = "A coleta Linux importada NÃO identifica um Raspberry Pi. Não representa aprovação do equipamento."; el("sources").appendChild(p);
  }
  const platform = el("platform");
  card(platform, "Modelo observado", metrics.model, "Device Tree da instalação coletada");
  card(platform, "Temperatura CPU", display(metrics.cpu_temperature_c, " °C"), "Sensor thermal_zone0; confirmar hardware");
  card(platform, "CPU utilizada", display(metrics.cpu_used_percent, " %"), "Amostra curta, sem teste de estresse");
  card(platform, "Memória utilizada", display(metrics.memory_used_percent, " %"), `${display(metrics.memory_total_mib, " MiB")} totais`);
  card(platform, "Armazenamento /", display(metrics.root_used_percent, " %"), `${display(metrics.root_free_gib, " GiB")} livres; integridade não certificada`);
  card(platform, "Frequência CPU", display(metrics.cpu_frequency_mhz, " MHz"), "Frequência instantânea observada");
  const flags = metrics.power_throttling?.flags;
  card(platform, "Alimentação / throttling", flags ? (Object.values(flags).some(Boolean) ? "Há flags registradas" : "Flags zeradas") : null, "Não substitui medição da alimentação");
  card(platform, "Linux instalado", checks.os_release?.output?.match(/^PRETTY_NAME=["']?([^\n"']+)/m)?.[1], "Versão coletada no alvo");
  const comm = el("communication");
  card(comm, "Encoder bruto", state.encoder_raw, "Último valor recebido; pode estar obsoleto");
  card(comm, "Ângulo informado", display(state.encoder_degrees, "°"), "Conversão do backend; não calibrada por esta ferramenta");
  card(comm, "Modbus informado", available(state.modbus_connected) ? (state.modbus_connected ? "Conectado" : "Desconectado") : null, "Flag do backend; não comprova uma leitura recente");
  card(comm, "WebSocket observado", statusLabels[ws.status] || ws.status, `${display(ws.messages)} mensagens em ${display(ws.elapsed_seconds, " s")}`);
  card(comm, "Leituras RTU capturadas", display(modbus?.statistics?.successful_read_hz?.toFixed(2), " Hz"), "Capturas FC01/02/03/04 válidas; não é taxa do encoder");
  card(comm, "Latência RTU p95", display(modbus?.statistics?.latency_p95_ms, " ms"), "Medida na captura pareada, nunca inferida do WebSocket");
  card(comm, "Leituras OK do encoder", display(feedbackSummary.successful_encoder_read_hz?.toFixed(2), " Hz"), "Contador do backend corrigido; indisponível no legado");
  const sshStatus = windows?.checks?.tcp?.find(item => item.port === 22)?.status;
  card(comm, "SSH / porta 22", statusLabels[sshStatus] || sshStatus, "Recusada: verificar serviço, listener e firewall no alvo");
  globalThis.NeocoudeFeedback.renderTable(el("signals"), feedbackSummary);
  if (windows) detail("Frequência de mensagens e presença dos sinais", feedbackSummary);
  if (linux) {
    detail("Serviços Linux e reinicializações", {services: checks.service_details, failed: checks.services_failed, boots: checks.boot_history, shutdowns: checks.shutdown_history});
    detail("Rede, Wi-Fi e USB", {network: checks.network, wifi: checks.wifi_interfaces, stations: checks.wlan0_stations, rfkill: checks.rfkill, usb: checks.usb, serial: checks.serial_devices, owners: checks.serial_owners});
    detail("Histórico de falhas e logs", {kernel: checks.kernel_log, previous_boot: checks.previous_boot, boot_errors: checks.boot_errors, services: checks.service_logs});
    detail("Aplicação, dependências e firmware", {application: linux.application, python: checks.python_packages, firmware: checks.firmware, power: metrics.power_throttling});
    detail("Limites da coleta Linux", linux.limitations);
  }
  if (windows) detail("Coleta Windows e mensagens recebidas", windows);
  if (modbus) detail("Integridade e estatísticas da captura Modbus", modbus);
  if (reports.has("usb_inventory")) detail("Portas, USB e adaptadores do notebook (sem leitura de sensores)", reports.get("usb_inventory"));
  if (reports.has("layer_manifest")) detail("Versionamento por camada e comparação com a instalação", reports.get("layer_manifest"));
  el("export").disabled = reports.size === 0;
}
el("files").addEventListener("change", async event => {
  const errors = [];
  for (const file of Array.from(event.target.files).slice(0, 8)) {
    try {
      if (file.size > 10 * 1024 * 1024) throw new Error("arquivo maior que 10 MiB");
      const decoded = JSON.parse(await file.text());
      const batch = Array.isArray(decoded) ? decoded : [decoded];
      if (batch.length > 5) throw new Error("máximo de cinco tipos de relatório");
      for (const report of batch) {
        if (!report || report.schema_version !== 1 || !allowedKinds.has(report.kind)) throw new Error("formato de relatório desconhecido");
        // Keep the latest snapshot for each layer, independent of file selection order.
        const previous = reports.get(report.kind);
        if (!previous || Date.parse(report.collected_at) >= Date.parse(previous.collected_at)) reports.set(report.kind, report);
      }
    } catch (error) { errors.push(`${file.name}: ${error.message}`); }
  }
  try { render(); } catch (error) { errors.push(`Estrutura de relatório inválida: ${error.message}`); }
  el("message").textContent = errors.length ? errors.join(" · ") : `${reports.size} tipos de evidência importados. Nenhuma verificação física ou operacional foi aprovada.`;
});
el("export").addEventListener("click", () => {
  const url = URL.createObjectURL(new Blob([JSON.stringify(Array.from(reports.values()), null, 2)], {type: "application/json"}));
  const link = document.createElement("a"); link.href = url; link.download = `neocoude-evidencias-${new Date().toISOString().replace(/[:.]/g, "-")}.json`; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
render();
