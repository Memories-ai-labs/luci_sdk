import subprocess


class DeviceAPI:
    """
    High-level device information interface for LUCI Pin.

    This class wraps common ADB shell queries and exposes them
    as Python methods.
    """

    def __init__(self, device_id: str):
        if not device_id:
            raise ValueError("DeviceAPI requires a valid device_id")
        self.device_id = device_id

    def _adb_shell(self, command: str) -> str:
        """Run an adb shell command and return stdout."""
        result = subprocess.run(
            ["adb", "-s", self.device_id, "shell", command],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        return result.stdout.strip()

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

        Equivalent to:
            adb shell cat /etc/os-release
        """
        return self._adb_shell("cat /etc/os-release")

    def uptime(self) -> str:
        """
        Return device uptime.
        """
        return self._adb_shell("uptime")

    def ip_address(self) -> str | None:
        """
        Return the device IP address on wlan0 if available.
        """
        out = self._adb_shell("ip addr show wlan0")
        for token in out.split():
            if token.startswith("inet"):
                return token.split("/")[0][5:]
        return None
