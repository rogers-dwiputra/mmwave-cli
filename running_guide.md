# Petunjuk Menjalankan MIMO Radar Capture

## Daftar Isi
- [Running mimo.c](#running-mimoc)
- [Running mimo.py](#running-mimopy)
- [Struktur Direktori](#struktur-direktori)
- [Catatan Penting](#catatan-penting)

---

## Running `mimo.c`

### 1. Persiapan Dependensi
```bash
# Install build tools jika belum ada
sudo apt install build-essential
```

### 2. Compile
```bash
gcc -o mimo mimo.c \
    -I./include \
    -L./lib \
    -lmmwavelink \
    -lmmwcas \
    -lpthread \
    -lm \
    -Wall
```
> Sesuaikan path `-I` dan `-L` dengan lokasi header dan library TI mmWaveLink di sistem Anda.

### 3. Jalankan
```bash
# Konfigurasi saja
./mimo -c -i 192.168.33.180 -p 5001

# Rekam saja (oneshot, 2 menit)
./mimo -r -t 2.0 -d mmwl_capture -i 192.168.33.180 -p 5001

# Konfigurasi sekaligus rekam
./mimo -c -r -t 2.0 -d mmwl_capture -i 192.168.33.180 -p 5001

# Mode monitor (infinite loop, interval 10 detik)
./mimo -c -r -m -n 10 -i 192.168.33.180 -p 5001
```

### Daftar Argumen `mimo.c`

| Argumen | Keterangan | Default |
|---|---|---|
| `-c` / `--configure` | Konfigurasi radar | - |
| `-r` / `--record` | Mulai rekam | - |
| `-t` / `--time` | Durasi rekam (menit) | `1.0` |
| `-d` / `--capture-dir` | Nama direktori capture | `MMWL_Capture_<timestamp>` |
| `-i` / `--ip-addr` | IP TDA board | `192.168.33.180` |
| `-p` / `--port` | Port TDA board | `5001` |
| `-m` / `--monitor` | Mode monitor (infinite loop) | - |
| `-n` / `--interval` | Interval antar capture (detik) | `10` |

---

## Running `mimo.py`

### 1. Persiapan Dependensi
```bash
pip install cython
```

### 2. Build `mmwcas.pyx` (Cython)

Buat file `setup.py` terlebih dahulu:
```python
# setup.py
from setuptools import setup
from Cython.Build import cythonize

setup(
    ext_modules=cythonize("mmwcas.pyx"),
)
```

Kemudian build:
```bash
python setup.py build_ext --inplace
```
> Setelah berhasil, akan muncul file `mmwcas.so` (Linux) di direktori yang sama.

### 3. Jalankan
```bash
# Rekam 10 detik, 1 kali (default)
python mimo.py

# Rekam 30 detik dengan direktori custom
python mimo.py -d my_capture -t 30.0

# Rekam 3 kali loop, interval 60 detik antar loop
python mimo.py -d my_capture -t 10.0 -n 3 -i 60.0

# Infinite loop (Ctrl+C untuk berhenti)
python mimo.py -d my_capture -t 10.0 -n 0

# Ganti IP TDA board
python mimo.py --tda-ip 192.168.33.180
```

### Daftar Argumen `mimo.py`

| Argumen | Keterangan | Default |
|---|---|---|
| `-d` / `--directory` | Nama direktori capture | `mmwave_python` |
| `-t` / `--duration` | Durasi rekam (detik) | `10.0` |
| `--tda-ip` | IP TDA board | `192.168.33.180` |
| `-n` / `--num-loops` | Jumlah loop (0 = infinite) | `1` |
| `-i` / `--inter-loop-time` | Jeda antar loop (detik) | `60.0` |

---

## Struktur Direktori

```
project/
├── mimo.c
├── mimo.py
├── mmwcas.pyx
├── setup.py
├── utility.py
├── include/            ← header TI (mmwave.h, dll)
├── lib/                ← library TI (.so / .a)
└── mmwave_json_files/  ← output JSON (dibuat otomatis)
```

---

## Catatan Penting

- Pastikan TDA board sudah **menyala dan terhubung ke jaringan** sebelum menjalankan script.
- Pastikan koneksi SSH ke `root@192.168.33.180` dapat dilakukan **tanpa password** (menggunakan SSH key), karena `utility.py` menggunakan SSH untuk verifikasi file hasil capture.
- File hasil capture tersimpan di `/mnt/ssd/<capture_dir>` di dalam TDA board.
- File `.mmwave.json` tersimpan di direktori `mmwave_json_files/` di host (sesuai perubahan yang telah dilakukan).
