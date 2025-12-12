import os
import subprocess
import sys

from sdk_capture.capture_sdk import SingleCameraCapture
from .device import DeviceAPI


class LUCI:
    """
    High-level SDK interface for the LUCI Pin.

    Example:
        luci = LUCI.connect_via_adb()
        luci.join_hotspot("SSID", "PASSWORD")
        print(luci.device.storage())
        luci.view_stream()
    """

    def __init__(self, device_id: str):
        if not device_id:
            raise ValueError("LUCI requires a valid device_id")
        self.device_id = device_id
        self._ip_address: str | None = None

    # ======================================================
    # Connection
    # ======================================================
    @classmethod
    def connect_via_adb(cls) -> "LUCI":
        """
        Detect a connected LUCI Pin via ADB and return a LUCI instance.
        """
        result = subprocess.run(
            ["adb", "devices"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        lines = result.stdout.splitlines()[1:]
        devices = [l.split()[0] for l in lines if "\tdevice" in l]

        if not devices:
            raise RuntimeError("No LUCI Pin detected via ADB")

        device_id = devices[0]
        print(f"[LUCI] Connected via ADB: {device_id}")
        return cls(device_id=device_id)

    # ======================================================
    # Wi-Fi / Hotspot
    # ======================================================
    def join_hotspot(self, ssid: str, password: str) -> "LUCI":
        """
        Join a Wi-Fi hotspot using the existing setup_hotspot_connection.py script.
        """
        if not ssid or not password:
            raise ValueError("SSID and password are required")

        script_path = os.path.abspath(
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "setup_connection",
                "Wireless_connection",
                "setup_hotspot_connection.py"
            )
        )

        if not os.path.exists(script_path):
            raise FileNotFoundError(
                f"Hotspot setup script not found: {script_path}"
            )

        print("[LUCI] Joining hotspot...")

        result = subprocess.run(
            [sys.executable, script_path, ssid, password],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        if result.returncode != 0:
            raise RuntimeError(result.stderr or result.stdout)

        # Cache IP address after connection
        self._ip_address = self._detect_ip()

        if self._ip_address:
            print(f"[LUCI] Connected to hotspot, IP = {self._ip_address}")
        else:
            print("[LUCI] Hotspot connected, IP address not detected")

        return self

    def _detect_ip(self) -> str | None:
        """
        Detect IP address using multiple fallback methods.
        Works on BusyBox / embedded Linux.
        """

        commands = [
            "ip addr show wlan0",
            "ifconfig wlan0",
            "udhcpc -n -q -i wlan0",
        ]

        for cmd in commands:
            result = subprocess.run(
                ["adb", "-s", self.device_id, "shell", cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            out = result.stdout
            for token in out.replace(":", " ").split():
                if token.count(".") == 3 and token[0].isdigit():
                    return token

        return None

    # ======================================================
    # Device API
    # ======================================================
    @property
    def device(self) -> DeviceAPI:
        """
        Access device-level inspection APIs.
        """
        return DeviceAPI(self.device_id)

    # ======================================================
    # RTSP Streaming
    # ======================================================
    def view_stream(
        self,
        port: int = 50001,
        path: str = "/live/0"
    ):
        """
        Open and display the RTSP video stream.
        """
        ip = self._ip_address or self.device.ip_address()
        if not ip:
            raise RuntimeError(
                "Device IP unknown. Connect to hotspot first."
            )

        rtsp_url = f"rtsp://{ip}:{port}{path}"
        print(f"[LUCI] Opening RTSP stream: {rtsp_url}")

        cap = SingleCameraCapture(
            rtsp_url=rtsp_url,
            name="luci"
        )
        cap.run()
