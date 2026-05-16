// TTN Uplink Formatter — gb-sar-01 / iosar-imrsl
// Paste this into TTN Console > Applications > iosar-imrsl > Payload formatters > Uplink
// Decodes 10-byte big-endian payload from lora_sender.py
// temperature_c is a static placeholder until hardware sensor is available

function decodeUplink(input) {
  var b = input.bytes;
  if (b.length < 10) {
    return { errors: ["payload too short, expected 10 bytes, got " + b.length] };
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

  return {
    data: {
      timestamp_unix:        ts,
      timestamp_iso:         iso,
      dominant_frequency_hz: freq_hz,
      displacement_rms_mm:   disp_rms_mm,
      displacement_rms_um:   Math.round(disp_rms_mm * 1000),
      max_deflection_mm:     max_defl_mm,
      max_deflection_um:     Math.round(max_defl_mm * 1000),
      temperature_c:         22.0,   // static placeholder — replace with sensor value later
      latitude:              43.8156,
      longitude:             140.9723
    }
  };
}
