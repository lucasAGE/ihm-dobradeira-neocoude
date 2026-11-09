const assert = require("node:assert/strict");
const {test} = require("node:test");
const feedback = require("../panel/feedback.js");
const {spawnSync} = require("node:child_process");
const path = require("node:path");
const frame = (time, data, type = "state_update") => ({elapsed_ms: time, received_at: `test-${time}`, type, data});
const row = (summary, key) => summary.rows.find(item => item.key === key);

test("zero and false remain observations, while missing signals remain unknown", () => {
  const s = feedback.summarize([frame(0, {encoder_raw: 0, inputs: {E0: false, E6: true}}, "full_state")]);
  assert.equal(row(s, "encoder_raw").value, 0); assert.equal(feedback.format(row(s, "inputs.E0")), "0");
  assert.equal(row(s, "inputs.E7").quality, "missing");
  assert.equal(row(s, "inputs.E6").quality, "backend_unverified");
  assert.equal(s.successful_encoder_read_hz, null);
});
test("partial nested updates preserve other inputs but an explicit null invalidates", () => {
  const s = feedback.summarize([frame(0, {inputs: {E0: false, E6: true}}, "full_state"),
    frame(500, {inputs: {E0: true}}), frame(1000, {inputs: {E6: null}})], 1500);
  assert.equal(row(s, "inputs.E0").changes, 1);
  assert.equal(row(s, "inputs.E0").since_field_received_ms, 1000);
  assert.equal(row(s, "inputs.E6").quality, "invalid");
  assert.equal(row(s, "inputs.E6").value, null); assert.equal(row(s, "inputs.E6").last_good_value, true);
});
test("a new full snapshot clears values missing from that snapshot", () => {
  const s = feedback.summarize([frame(0, {encoder_raw: 200, inputs: {E6: true}}, "full_state"), frame(100, {}, "full_state")]);
  assert.equal(row(s, "encoder_raw").value, null); assert.equal(row(s, "inputs.E6").quality, "missing");
});
test("false-like strings, objects, out-of-range raw values and nonfinite numbers are not measurements", () => {
  const s = feedback.summarize([frame(0, {encoder_raw: 65536, encoder_degrees: Infinity, inputs: {E0: "false", E6: {active: true}}})]);
  for (const key of ["encoder_raw", "encoder_degrees", "inputs.E0", "inputs.E6"]) assert.equal(row(s, key).value, null);
});
test("a malformed group invalidates old values instead of silently preserving them", () => {
  for (const malformed of ["broken", false, 0, [], null]) {
    const s = feedback.summarize([frame(0, {inputs: {E6: true}}, "full_state"), frame(100, {inputs: malformed})]);
    assert.equal(row(s, "inputs.E6").value, null);
    assert.equal(row(s, "inputs.E6").quality, "invalid");
    assert.equal(row(s, "inputs.E6").last_good_value, true);
  }
});
test("message frequency, attempted polling, successful reads and RTT remain distinct", () => {
  const s = feedback.summarize([frame(0, {poll_count: 10, encoder_raw: 123}), frame(1000, {poll_count: 14, heartbeat: true}),
    frame(2000, {poll_count: 18})], 3000);
  assert.equal(s.message_hz, 1); assert.equal(s.poll_attempt_hz, 4);
  assert.equal(s.successful_encoder_read_hz, null); assert.equal(s.rtu_latency_ms, null);
  assert.equal(row(s, "encoder_raw").updates, 1); assert.equal(row(s, "encoder_raw").since_field_received_ms, 3000);
  assert.equal(s.silence_ms, 1000); assert.equal(s.max_message_gap_ms, 1000);
});
test("poll counter reset and clock regression suppress misleading rates", () => {
  const reset = feedback.summarize([frame(0, {poll_count: 99}), frame(1000, {poll_count: 1})]);
  assert.equal(reset.poll_resets, 1); assert.equal(reset.poll_attempt_hz, null);
  const backwards = feedback.summarize([frame(1000, {encoder_raw: 1}), frame(500, {encoder_raw: 2})]);
  assert.equal(backwards.timing_errors, 1); assert.equal(backwards.message_hz, null);
  assert.equal(feedback.summarize([frame(0, {}), {type: "state_update", data: {}}, frame(1000, {})]).message_hz, null);
});
test("missing or regressive timestamps cannot produce zero gaps or a claimed silence duration", () => {
  for (const frames of [
    [{type: "full_state", data: {}}, {type: "state_update", data: {}}],
    [frame(0, {}), {type: "state_update", data: {}}],
    [frame(1000, {}), frame(500, {})]
  ]) {
    const s = feedback.summarize(frames, 2000);
    assert.equal(s.max_message_gap_ms, null);
    assert.equal(s.silence_ms, null);
  }
});
test("encoder wrap in the UI never erases the raw counter history", () => {
  const s = feedback.summarize([frame(0, {encoder_raw: 399, encoder_degrees: 179.55}), frame(100, {encoder_raw: 400, encoder_degrees: 0})]);
  assert.deepEqual(s.encoder_series.map(p => p.value), [399, 400]); assert.equal(row(s, "encoder_degrees").value, 0);
});
test("unknown fields and prototype keys cannot enter the signal model", () => {
  const safe = feedback.sanitize(JSON.parse('{"__proto__":{"polluted":true},"password":"secret","inputs":{"E0":true,"constructor":"bad"}}'));
  assert.deepEqual(safe, {inputs: {E0: true}}); assert.equal({}.polluted, undefined);
});
const quality = (status, count, errorCount = 0) => ({status, success_count: count, error_count: errorCount,
  last_attempt_at: "2026-11-09T12:00:01+00:00", last_success_at: "2026-11-09T12:00:00+00:00", last_error: status === "error" ? "read_failed" : null});
test("backend quality preserves legitimate false and nulls an explicitly failed observation", () => {
  const frames = [frame(0, {inputs: {E6: false}, read_quality: {"inputs.E6": quality("ok", 1)}}, "full_state")];
  assert.equal(row(feedback.summarize(frames), "inputs.E6").quality, "backend_read_ok");
  frames.push(frame(100, {read_quality: {"inputs.E6": quality("error", 1, 1)}}));
  const failed = row(feedback.summarize(frames), "inputs.E6");
  assert.equal(failed.value, null); assert.equal(failed.quality, "read_error");
  assert.equal(feedback.format(failed), "Falha de leitura");
  frames.push(frame(200, {inputs: {E6: false}, read_quality: {"inputs.E6": quality("ok", 2, 1)}}));
  assert.equal(row(feedback.summarize(frames), "inputs.E6").value, false);
});
test("successful encoder rate counts successes and is suppressed on backend restart", () => {
  const frames = [frame(0, {feedback_session: "a", read_quality: {encoder_raw: quality("ok", 10)}}),
    frame(1000, {read_quality: {encoder_raw: quality("error", 10, 1)}}),
    frame(2000, {read_quality: {encoder_raw: quality("ok", 12, 1)}})];
  const s = feedback.summarize(frames);
  assert.equal(s.successful_encoder_read_hz, 1); assert.equal(s.encoder_error_count, 1);
  frames.push(frame(3000, {feedback_session: "b", read_quality: {encoder_raw: quality("ok", 20)}}));
  assert.equal(feedback.summarize(frames).successful_encoder_read_hz, null);
});
test("new full snapshot removes old read-quality metadata", () => {
  const s = feedback.summarize([frame(0, {encoder_raw: 1, read_quality: {encoder_raw: quality("ok", 1)}}, "full_state"),
    frame(1000, {encoder_raw: 2}, "full_state")]);
  assert.equal(row(s, "encoder_raw").quality, "backend_unverified");
  assert.equal(s.successful_encoder_read_hz, null);
});
test("actual backend JSON survives successful read, failure and recovery in the monitor", () => {
  const produced = spawnSync(process.env.PYTHON || "python", ["-c",
    "import asyncio,json; from diagnostics.tests.runtime_fixture import feedback_frames; print(json.dumps(asyncio.run(feedback_frames()),allow_nan=False))"],
    {cwd: path.resolve(__dirname, "../.."), encoding: "utf8", windowsHide: true, timeout: 15000});
  assert.equal(produced.status, 0, produced.stderr);
  const frames = JSON.parse(produced.stdout);
  const failed = feedback.summarize(frames.slice(0, 3));
  assert.equal(row(failed, "inputs.E6").value, null);
  assert.equal(row(failed, "inputs.E6").quality, "read_error");
  assert.equal(row(failed, "encoder_degrees").value, null);
  assert.equal(failed.machine_state_name, "DESCONHECIDO");
  const recovered = feedback.summarize(frames);
  assert.equal(row(recovered, "inputs.E6").value, false);
  assert.equal(row(recovered, "inputs.E6").quality, "backend_read_ok");
  assert.equal(row(recovered, "encoder_raw").value, 0);
  assert.equal(recovered.encoder_success_count, 2);
  assert.equal(recovered.encoder_error_count, 1);
});
