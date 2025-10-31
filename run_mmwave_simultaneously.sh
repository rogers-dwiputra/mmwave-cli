#!/bin/bash

# --- Konfigurasi Variabel ---

# Ganti 'nama_perangkat_anda' dengan nilai yang sesuai untuk variabel $NAME
# Anda juga bisa mengubah ini menjadi meminta input dari pengguna.
NAME="SimultantRecordTest_$(date +%y%m%d_%H%M%S)"

# File konfigurasi yang sama
CONFIG_FILE="config/Cascade_Configuration_250227_79Ghz_30frame.toml"

# Durasi rekaman yang sama
TIME_DURATION="0.17"

echo "Memulai eksekusi mmwave secara simultan dengan NAME=$NAME"
echo "--------------------------------------------------------"

# --- Perintah 1 (Jalankan di Background) ---
echo "Memulai Perintah 1 (IP 192.168.33.180)..."
./mmwave -d "$NAME" -i 192.168.33.180 -f "$CONFIG_FILE" --configure --record --time "$TIME_DURATION" &

# Simpan PID dari proses pertama
PID1=$!

# --- Perintah 2 (Jalankan di Background) ---
echo "Memulai Perintah 2 (IP 192.168.33.181)..."
./mmwave -d "$NAME" -i 192.168.33.181 -f "$CONFIG_FILE" --configure --record --time "$TIME_DURATION" &

# Simpan PID dari proses kedua
PID2=$!

# --- Tunggu Kedua Perintah Selesai ---
echo ""
echo "⏳ Menunggu kedua proses mmwave (PID $PID1 dan $PID2) selesai..."
wait $PID1
wait $PID2

echo ""
echo "Kedua perintah mmwave telah selesai dieksekusi."
