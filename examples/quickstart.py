"""
Quickstart for LUCI SDK.

Demonstrates:
1. USB (ADB) connection
2. Optional hotspot setup
3. Device inspection
4. IP caching for later use

Run once for setup.
"""

from luci import LUCI
from luci.utils import save_ip


def main():
    luci = LUCI.connect_via_adb()

    # OPTIONAL: only needed if hotspot not yet configured
    # luci.join_hotspot("HOTSPOT_NAME", "HOTSPOT_PASSWORD")

    print("=== Storage ===")
    print(luci.device.storage())

    print("=== Config ===")
    print(luci.device.config())

    ip = luci.ip_address

    if ip:
        save_ip(ip)
        print(f"[INFO] Saved IP address: {ip}")
    else:
        print("[WARN] Could not detect IP")

    print(
        "\nNext:\n"
        "  python examples/record_video.py\n"
        "or view stream via your RTSP client."
    )


if __name__ == "__main__":
    main()