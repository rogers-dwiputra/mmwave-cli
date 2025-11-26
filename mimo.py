import time
import mmwcas
import argparse
import subprocess
import threading
import sys
import json
from datetime import datetime
import os
from lua_loader import parse_lua_assignments, convert_physical_to_lsb
import copy

# --- Konfigurasi Default (dapat diubah melalui argumen CLI) ---
DEFAULT_REMOTE_USER = "root"
DEFAULT_REMOTE_IP = "192.168.33.180"
DEFAULT_REMOTE_BASE_PATH = "/mnt/ssd"
DEFAULT_LOCAL_DEST_PATH = "~/mmwave-cli/PostProc/"

# --- Konfigurasi Radar Default (diterjemahkan dari mimo.c) ---
# Ini akan digunakan jika tidak ada file .lua yang disediakan
default_radar_config = {
    "profileCfg": {
        "profileId": 0, "pfVcoSelect": 0x02, "startFreqConst": 1434000000,
        "freqSlopeConst": 518, "idleTimeConst": 700, "adcStartTimeConst": 435,
        "rampEndTime": 6897, "txOutPowerBackoffCode": 0x0, "txPhaseShifter": 0x0,
        "txStartTime": 0x0, "numAdcSamples": 512, "digOutSampleRate": 8000,
        "hpfCornerFreq1": 0x0, "hpfCornerFreq2": 0x0, "rxGain": 48,
    },
    "frameCfg": {
        "chirpStartIdx": 0, "chirpEndIdx": 11, "numFrames": 0, "numLoops": 10,
        "numAdcSamples": 512, "frameTriggerDelay": 0x0, "framePeriodicity": 20000000,
    },
    "channelCfg": {"rxChannelEn": 0x0F, "txChannelEn": 0x07, "cascading": 0x02},
    "adcOutCfg": {"fmt": {"b2AdcBits": 2, "b2AdcOutFmt": 1, "b8FullScaleReducFctr": 0}},
    "dataFmtCfg": {"iqSwapSel": 0, "chInterleave": 0, "rxChannelEn": 0xF, "adcFmt": 1, "adcBits": 2},
    "ldoCfg": {"ldoBypassEnable": 3, "ioSupplyIndicator": 0, "supplyMonIrDrop": 0},
    "lpmCfg": {"lpAdcMode": 0},
    "miscCfg": {"miscCtl": 1},
    "datapathCfg": {"intfSel": 0, "transferFmtPkt0": 1, "transferFmtPkt1": 0},
    "datapathClkCfg": {"laneClkCfg": 1, "dataRate": 1},
    "hsClkCfg": {"hsiClk": 0x09},
    "csi2LaneCfg": {"lineStartEndDis": 0, "lanePosPolSel": 0x35421},
}

def export_config_to_json(config, filename, num_devices=4):
    """
    Membuat file mmwave.json dari dictionary konfigurasi radar.
    Versi ini diformat ulang agar mudah dibaca dan memiliki struktur yang benar.
    """
    print(f"  > Membuat file konfigurasi JSON: {filename}")
    
    p_cfg = config['profileCfg']
    f_cfg = config['frameCfg']
    
    startFreq_GHz = (p_cfg['startFreqConst'] * 53.6441803) / 1e9
    freqSlope_MHz_usec = (p_cfg['freqSlopeConst'] * 48.2797623) / 1000.0
    idleTime_usec = p_cfg['idleTimeConst'] * 0.01
    adcStartTime_usec = p_cfg['adcStartTimeConst'] * 0.01
    rampEndTime_usec = p_cfg['rampEndTime'] * 0.01
    txStartTime_usec = p_cfg['txStartTime'] * 0.01
    framePeriodicity_msec = (f_cfg['framePeriodicity'] * 5.0) / 1e6

    json_output = {
        "configGenerator": {
            "createdBy": "mmwave-cli-python",
            "createdOn": datetime.now().astimezone().isoformat(),
            "isConfigIntermediate": 1
        },
        "mmWaveDevices": []
    }

    for devId in range(num_devices):
        chirp_tx_table = {0: {11, 10, 9}, 1: {8, 7, 6}, 2: {5, 4, 3}, 3: {2, 1, 0}}
        chirps = []
        for chirpIdx in range(12):
            tx_enable = 0
            if chirpIdx in chirp_tx_table.get(devId, set()):
                tx_map = {val: idx for idx, val in enumerate(sorted(list(chirp_tx_table[devId]), reverse=True))}
                tx_enable = 1 << tx_map[chirpIdx]
            chirps.append({
                "rlChirpCfg_t": {
                    "chirpStartIdx": chirpIdx, "chirpEndIdx": chirpIdx, "profileId": 0,
                    "startFreqVar_MHz": 0.0, "freqSlopeVar_KHz_usec": 0.0,
                    "idleTimeVar_usec": 0.0, "adcStartTimeVar_usec": 0.0,
                    "txEnable": f"0x{tx_enable:X}"
                }
            })

        device_config = {
            "mmWaveDeviceId": devId,
            "rfConfig": {
                "rlChanCfg_t": {
                    "rxChannelEn": f"0x{config['channelCfg']['rxChannelEn']:X}",
                    "txChannelEn": f"0x{config['channelCfg']['txChannelEn']:X}",
                    "cascading": 1 if devId == 0 else 2,
                    "cascadingPinoutCfg": "0x0"
                },
                "rlAdcOutCfg_t": {
                    "fmt": config['adcOutCfg']['fmt']
                },
                "rlLowPowerModeCfg_t": config['lpmCfg'],
                "rlProfiles": [{
                    "rlProfileCfg_t": {
                        "profileId": p_cfg['profileId'],
                        "pfVcoSelect": f"0x{p_cfg['pfVcoSelect']:X}",
                        "startFreqConst_GHz": startFreq_GHz,
                        "idleTimeConst_usec": idleTime_usec,
                        "adcStartTimeConst_usec": adcStartTime_usec,
                        "rampEndTime_usec": rampEndTime_usec,
                        "txOutPowerBackoffCode": f"0x{p_cfg['txOutPowerBackoffCode']:X}",
                        "txPhaseShifter": f"0x{p_cfg['txPhaseShifter']:X}",
                        "freqSlopeConst_MHz_usec": freqSlope_MHz_usec,
                        "txStartTime_usec": txStartTime_usec,
                        "numAdcSamples": p_cfg['numAdcSamples'],
                        "digOutSampleRate": float(p_cfg['digOutSampleRate']),
                        "hpfCornerFreq1": p_cfg['hpfCornerFreq1'],
                        "hpfCornerFreq2": p_cfg['hpfCornerFreq2'],
                        "rxGain_dB": f"0x{p_cfg['rxGain']:X}"
                    }
                }],
                "rlChirps": chirps,
                "rlFrameCfg_t": {
                    "chirpEndIdx": f_cfg['chirpEndIdx'],
                    "chirpStartIdx": f_cfg['chirpStartIdx'],
                    "numLoops": f_cfg['numLoops'],
                    "numFrames": f_cfg['numFrames'],
                    "framePeriodicity_msec": framePeriodicity_msec,
                    "triggerSelect": 1 if devId == 0 else 2,
                    "frameTriggerDelay": 0.0
                }
            },
            "rawDataCaptureConfig": {
                "rlDevDataFmtCfg_t": {
                    "iqSwapSel": config['dataFmtCfg']['iqSwapSel'],
                    "chInterleave": config['dataFmtCfg']['chInterleave']
                },
                "rlDevDataPathCfg_t": {
                    "intfSel": config['datapathCfg']['intfSel'],
                    "transferFmtPkt0": f"0x{config['datapathCfg']['transferFmtPkt0']:X}",
                    "transferFktPkt1": f"0x{config['datapathCfg']['transferFmtPkt1']:X}",
                }
            }
        }
        json_output["mmWaveDevices"].append(device_config)

    try:
        with open(filename, 'w') as f:
            json.dump(json_output, f, indent=2)
        print(f"  > Berhasil menyimpan konfigurasi ke {filename}")
    except IOError as e:
        print(f"ERROR: Gagal menyimpan file JSON: {e}", file=sys.stderr)

def check_status(status, error_message):
    if status != 0:
        print(f"ERROR: {error_message} (Kode Status: {status})", file=sys.stderr)
        sys.exit(1)

def run_capture(capture_dir, duration_sec, config):
    json_filename = f"{capture_dir}.mmwave.json"
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Memulai siklus perekaman...")
    print(f"  > Direktori Perekaman: {capture_dir}")
    print(f"  > Durasi: {duration_sec} detik")
    status = mmwcas.mmw_arming_tda(capture_dir)
    check_status(status, "Gagal melakukan arming TDA")
    time.sleep(2)
    status = mmwcas.mmw_start_frame()
    check_status(status, "Gagal memulai frame")
    print("  > Perekaman sedang berlangsung...")
    time.sleep(duration_sec)
    status = mmwcas.mmw_stop_frame()
    check_status(status, "Gagal menghentikan frame")
    status = mmwcas.mmw_dearming_tda()
    check_status(status, "Gagal melakukan dearming TDA")
    print(f"  > Perekaman untuk '{capture_dir}' selesai.")
    export_config_to_json(config, json_filename)
    time.sleep(1)
    return json_filename

def transfer_data_thread(remote_user, remote_ip, remote_path, local_path, capture_dir, json_filename):
    source_dir = f"{remote_user}@{remote_ip}:{remote_path}/{capture_dir}"
    destination_path = os.path.expanduser(local_path)
    os.makedirs(destination_path, exist_ok=True)
    command_dir = ["scp", "-O", "-o", "HostKeyAlgorithms=+ssh-rsa", "-o", "PubkeyAcceptedAlgorithms=+ssh-rsa", "-r", source_dir, destination_path]
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Memulai transfer direktori '{capture_dir}'...")
    try:
        subprocess.run(command_dir, check=True, capture_output=True, text=True)
        print(f"  > Transfer direktori '{capture_dir}' berhasil.")
    except Exception as e:
        print(f"ERROR: Gagal mentransfer direktori '{capture_dir}'. Detail: {e}", file=sys.stderr)
    source_json = json_filename
    command_json = ["scp", "-O", "-o", "HostKeyAlgorithms=+ssh-rsa", "-o", "PubkeyAcceptedAlgorithms=+ssh-rsa", source_json, f"{remote_user}@{remote_ip}:{remote_path}/{capture_dir}/"]
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Memulai transfer file JSON '{json_filename}'...")
    try:
        subprocess.run(command_json, check=True, capture_output=True, text=True)
        print(f"  > Transfer file JSON '{json_filename}' berhasil.")
    except Exception as e:
        print(f"ERROR: Gagal mentransfer file JSON '{json_filename}'. Detail: {e}", file=sys.stderr)

def start_async_transfer(remote_user, remote_ip, remote_path, local_path, capture_dir, json_filename):
    thread = threading.Thread(target=transfer_data_thread, args=(remote_user, remote_ip, remote_path, local_path, capture_dir, json_filename))
    thread.daemon = True
    thread.start()
    print(f"  > Proses transfer untuk '{capture_dir}' dan '{json_filename}' telah dimulai di latar belakang.")

def main():
    parser = argparse.ArgumentParser(description="Alat kontrol dan perekaman untuk TI MMWave Cascade EVM, versi Python.", formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('--lua', type=str, help="Path ke file konfigurasi .lua dari mmWave Studio.")
    parser.add_argument('-m', '--mode', choices=['single', 'continuous'], default='single', help="Mode operasi")
    parser.add_argument('-d', '--duration', type=float, default=10.0, help="Durasi perekaman (detik)")
    parser.add_argument('-n', '--interval', type=float, default=10.0, help="Interval antar perekaman (detik) di mode continuous")
    parser.add_argument('--basename', type=str, default="MMWL_Capture", help="Nama dasar untuk direktori perekaman")
    parser.add_argument('--no-transfer', action='store_true', help="Nonaktifkan transfer data otomatis")
    parser.add_argument('--remote-user', type=str, default=DEFAULT_REMOTE_USER)
    parser.add_argument('--remote-ip', type=str, default=DEFAULT_REMOTE_IP)
    parser.add_argument('--remote-path', type=str, default=DEFAULT_REMOTE_BASE_PATH)
    parser.add_argument('--local-path', type=str, default=DEFAULT_LOCAL_DEST_PATH)
    args = parser.parse_args()

    # Tentukan konfigurasi yang akan digunakan
    active_config = copy.deepcopy(default_radar_config) # Mulai dengan salinan default
    if args.lua:
        print(f"Memuat konfigurasi dari file LUA: {args.lua}")
        lua_params = parse_lua_assignments(args.lua)
        if lua_params:
            lsb_params = convert_physical_to_lsb(lua_params)
            print("[Lua Loader] Menerapkan parameter LSB yang dikonversi...")
            # Terapkan parameter yang dikonversi ke konfigurasi aktif
            for key, value in lsb_params.items():
                if key in active_config["profileCfg"]:
                    active_config["profileCfg"][key] = value
                if key in active_config["frameCfg"]:
                    active_config["frameCfg"][key] = value
        else:
            print("Gagal memuat file LUA. Menggunakan konfigurasi default.", file=sys.stderr)
    else:
        print("Menggunakan konfigurasi default.")

    print("Menginisialisasi MMWave...")
    status = mmwcas.mmw_set_config(active_config)
    check_status(status, "Gagal mengatur konfigurasi")
    status = mmwcas.mmw_init()
    check_status(status, "Gagal melakukan inisialisasi mmw_init")
    time.sleep(2)

    try:
        if args.mode == 'single':
            print("Mode Operasi: Single Capture")
            capture_dir = f"{args.basename}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            json_filename = run_capture(capture_dir, args.duration, active_config)
            if not args.no_transfer:
                start_async_transfer(args.remote_user, args.remote_ip, args.remote_path, args.local_path, capture_dir, json_filename)
            time.sleep(2) 
        elif args.mode == 'continuous':
            print("Mode Operasi: Continuous Monitoring")
            print(f"Interval antar perekaman: {args.interval} detik")
            print("Tekan Ctrl+C untuk berhenti.")
            while True:
                capture_dir = f"{args.basename}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                json_filename = run_capture(capture_dir, args.duration, active_config)
                if not args.no_transfer:
                    start_async_transfer(args.remote_user, args.remote_ip, args.remote_path, args.local_path, capture_dir, json_filename)
                print(f"\nMenunggu {args.interval} detik untuk siklus berikutnya...")
                time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nInterupsi diterima (Ctrl+C). Menghentikan program...")
    finally:
        print("Menutup koneksi MMWave...")
        print("Selesai.")

if __name__ == "__main__":
    main()