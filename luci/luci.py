import os
import subprocess
import sys
import re

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

    # ======================================================
    # Initialization
    # ======================================================
    def __init__(self, device_id: str):
        if not device_id:
            raise ValueError("LUCI requires a valid device_id")

        self.device_id = device_id
        # Always initialize IP cache
        self._ip_address: str | None = None

    # ======================================================
    # ADB Connection
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
        Join a Wi-Fi hotspot using setup_hotspot_connection.py.
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

        # Detect and cache IP immediately after hotspot join
        self._ip_address = self._detect_ip()

        if self._ip_address:
            print(f"[LUCI] Connected to hotspot, IP = {self._ip_address}")
        else:
            print("[LUCI] Hotspot connected, IP address not detected")

        return self

    # ======================================================
    # IP Detection (robust for embedded Linux)
    # ======================================================
    def _detect_ip(self) -> str | None:
        """
        Detect IP address using multiple fallback methods.
        Designed for BusyBox / embedded Linux environments.
        """
        commands = [
            "ip addr show wlan0",
            "ifconfig wlan0",
            "route -n",
        ]

        for cmd in commands:
            result = subprocess.run(
                ["adb", "-s", self.device_id, "shell", cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            output = result.stdout
            matches = re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", output)

            for ip in matches:
                # Filter loopback and invalid addresses
                if not ip.startswith(("127.", "0.")):
                    return ip

        return None

    # ======================================================
    # Public IP accessor (IMPORTANT)
    # ======================================================
    @property
    def ip_address(self) -> str | None:
        """
        Return the best-known IP address.

        Priority:
        1. Cached IP from hotspot join
        2. Live detection via ADB
        """
        if self._ip_address:
            return self._ip_address

        self._ip_address = self._detect_ip()
        return self._ip_address

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
        ip: str | None = None,
        port: int = 50001,
        path: str = "/live/0"
    ):
        """
        Open and display the RTSP video stream.

        Args:
            ip: Optional manual IP override
            port: RTSP port
            path: RTSP path
        """
        ip = ip or self.ip_address

        if not ip:
            raise RuntimeError(
                "Device IP unknown.\n"
                "Ensure hotspot is connected or provide IP manually:\n"
                "    luci.view_stream(ip='192.168.x.x')"
            )

        rtsp_url = f"rtsp://{ip}:{port}{path}"
        print(f"[LUCI] Opening RTSP stream: {rtsp_url}")

        cap = SingleCameraCapture(
            rtsp_url=rtsp_url,
            name="luci"
        )
        cap.run()
