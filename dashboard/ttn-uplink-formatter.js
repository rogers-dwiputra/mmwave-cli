// TTN Uplink Formatter — gb-sar-01 / iosar-imrsl
// Paste this into TTN Console > Applications > iosar-imrsl > Payload formatters > Uplink
// Decodes variable-length big-endian payload from lora_sender.py
//
// Payload layout:
//   Byte 0-3  : Unix timestamp (uint32)
//   Byte 4-5  : dominant_frequency_hz × 100 (uint16, 0 = no peak / below the
//               amplitude+coherence gate -- decoded to `null`, not 0)
//   Byte 6-7  : dominant_frequency_hz_2 × 100 (uint16, 0 = no 2nd peak --
//               decoded to `null`. Up to 2 local-maxima peaks that each
//               independently clear both gates are reported, e.g. a
//               spectrum with two real modes above 4 um; see
//               SPEC_vibration_threshold_NaN.md)
//   Byte 8-9  : displacement_rms_mm × 1000 (uint16)
//   Byte 10-11: max_deflection_mm × 1000 (uint16)
//   Byte 12   : N_PS count (uint8) — number of PS points
//   Bytes 13+ : Per-PS data, 4 bytes each (single peak per PS):
//                 uint16 : ps_i freq × 100   (0 = no peak -- decoded to `null`)
//                 uint16 : ps_i rms_mm × 1000
//   Byte 13+4×N_PS : N_PHASE count (uint8) — number of fixed phase-eval
//                     points (0 unless --lora-phase-eval-file was set; see
//                     ps_monitoring._compute_phase_eval). Sensei's hand-picked
//                     7 reference + 5 bridge-target points, for offline APS
//                     evaluation only -- InfluxDB storage only, intentionally
//                     NOT wired into any Grafana panel.
//   Bytes 14+4×N_PS+ : Per-point coherent-mean phase, 2 bytes each:
//                 int16 : phase_rad × 1000 (signed, milliradians)
//   Byte 14+4×N_PS+2×N_PHASE : module_temp_c (int8, signed) — Wio-E5
//                     internal MCU temp via AT+TEMP, present only when a
//                     live session was open at send time. Diagnostic only
//                     (self-heating biased).

function decodeUplink(input) {
  var b = input.bytes;
  if (b.length < 12) {
    return { errors: ["payload too short, expected ≥12 bytes, got " + b.length] };
  }

  var ts         = ((b[0] << 24) >>> 0) | (b[1] << 16) | (b[2] << 8) | b[3];
  var freq_raw   = (b[4] << 8) | b[5];
  var freq2_raw  = (b[6] << 8) | b[7];
  var rms_raw    = (b[8] << 8) | b[9];
  var defl_raw   = (b[10] << 8) | b[11];

  // 0 is the "no peak / below the amplitude+coherence gate" sentinel
  // (SPEC_vibration_threshold_NaN.md) -- decode it to null so a Grafana
  // panel with "Connect null values: Never" draws a real gap instead of
  // dipping to a spurious 0 Hz.
  var freq_hz        = freq_raw  === 0 ? null : freq_raw  / 100.0;
  var freq2_hz       = freq2_raw === 0 ? null : freq2_raw / 100.0;
  var disp_rms_mm    = rms_raw   / 1000.0;
  var max_defl_mm    = defl_raw  / 1000.0;

  var d   = new Date(ts * 1000);
  var iso = d.toISOString();

  var out = {
    timestamp_unix:          ts,
    timestamp_iso:           iso,
    dominant_frequency_hz:   freq_hz,
    dominant_frequency_hz_2: freq2_hz,
    displacement_rms_mm:     disp_rms_mm,
    displacement_rms_um:     Math.round(disp_rms_mm * 1000),
    max_deflection_mm:       max_defl_mm,
    max_deflection_um:       Math.round(max_defl_mm * 1000),
    temperature_c:           null,   // filled in below when the trailing byte is present
    latitude:                43.8156,
    longitude:               140.9723,
    n_ps:                    0,
    n_phase:                 0
  };

  // ── Per-PS section (byte 12+) ─────────────────────────────────────────────
  if (b.length > 12) {
    var n_ps = b[12];
    out.n_ps = n_ps;

    for (var i = 0; i < n_ps; i++) {
      var offset = 13 + i * 4;
      if (offset + 3 >= b.length) break;   // guard against truncated payload

      var ps_freq_raw = (b[offset]     << 8) | b[offset + 1];
      var ps_rms_raw  = (b[offset + 2] << 8) | b[offset + 3];

      var ps_freq_hz = ps_freq_raw === 0 ? null : ps_freq_raw / 100.0;
      var ps_rms_mm  = ps_rms_raw  / 1000.0;

      out["freq_ps" + i]    = ps_freq_hz;
      out["rms_ps" + i]     = ps_rms_mm;
      out["rms_um_ps" + i]  = Math.round(ps_rms_mm * 1000);
    }

    // ── Phase-eval section (fixed points, offline APS evaluation only --
    // InfluxDB storage only, deliberately not surfaced on any Grafana panel) ──
    var phaseOffset = 13 + n_ps * 4;
    var n_phase = 0;
    if (b.length > phaseOffset) {
      n_phase = b[phaseOffset];
      out.n_phase = n_phase;

      for (var j = 0; j < n_phase; j++) {
        var pOffset = phaseOffset + 1 + j * 2;
        if (pOffset + 1 >= b.length) break;   // guard against truncated payload

        var rawPhase = (b[pOffset] << 8) | b[pOffset + 1];
        if (rawPhase > 32767) rawPhase -= 65536;   // int16 sign extend
        out["phase_rad_" + j] = rawPhase / 1000.0;
      }
    }

    // ── Trailing module temperature byte (signed int8) ────────────────────
    var tempOffset = phaseOffset + 1 + n_phase * 2;
    if (b.length > tempOffset) {
      var rawTemp = b[tempOffset];
      out.temperature_c = rawTemp > 127 ? rawTemp - 256 : rawTemp;
    }
  }

  return { data: out };
}
