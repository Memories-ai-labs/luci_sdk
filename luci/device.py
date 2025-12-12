import subprocess
import re


class DeviceAPI:
    """
    High-level device information interface for LUCI Pin.

    This class wraps common ADB shell queries and exposes them
    as Python methods. Designed to work reliably on embedded
    Linux / BusyBox-based systems.
    """

    def __init__(self, device_id: str):
        if not device_id:
            raise ValueError("DeviceAPI requires a valid device_id")
        self.device_id = device_id

    # ======================================================
    # Internal helpers
    # ======================================================
    def _adb_shell(self, command: str) -> str:
        """
        Run an adb shell command and return stdout only.
        Stderr is intentionally suppressed to avoid noisy output
        on embedded systems.
        """
        result = subprocess.run(
            ["adb", "-s", self.device_id, "shell", command],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        return result.stdout.strip()

    # ======================================================
    # Device information
    # ======================================================
    def storage(self) -> str:
        """
        Return storage usage information.

        Equivalent to:
            adb shell df -h
        """
        return self._adb_shell("df -h")

    def config(self) -> str:
        """
        Return OS / configuration information.

        On embedded Linux devices, /etc/os-release may not exist.
        In that case, a descriptive fallback string is returned.
        """
        out = self._adb_shell("cat /etc/os-release 2>/dev/null")
        return out or "Embedded Linux device (no /etc/os-release)"

    def uptime(self) -> str:
        """
        Return device uptime.

        Equivalent to:
            adb shell uptime
        """
        return self._adb_shell("uptime")

    # ======================================================
    # Network
    # ======================================================
    def ip_address(self) -> str | None:
        """
        Return the device IP address on wlan0 if available.

        Uses multiple fallback commands to support BusyBox
        and minimal embedded Linux environments.
        """
        commands = [
            "ip addr show wlan0",
            "ifconfig wlan0",
            "route -n",
        ]

        for cmd in commands:
            out = self._adb_shell(cmd)
            if not out:
                continue

            # Find IPv4 addresses
            matches = re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", out)
            for ip in matches:
                # Filter out loopback and invalid addresses
                if not ip.startswith(("127.", "0.")):
                    return ip

        return None
