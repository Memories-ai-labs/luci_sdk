"""
setup_hotspot_connection.py

Establishes a Wi-Fi connection between the LUCI Pin and a user-provided
mobile/PC hotspot using ADB and wpa_supplicant.

Usage:
    python setup_hotspot_connection.py <SSID> <PASSWORD>

Notes:
- Hotspot must be enabled manually on the host device.
- This script pushes and executes a shell script on the LUCI Pin.
- Designed for embedded Linux (wpa_supplicant + udhcpc).
"""

import subprocess
import tempfile
import os
import time
import sys


ADB = "adb"  # Change this if adb is not in PATH


def run(cmd, check=True):
    print(">", " ".join(cmd))
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    if check and result.returncode != 0:
        if result.stderr:
            print(result.stderr.strip())
        raise RuntimeError("Command failed")
    return result.stdout.strip()


def get_device():
    out = run([ADB, "devices"])
    lines = out.splitlines()[1:]
    devices = [l.split()[0] for l in lines if "\tdevice" in l]
    if not devices:
        raise RuntimeError("No ADB device found")
    return devices[0]


def create_wifi_script(path):
    script = """#!/bin/sh
SSID="$1"
PASS="$2"

WPA_CONF=/tmp/wpa_supplicant.conf

echo "network={" > $WPA_CONF
echo "    ssid=\\"$SSID\\"" >> $WPA_CONF
echo "    psk=\\"$PASS\\"" >> $WPA_CONF
echo "}" >> $WPA_CONF

wpa_supplicant -B -i wlan0 -c $WPA_CONF

sleep 10

for j in 1 2 3 4 5; do
    udhcpc -i wlan0 && break
    echo "DHCP failed, retrying in 3s..."
    sleep 3
done
"""
    with open(path, "w", newline="\n") as f:
        f.write(script)


def reset_wifi(device):
    print("Resetting Wi-Fi interface...")
    run([ADB, "-s", device, "shell", "killall", "wpa_supplicant"], check=False)
    run([ADB, "-s", device, "shell", "killall", "udhcpc"], check=False)
    run([ADB, "-s", device, "shell", "ifconfig", "wlan0", "down"], check=False)
    time.sleep(1)
    run([ADB, "-s", device, "shell", "ifconfig", "wlan0", "up"], check=False)


def push_and_run(device, local_script, ssid, password):
    remote_path = "/data/local/tmp/setup_wifi.sh"

    run([ADB, "-s", device, "push", local_script, remote_path])
    run([ADB, "-s", device, "shell", "chmod", "+x", remote_path])
    run([ADB, "-s", device, "shell", remote_path, ssid, password])


def main():
    if len(sys.argv) != 3:
        print("Usage: python setup_hotspot_connection.py <SSID> <PASSWORD>")
        sys.exit(1)

    ssid = sys.argv[1]
    password = sys.argv[2]

    device = get_device()
    print(f"Using device: {device}")

    with tempfile.TemporaryDirectory() as tmp:
        script_path = os.path.join(tmp, "setup_wifi.sh")
        create_wifi_script(script_path)

        reset_wifi(device)
        push_and_run(device, script_path, ssid, password)

    print("Hotspot connection script completed.")


if __name__ == "__main__":
    main()
