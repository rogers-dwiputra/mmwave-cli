import re
import ast

# Regex sederhana untuk menangkap assignment seperti:  name = value
ASSIGN_RE = re.compile(r'^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*([^-\n]+)')

def parse_lua_assignments(lua_path):
    """
    Membaca file .lua mmWave Studio dan mengambil parameter fisik
    seperti start_freq, slope, idle_time, adc_samples, dll.
    """
    params = {}

    with open(lua_path, "r") as f:
        for line in f:
            m = ASSIGN_RE.match(line)
            if not m:
                continue

            key = m.group(1).strip()
            val = m.group(2).strip()

            # Buang koma atau komentar
            val = val.split('--')[0].strip()
            val = val.rstrip(',')

            # Convert angka ke float/int Python
            try:
                val_py = ast.literal_eval(val)
            except Exception:
                continue

            params[key] = val_py

    return params


def convert_physical_to_lsb(params):
    """
    Konversi parameter fisik (GHz, MHz/us, us) dari Lua
    ke LSB sesuai DFP yang digunakan mimo.py.
    """
    p = {}

    # ====== PROFILE CONFIG ======
    # Konversi sesuai rumus mimo.py:
    #   startFreq_GHz = startFreqConst * 53.6441803 / 1e9
    #   freqSlope_MHz_us = freqSlopeConst * 48.2797623 / 1000

    if "start_freq" in params:
        p["startFreqConst"] = int(params["start_freq"] * 1e9 / 53.6441803)

    if "slope" in params:
        p["freqSlopeConst"] = int(params["slope"] * 1000 / 48.2797623)

    if "idle_time" in params:
        p["idleTimeConst"] = int(params["idle_time"] / 0.01)

    if "adc_start_time" in params:
        p["adcStartTimeConst"] = int(params["adc_start_time"] / 0.01)

    if "ramp_end_time" in params:
        p["rampEndTime"] = int(params["ramp_end_time"] / 0.01)

    if "adc_samples" in params:
        p["numAdcSamples"] = int(params["adc_samples"])

    if "sample_freq" in params:
        p["digOutSampleRate"] = int(params["sample_freq"])  # ksps

    if "rx_gain" in params:
        p["rxGain"] = int(params["rx_gain"])

    # ====== FRAME CONFIG ======
    if "start_chirp_tx" in params:
        p["chirpStartIdx"] = int(params["start_chirp_tx"])

    if "end_chirp_tx" in params:
        p["chirpEndIdx"] = int(params["end_chirp_tx"])

    if "nchirp_loops" in params:
        p["numLoops"] = int(params["nchirp_loops"])

    if "nframes_master" in params:
        p["numFrames"] = int(params["nframes_master"])

    if "Inter_Frame_Interval" in params:
        # ms → LSB. Rumus di mimo.c: framePeriodicity_msec = (framePeriodicity * 5.0) / 1e6
        # Maka, LSB = msec * 1e6 / 5.0
        p["framePeriodicity"] = int(params["Inter_Frame_Interval"] * 1e6 / 5.0)

    return p