import time
import mmwcas
import argparse
import subprocess
import threading
import sys
from datetime import datetime
import os

# --- Konfigurasi Default (dapat diubah melalui argumen CLI) ---
DEFAULT_REMOTE_USER = "root"
DEFAULT_REMOTE_IP = "192.168.33.180"
DEFAULT_REMOTE_BASE_PATH = "/mnt/ssd"
DEFAULT_LOCAL_DEST_PATH = "~/mmwave-cli/PostProc/"

def check_status(status, error_message):
    """Memeriksa status dari panggilan mmwcas dan keluar jika ada error."""
    if status != 0:
        print(f"ERROR: {error_message} (Kode Status: {status})", file=sys.stderr)
        # Coba untuk menutup koneksi sebelum keluar
        try:
            mmwcas.mmw_close()
        except Exception as e:
            print(f"Peringatan: Gagal menutup koneksi mmwcas saat error: {e}", file=sys.stderr)
        sys.exit(1)

def run_capture(capture_dir, duration_sec):
    """
    Menjalankan satu siklus perekaman data penuh.
    Mulai dari arming, start frame, menunggu, stop frame, dan dearming.
    """
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
    time.sleep(1)

def transfer_data_thread(remote_user, remote_ip, remote_path, local_path, capture_dir):
    """
    Fungsi yang akan dijalankan di thread terpisah untuk mentransfer data via scp.
    """
    source = f"{remote_user}@{remote_ip}:{remote_path}/{capture_dir}"
    destination = os.path.expanduser(local_path) # Memperluas '~' menjadi home directory

    # Membuat direktori tujuan jika belum ada
    os.makedirs(destination, exist_ok=True)

    # Perintah SCP yang sama dengan di mimo.c untuk kompatibilitas
    command = [
        "scp",
        "-O", # Diperlukan untuk beberapa versi OpenSSH
        "-o", "HostKeyAlgorithms=+ssh-rsa",
        "-o", "PubkeyAcceptedAlgorithms=+ssh-rsa",
        "-r", # Rekursif untuk direktori
        source,
        destination
    ]
    
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Memulai transfer data untuk '{capture_dir}'...")
    print(f"  > Perintah: {' '.join(command)}")
    
    try:
        # Menggunakan subprocess.run untuk menunggu proses selesai dan menangkap output
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        print(f"  > Transfer untuk '{capture_dir}' berhasil diselesaikan.")
        # print(f"  > STDOUT: {result.stdout}") # Uncomment untuk debugging
    except subprocess.CalledProcessError as e:
        print(f"ERROR: Gagal mentransfer data untuk '{capture_dir}'.", file=sys.stderr)
        print(f"  > Return Code: {e.returncode}", file=sys.stderr)
        print(f"  > STDERR: {e.stderr}", file=sys.stderr)
    except FileNotFoundError:
        print("ERROR: Perintah 'scp' tidak ditemukan. Pastikan OpenSSH client terinstall.", file=sys.stderr)


def start_async_transfer(remote_user, remote_ip, remote_path, local_path, capture_dir):
    """
    Memulai transfer data dalam thread terpisah agar tidak memblokir.
    """
    thread = threading.Thread(
        target=transfer_data_thread,
        args=(remote_user, remote_ip, remote_path, local_path, capture_dir)
    )
    thread.daemon = True  # Memastikan thread akan berhenti jika program utama berhenti
    thread.start()
    print(f"  > Proses transfer untuk '{capture_dir}' telah dimulai di latar belakang.")


def main():
    """Fungsi utama untuk menjalankan skrip."""
    parser = argparse.ArgumentParser(
        description="Alat kontrol dan perekaman untuk TI MMWave Cascade EVM, versi Python.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    
    # Argumen untuk mode operasi
    parser.add_argument(
        '-m', '--mode',
        choices=['single', 'continuous'],
        default='single',
        help="Mode operasi:\n"
             "  single: Menjalankan satu kali perekaman dan keluar.\n"
             "  continuous: Menjalankan perekaman secara terus-menerus."
    )
    parser.add_argument(
        '-d', '--duration',
        type=float,
        default=60.0,
        help="Durasi perekaman untuk setiap siklus dalam detik. Default: 60."
    )
    parser.add_argument(
        '-n', '--interval',
        type=float,
        default=10.0,
        help="Interval waktu (dalam detik) antar perekaman dalam mode continuous. Default: 10."
    )
    parser.add_argument(
        '--basename',
        type=str,
        default="MMWL_Capture",
        help="Nama dasar untuk direktori perekaman. Timestamp akan ditambahkan."
    )
    parser.add_argument(
        '--no-transfer',
        action='store_true',
        help="Nonaktifkan fitur transfer data otomatis setelah perekaman."
    )

    # Argumen untuk konfigurasi transfer
    parser.add_argument('--remote-user', type=str, default=DEFAULT_REMOTE_USER)
    parser.add_argument('--remote-ip', type=str, default=DEFAULT_REMOTE_IP)
    parser.add_argument('--remote-path', type=str, default=DEFAULT_REMOTE_BASE_PATH)
    parser.add_argument('--local-path', type=str, default=DEFAULT_LOCAL_DEST_PATH)

    args = parser.parse_args()

    # Inisialisasi mmwcas
    print("Menginisialisasi MMWave...")
    status = mmwcas.mmw_set_config({}) # Menggunakan config default
    check_status(status, "Gagal mengatur konfigurasi")
    
    status = mmwcas.mmw_init()
    check_status(status, "Gagal melakukan inisialisasi mmw_init")
    time.sleep(2)

    try:
        if args.mode == 'single':
            print("Mode Operasi: Single Capture")
            capture_dir = f"{args.basename}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            run_capture(capture_dir, args.duration)
            if not args.no_transfer:
                start_async_transfer(
                    args.remote_user, args.remote_ip, args.remote_path, args.local_path, capture_dir
                )
            # Beri waktu sedikit agar thread transfer bisa dimulai
            time.sleep(2) 

        elif args.mode == 'continuous':
            print("Mode Operasi: Continuous Monitoring")
            print(f"Interval antar perekaman: {args.interval} detik")
            print("Tekan Ctrl+C untuk berhenti.")
            
            while True:
                capture_dir = f"{args.basename}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                run_capture(capture_dir, args.duration)
                if not args.no_transfer:
                    start_async_transfer(
                        args.remote_user, args.remote_ip, args.remote_path, args.local_path, capture_dir
                    )
                
                print(f"\nMenunggu {args.interval} detik untuk siklus berikutnya...")
                time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\nInterupsi diterima (Ctrl+C). Menghentikan program...")
    finally:
        print("Menutup koneksi MMWave...")
        mmwcas.mmw_close()
        print("Selesai.")

if __name__ == "__main__":
    main()
