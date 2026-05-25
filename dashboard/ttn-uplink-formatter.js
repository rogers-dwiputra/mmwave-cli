// TTN Uplink Formatter — gb-sar-01 / iosar-imrsl
// Paste this into TTN Console > Applications > iosar-imrsl > Payload formatters > Uplink
// Decodes variable-length big-endian payload from lora_sender.py
//
// Payload layout:
//   Byte 0-3  : Unix timestamp (uint32)
//   Byte 4-5  : dominant_frequency_hz × 100 (uint16)
//   Byte 6-7  : displacement_rms_mm × 1000 (uint16)
//   Byte 8-9  : max_deflection_mm × 1000 (uint16)
//   Byte 10   : N_PS count (uint8) — number of PS points
//   Bytes 11+ : Per-PS data, 4 bytes each:
//                 uint16 : ps_i freq × 100   (0 = no peak detected)
//                 uint16 : ps_i rms_mm × 1000
//
// temperature_c is a static placeholder until hardware sensor is available

function decodeUplink(input) {
  var b = input.bytes;
  if (b.length < 10) {
    return { errors: ["payload too short, expected ≥10 bytes, got " + b.length] };
  }

  var ts         = ((b[0] << 24) >>> 0) | (b[1] << 16) | (b[2] << 8) | b[3];
  var freq_raw   = (b[4] << 8) | b[5];
  var rms_raw    = (b[6] << 8) | b[7];
  var defl_raw   = (b[8] << 8) | b[9];

  var freq_hz        = freq_raw  / 100.0;
  var disp_rms_mm    = rms_raw   / 1000.0;
  var max_defl_mm    = defl_raw  / 1000.0;

  var d   = new Date(ts * 1000);
  var iso = d.toISOString();

  var out = {
    timestamp_unix:        ts,
    timestamp_iso:         iso,
    dominant_frequency_hz: freq_hz,
    displacement_rms_mm:   disp_rms_mm,
    displacement_rms_um:   Math.round(disp_rms_mm * 1000),
    max_deflection_mm:     max_defl_mm,
    max_deflection_um:     Math.round(max_defl_mm * 1000),
    temperature_c:         22.0,   // static placeholder — replace with sensor value later
    latitude:              43.8156,
    longitude:             140.9723,
    n_ps:                  0
  };

  // ── Per-PS section (byte 10+) ─────────────────────────────────────────────
  if (b.length > 10) {
    var n_ps = b[10];
    out.n_ps = n_ps;

    for (var i = 0; i < n_ps; i++) {
      var offset = 11 + i * 4;
      if (offset + 3 >= b.length) break;   // guard against truncated payload

      var ps_freq_raw = (b[offset]     << 8) | b[offset + 1];
      var ps_rms_raw  = (b[offset + 2] << 8) | b[offset + 3];

      var ps_freq_hz = ps_freq_raw / 100.0;   // 0.0 = no peak detected
      var ps_rms_mm  = ps_rms_raw  / 1000.0;

      out["freq_ps" + i]    = ps_freq_hz;
      out["rms_ps" + i]     = ps_rms_mm;
      out["rms_um_ps" + i]  = Math.round(ps_rms_mm * 1000);
    }
  }

  return { data: out };
}
