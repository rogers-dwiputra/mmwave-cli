"""
TTN → InfluxDB bridge.
Subscribes to TTN MQTT, writes decoded_payload fields to InfluxDB Cloud.

Usage:
  pip install paho-mqtt influxdb-client
  export TTN_API_KEY="<your-ttn-api-key>"
  export INFLUXDB_TOKEN="<your-influxdb-token>"
  python3 ttn_to_influxdb.py
"""

import json
import os
import ssl
import sys
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

# ── TTN MQTT ─────────────────────────────────────────────────────────────────
TTN_HOST    = "imrsl.as1.cloud.thethings.industries"
TTN_PORT    = 8883
TTN_APP_ID  = "iosar-imrsl"
TTN_API_KEY = os.environ.get("TTN_API_KEY", "")   # set via env var
TTN_TOPIC   = f"v3/{TTN_APP_ID}/devices/+/up"

# ── InfluxDB Cloud ────────────────────────────────────────────────────────────
INFLUX_URL    = "https://us-east-1-1.aws.cloud2.influxdata.com"
INFLUX_ORG    = "fa0efd0230808dbd"
INFLUX_BUCKET = "iosar"
INFLUX_TOKEN  = os.environ.get("INFLUXDB_TOKEN", "")  # set via env var


def _get_write_api():
    client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
    return client.write_api(write_options=SYNCHRONOUS)


write_api = None


def on_connect(client, userdata, flags, rc):
    codes = {
        0: "connected",
        1: "bad protocol",
        2: "client ID rejected",
        3: "server unavailable",
        4: "bad credentials",
        5: "not authorized",
    }
    print(f"MQTT: {codes.get(rc, f'rc={rc}')}")
    if rc == 0:
        client.subscribe(TTN_TOPIC)
        print(f"Subscribed: {TTN_TOPIC}")


def on_message(client, userdata, msg):
    global write_api
    try:
        payload = json.loads(msg.payload.decode())
        uplink  = payload.get("uplink_message", {})
        decoded = uplink.get("decoded_payload", {})

        if not decoded:
            return

        device_id = (
            payload.get("end_device_ids", {}).get("device_id", "unknown")
        )
        received_at = uplink.get("received_at") or datetime.now(timezone.utc).isoformat()

        point = (
            Point("uplink")
            .tag("device_id", device_id)
            .tag("application_id", TTN_APP_ID)
            .time(received_at)
        )

        # Write all numeric fields including per-PS (freq_ps0, rms_ps0, …)
        for key, value in decoded.items():
            if key in ("timestamp_iso",):
                continue   # skip ISO string fields
            if isinstance(value, (int, float)):
                point = point.field(key, float(value))

        write_api.write(bucket=INFLUX_BUCKET, record=point)

        # Concise log: overall + per-PS summary
        n_ps = int(decoded.get("n_ps", 0))
        ps_summary = ""
        if n_ps > 0:
            ps_parts = [
                f"PS{i}:{decoded.get(f'freq_ps{i}', 0):.2f}Hz"
                for i in range(n_ps)
            ]
            ps_summary = "  per-PS: " + " | ".join(ps_parts)
        print(f"[{received_at}] {device_id}: "
              f"freq={decoded.get('dominant_frequency_hz', '?')} Hz  "
              f"rms={decoded.get('displacement_rms_mm', '?')} mm{ps_summary}")

    except Exception as exc:
        print(f"Error processing message: {exc}", file=sys.stderr)


def on_disconnect(client, userdata, rc):
    if rc != 0:
        print(f"MQTT disconnected unexpectedly (rc={rc}), will auto-reconnect")


def main():
    if not TTN_API_KEY:
        sys.exit("TTN_API_KEY env var not set")
    if not INFLUX_TOKEN:
        sys.exit("INFLUXDB_TOKEN env var not set")

    global write_api
    write_api = _get_write_api()
    print(f"InfluxDB connected → bucket: {INFLUX_BUCKET}")

    client = mqtt.Client(protocol=mqtt.MQTTv311)
    client.username_pw_set(TTN_APP_ID, TTN_API_KEY)
    client.tls_set(tls_version=ssl.PROTOCOL_TLS)
    client.on_connect    = on_connect
    client.on_message    = on_message
    client.on_disconnect = on_disconnect

    print(f"Connecting to {TTN_HOST}:{TTN_PORT} ...")
    client.connect(TTN_HOST, TTN_PORT, keepalive=60)
    client.loop_forever()


if __name__ == "__main__":
    main()
