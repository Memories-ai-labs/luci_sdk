import argparse
import socket
import time

from luci import LUCI
from luci.utils import load_ip, save_ip
from sdk_save_video.luci_sdk import RtspRecorder

DEFAULT_PORT = 50001
DEFAULT_PATH = "/live/0"


def rtsp_reachable(ip: str, port: int, timeout: float = 2.0) -> bool:
    """
    Fast check to see whether the RTSP port is reachable.
    Avoids launching FFmpeg unnecessarily.
    """
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Record LUCI RTSP stream (cached IP → ADB fallback)"
    )
    parser.add_argument("--duration", type=int, default=10,
                        help="Recording duration in seconds")
    parser.add_argument("--segment-time", type=int, default=5,
                        help="FFmpeg segment duration in seconds")
    parser.add_argument("--save-dir", default="recordings",
                        help="Directory to save recordings")
    parser.add_argument("--ffmpeg", default="ffmpeg",
                        help="Path to ffmpeg executable")
    args = parser.parse_args()

    ip = None
    luci = None

    # --------------------------------------------------
    # 1. Try cached IP first
    # --------------------------------------------------
    cached_ip = load_ip()
    if cached_ip:
        print(f"[INFO] Found cached IP: {cached_ip}")
        if rtsp_reachable(cached_ip, DEFAULT_PORT):
            print("[INFO] RTSP reachable via cached IP")
            ip = cached_ip
        else:
            print("[WARN] Cached IP not reachable")

    # --------------------------------------------------
    # 2. Try ADB if no valid IP yet
    # --------------------------------------------------
    if not ip:
        print("[INFO] Trying ADB connection...")
        try:
            luci = LUCI.connect_via_adb()
        except RuntimeError as e:
            print(f"[ERROR] {e}")
            print(
                "\n[HINT]\n"
                "  • If the device is already on Wi-Fi, ensure the cached IP is valid\n"
                "  • Or connect the LUCI Pin via USB and enable ADB\n"
            )
            return

        ip = luci.ip_address
        if ip and rtsp_reachable(ip, DEFAULT_PORT):
            print(f"[INFO] RTSP reachable via ADB-detected IP: {ip}")
            save_ip(ip)
            print(f"[INFO] Saved IP address: {ip}")
        else:
            print("[INFO] Attempting hotspot connection...")
            ssid = input("Hotspot SSID: ").strip()
            password = input("Hotspot Password: ").strip()

            luci.join_hotspot(ssid, password)
            ip = luci.ip_address

            if not ip or not rtsp_reachable(ip, DEFAULT_PORT):
                raise RuntimeError("RTSP stream not reachable after hotspot connection")

            save_ip(ip)
            print(f"[INFO] Saved IP address: {ip}")

    # --------------------------------------------------
    # 3. Record using known-good workflow
    # --------------------------------------------------
    rtsp_url = f"rtsp://{ip}:{DEFAULT_PORT}{DEFAULT_PATH}"
    print(f"[INFO] Recording RTSP stream: {rtsp_url}")

    recorder = RtspRecorder(
        rtsp_url=rtsp_url,
        ffmpeg_path=args.ffmpeg,
        save_dir=args.save_dir,
        segment_time=args.segment_time
    )

    recorder.start()
    print(f"[INFO] Recording for {args.duration} seconds")
    print("[INFO] Do NOT press Ctrl+C unless you want to stop early")

    try:
        time.sleep(args.duration)
    except KeyboardInterrupt:
        print("\n[WARN] Ctrl+C detected — stopping recording safely")
    finally:
        recorder.stop()
        print("[SUCCESS] Recording finished")
        print(f"[INFO] Files saved in: {args.save_dir}")


if __name__ == "__main__":
    main()
