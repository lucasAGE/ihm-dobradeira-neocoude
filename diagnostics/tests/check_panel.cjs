// Optional browser integration check, using an installed Chromium and CDP pipe.
// Usage: node diagnostics/tests/check_panel.cjs /path/to/chrome [output-directory]
// No package installation, production browser profile or machine network access.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const { spawn, spawnSync } = require("node:child_process");
const http = require("node:http"), crypto = require("node:crypto");
const chrome = process.argv[2];
if (!chrome) throw new Error("Provide the installed Chromium executable");
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), "neocoude-panel-"));
const output = path.resolve(process.argv[3] || path.join(__dirname, "../output"));
fs.mkdirSync(output, {recursive: true});
const child = spawn(chrome, ["--headless", "--remote-debugging-pipe", "--no-first-run", "--no-default-browser-check",
  "--disable-background-networking", "--disable-component-update", `--user-data-dir=${temporary}`],
  {stdio: ["ignore", "ignore", "ignore", "pipe", "pipe"], windowsHide: true});
let sequence = 0, buffer = "", session;
const pending = new Map(), errors = [], requests = [];
let mockServer = null;
let backendFrames = null;
const mockSockets = new Set(), applicationFrames = [];
function packet(text) {
  const body = Buffer.from(text);
  const header = body.length < 126 ? Buffer.from([0x81, body.length]) : Buffer.from([0x81, 126, body.length >> 8, body.length & 255]);
  return Buffer.concat([header, body]);
}
async function startMock() {
  mockServer = http.createServer((_, response) => {response.writeHead(404); response.end();});
  mockServer.on("upgrade", (request, socket) => {
    mockSockets.add(socket); socket.on("close", () => mockSockets.delete(socket)); socket.on("error", () => {});
    const accept = crypto.createHash("sha1").update(request.headers["sec-websocket-key"] + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest("base64");
    socket.write("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: " + accept + "\r\n\r\n");
    if (backendFrames) {
      for (const frame of backendFrames.slice(0, 3)) socket.write(packet(JSON.stringify(frame)));
    } else {
    socket.write(packet(JSON.stringify({type: "full_state", data: {encoder_raw: 399, encoder_degrees: 179.55,
      inputs: {E0: false, E5: true, E6: true}, outputs: {S0: false}, poll_count: 10}})));
    socket.write(packet("invalid json"));
    socket.write(packet(JSON.stringify({type: "state_update", data: {encoder_raw: 400, encoder_degrees: 0, inputs: {E0: true, E5: null}, poll_count: 11}})));
    }
    let incoming = Buffer.alloc(0);
    socket.on("data", chunk => {
      incoming = Buffer.concat([incoming, chunk]);
      while (incoming.length >= 2) {
        const opcode = incoming[0] & 15; let length = incoming[1] & 127, offset = 2;
        if (length === 126) {if (incoming.length < 4) return; length = incoming.readUInt16BE(2); offset = 4;}
        if (length === 127) {if (incoming.length < 10) return; length = Number(incoming.readBigUInt64BE(2)); offset = 10;}
        if (incoming[1] & 128) offset += 4;
        if (incoming.length < offset + length) return;
        incoming = incoming.subarray(offset + length);
        if (opcode === 1 || opcode === 2) applicationFrames.push(opcode);
        if (opcode === 8) {socket.end(Buffer.from([0x88, 0])); return;}
      }
    });
  });
  await new Promise(resolve => mockServer.listen(0, "127.0.0.1", resolve));
  return mockServer.address().port;
}
child.stdio[4].on("data", chunk => {
  buffer += chunk.toString();
  let end;
  while ((end = buffer.indexOf("\0")) >= 0) {
    const message = JSON.parse(buffer.slice(0, end)); buffer = buffer.slice(end + 1);
    if (message.id && pending.has(message.id)) {
      const {resolve, reject, timer} = pending.get(message.id); clearTimeout(timer); pending.delete(message.id);
      if (message.error) reject(new Error(JSON.stringify(message.error))); else resolve(message.result);
    }
    if (message.method === "Runtime.exceptionThrown") errors.push(message.params);
    if (message.method === "Network.requestWillBeSent") requests.push(message.params.request.url);
  }
});
function call(method, params = {}, targetSession = session) {
  return new Promise((resolve, reject) => {
    const id = ++sequence;
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`Timeout: ${method}`)); }, 10000);
    pending.set(id, {resolve, reject, timer});
    child.stdio[3].write(JSON.stringify({id, method, params, ...(targetSession ? {sessionId: targetSession} : {})}) + "\0");
  });
}
async function evaluate(expression) {
  const result = await call("Runtime.evaluate", {expression, returnByValue: true, awaitPromise: true});
  if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
  return result.result.value;
}
async function until(expression) {
  for (let attempt = 0; attempt < 50; attempt++) {
    if (await evaluate(expression)) return;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error(`Condition not met: ${expression}`);
}
(async () => {
  try {
    const {targetId} = await call("Target.createTarget", {url: "about:blank"}, null);
    session = (await call("Target.attachToTarget", {targetId, flatten: true}, null)).sessionId;
    await call("Runtime.enable"); await call("Page.enable"); await call("Network.enable");
    await call("Emulation.setDeviceMetricsOverride", {width: 1360, height: 1050, deviceScaleFactor: 1, mobile: false});
    await call("Page.navigate", {url: pathToFileURL(path.resolve(__dirname, "../panel/index.html")).href});
    await until("document.querySelectorAll('.card').length === 16");
    assert.equal(await evaluate("document.getElementById('export').disabled"), true);
    const fixture = [
      {schema_version: 1, kind: "linux_snapshot", collected_at: "2026-11-09T12:00:00Z",
        scope: {hostname: "SIMULAÇÃO · sem máquina", is_raspberry_pi: false},
        metrics: {}, checks: {kernel_log: {output: '<img src=x onerror="window.injected=true">'}}},
      {schema_version: 1, kind: "windows_probe", collected_at: "2026-11-09T12:00:00Z", scope: {target: "127.0.0.1 (SIMULAÇÃO)"},
        checks: {websocket: {status: "observation_complete", messages: 2, elapsed_seconds: 1, frames: [
          {type: "full_state", data: {encoder_raw: 311, encoder_degrees: 139.95, modbus_connected: true}},
          {type: "state_update", data: {poll_count: 2}}]}, tcp: [{port: 22, status: "refused"}]}}
    ];
    const fixturePath = path.join(temporary, "fixture.json"); fs.writeFileSync(fixturePath, JSON.stringify(fixture));
    const {root} = await call("DOM.getDocument");
    const {nodeId} = await call("DOM.querySelector", {nodeId: root.nodeId, selector: "#files"});
    await call("DOM.setFileInputFiles", {nodeId, files: [fixturePath]});
    await until("document.getElementById('message').textContent.includes('2 tipos')");
    assert.equal(await evaluate("document.getElementById('export').disabled"), false);
    assert.equal(await evaluate("document.body.textContent.includes('139.95°')"), true);
    assert.equal(await evaluate("document.body.textContent.includes('NÃO identifica um Raspberry Pi')"), true);
    assert.equal(await evaluate("Boolean(window.injected) || document.images.length > 0"), false);
    await call("Browser.setDownloadBehavior", {behavior: "allow", downloadPath: temporary}, null);
    await evaluate("document.getElementById('export').click()");
    let exported;
    for (let attempt = 0; attempt < 40; attempt++) {
      exported = fs.readdirSync(temporary).find(name => /^neocoude-evidencias-.*\.json$/.test(name));
      if (exported) break;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    assert.ok(exported, "Export should produce an offline JSON file");
    assert.equal(JSON.parse(fs.readFileSync(path.join(temporary, exported))).length, 2);
    for (const [width, height, name] of [[1360, 1050, "desktop"], [390, 844, "mobile"]]) {
      await call("Emulation.setDeviceMetricsOverride", {width, height, deviceScaleFactor: 1, mobile: width < 500});
      assert.equal(await evaluate("document.documentElement.scrollWidth <= window.innerWidth"), true);
      const shot = await call("Page.captureScreenshot", {format: "png", captureBeyondViewport: true});
      fs.writeFileSync(path.join(output, `panel-${name}-fixture.png`), Buffer.from(shot.data, "base64"));
    }
    const invalid = path.join(temporary, "invalid.json"); fs.writeFileSync(invalid, '{"kind":"unknown"}');
    await call("DOM.setFileInputFiles", {nodeId, files: [invalid]});
    await until("document.getElementById('message').textContent.includes('formato de relatório desconhecido')");
    assert.equal(errors.length, 0, JSON.stringify(errors));
    assert.equal(requests.some(url => /^https?:|^wss?:/.test(url)), false);
    const mockPort = await startMock();
    await call("Page.navigate", {url: pathToFileURL(path.resolve(__dirname, "../panel/live.html")).href});
    await until("document.querySelectorAll('#signals tbody tr').length > 40");
    const networkBefore = requests.length;
    await evaluate("document.getElementById('address').value='8.8.8.8'; document.getElementById('connect').click()");
    assert.equal(await evaluate("document.getElementById('live-status').textContent.includes('IPv4 local')"), true);
    assert.equal(requests.length, networkBefore);
    await evaluate(`document.getElementById('address').value='127.0.0.1'; document.getElementById('port').value='${mockPort}'; document.getElementById('connect').click()`);
    await until("document.querySelector('[data-signal=\"encoder_raw\"]').textContent.includes('400')");
    assert.equal(await evaluate("document.querySelector('[data-signal=\"inputs.E5\"]').textContent.includes('Inválido')"), true);
    assert.equal(await evaluate("document.querySelector('[data-signal=\"inputs.E7\"]').textContent.includes('Não recebido')"), true);
    await evaluate("document.getElementById('stop').click()");
    await until("document.getElementById('stop').disabled && !document.getElementById('save').disabled");
    await evaluate("document.getElementById('save').click()");
    let liveExport;
    for (let attempt = 0; attempt < 40; attempt++) {
      liveExport = fs.readdirSync(temporary).find(name => /^neocoude-feedback-.*\.json$/.test(name));
      if (liveExport) break;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    assert.ok(liveExport);
    const liveReport = JSON.parse(fs.readFileSync(path.join(temporary, liveExport)));
    assert.equal(liveReport.checks.websocket.malformed, 1);
    assert.equal(liveReport.checks.websocket.frames.length, 2);
    assert.equal(liveReport.checks.websocket.frames[1].data.inputs.E5, null);
    assert.equal(applicationFrames.length, 0, "Observer must never transmit application payloads");
    assert.equal(errors.length, 0, JSON.stringify(errors));
    assert.equal(requests.filter(url => /^https?:|^wss?:/.test(url)).every(url => url === `ws://127.0.0.1:${mockPort}/`), true);
    const liveShot = await call("Page.captureScreenshot", {format: "png", captureBeyondViewport: false});
    fs.writeFileSync(path.join(output, "feedback-live-fixture.png"), Buffer.from(liveShot.data, "base64"));
    // Send actual get_state() output from the corrected class through loopback WS.
    const generated = spawnSync(process.env.PYTHON || "python", ["-c",
      "import asyncio,json; from diagnostics.tests.runtime_fixture import feedback_frames; print(json.dumps(asyncio.run(feedback_frames()),allow_nan=False))"],
      {cwd: path.resolve(__dirname, "../.."), encoding: "utf8", timeout: 15000, windowsHide: true});
    assert.equal(generated.status, 0, generated.stderr);
    backendFrames = JSON.parse(generated.stdout);
    await evaluate("document.getElementById('connect').click()");
    await until("document.querySelector('[data-signal=\"inputs.E6\"]').textContent.includes('Falha de leitura')");
    assert.equal(await evaluate("document.getElementById('live-metrics').textContent.includes('DESCONHECIDO')"), true);
    assert.equal(await evaluate("document.querySelector('[data-signal=\"encoder_raw\"]').textContent.includes('read_failed')"), true);
    const failedShot = await call("Page.captureScreenshot", {format: "png", captureBeyondViewport: true});
    fs.writeFileSync(path.join(output, "feedback-backend-failure.png"), Buffer.from(failedShot.data, "base64"));
    for (const connection of mockSockets) if (!connection.destroyed) connection.write(packet(JSON.stringify(backendFrames[3])));
    await until("document.querySelector('[data-signal=\"inputs.E6\"]').textContent.includes('Leitura OK informada')");
    assert.equal(await evaluate("document.querySelector('[data-signal=\"inputs.E6\"] td:nth-child(2)').textContent"), "0");
    assert.equal(await evaluate("document.querySelector('[data-signal=\"encoder_raw\"] td:nth-child(2)').textContent"), "0");
    await evaluate("document.getElementById('stop').click()");
    const observedBackend = await evaluate("report.checks.websocket.frames");
    assert.equal(observedBackend[2].data.read_quality["inputs.E6"].status, "error");
    assert.equal(observedBackend[3].data.read_quality["inputs.E6"].status, "ok");
    assert.equal(applicationFrames.length, 0);

    // Load the existing HMI with an in-page WebSocket double: no service or PLC.
    await call("Page.addScriptToEvaluateOnNewDocument", {source: `
      window.__hmiSent = [];
      window.WebSocket = class {
        static OPEN=1; static CONNECTING=0; static CLOSED=3;
        constructor() { this.readyState=1; window.__hmiSocket=this; setTimeout(()=>this.onopen?.(),0); }
        send(message) { window.__hmiSent.push(message); }
        close() { this.readyState=3; }
      };`});
    await call("Emulation.setDeviceMetricsOverride", {width: 1360, height: 1050, deviceScaleFactor: 1, mobile: false});
    await call("Page.navigate", {url: pathToFileURL(path.resolve(__dirname, "../../ihm_esp32/static/index.html")).href});
    await until("typeof handleStateUpdate === 'function' && !!window.__hmiSocket?.onmessage");
    assert.equal(await evaluate("document.getElementById('stateName').textContent"), "DESCONHECIDO");
    await evaluate(`window.__hmiSocket.onmessage({data:${JSON.stringify(JSON.stringify(backendFrames[1]))}})`);
    assert.equal(await evaluate("document.getElementById('stateName').textContent"), "PARADA");
    const missing = {type: "state_update", data: {...backendFrames[2].data,
      target_angle: null, velocidade_rpm: null, angles: {bend_1: null, bend_2: null, bend_3: null},
      bend_1_left: null, bend_2_left: null, bend_3_left: null,
      control_bits: {PEDAL_SEGURA: null, MODO_MANUAL: null}, pedal_segura: null, mode_manual: null}};
    await evaluate(`window.__hmiSocket.onmessage({data:${JSON.stringify(JSON.stringify(missing))}})`);
    for (const id of ["encoderValue", "targetAngle", "speedValue", "angle1"])
      assert.equal(await evaluate(`document.getElementById('${id}').textContent`), "Sem leitura");
    assert.equal(await evaluate("document.getElementById('stateName').textContent"), "DESCONHECIDO");
    assert.equal(await evaluate("document.getElementById('manualModeToggle').getAttribute('aria-disabled')"), "true");
    await evaluate("toggleManualMode(); togglePedalSegura()");
    assert.deepEqual(await evaluate("window.__hmiSent"), []);
    const hmiShot = await call("Page.captureScreenshot", {format: "png", captureBeyondViewport: false});
    fs.writeFileSync(path.join(output, "hmi-backend-failure.png"), Buffer.from(hmiShot.data, "base64"));
    await evaluate(`window.__hmiSocket.onmessage({data:${JSON.stringify(JSON.stringify(backendFrames[3]))}})`);
    assert.equal(await evaluate("document.getElementById('encoderValue').textContent"), "0.0°");
    assert.equal(await evaluate("document.getElementById('stateName').textContent"), "PARADA");
    assert.equal(await evaluate("document.getElementById('manualModeToggle').getAttribute('aria-disabled')"), "false");
    assert.equal(errors.length, 0, JSON.stringify(errors));
    assert.equal(requests.filter(url => /^https?:|^wss?:/.test(url)).every(url => url === `ws://127.0.0.1:${mockPort}/`), true);
    console.log("Panel passed: offline import/merge/export, unknowns, inert logs, desktop/mobile; live loopback receive/export, invalid data, local IP restriction, zero transmitted application frames.");
    console.log("Backend feedback passed: actual class snapshots through WS, per-signal read errors, zero/false recovery; existing HMI unknown states, nulls and disabled unknown toggles.");
  } finally {
    for (const connection of mockSockets) connection.destroy();
    if (mockServer) mockServer.close();
    try { await call("Browser.close", {}, null); } catch { child.kill(); }
    // Leave temporary browser profile cleanup to the OS; never traverse user profiles.
    for (const item of pending.values()) clearTimeout(item.timer);
  }
})().catch(error => { console.error(error); child.kill(); process.exitCode = 1; });
