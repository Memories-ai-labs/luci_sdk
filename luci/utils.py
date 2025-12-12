import json
import os

CACHE_FILE = os.path.join(
    os.path.dirname(__file__),
    "..",
    ".luci_cache.json"
)


def save_ip(ip: str):
    data = {}
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                data = json.load(f)
        except Exception:
            data = {}

    data["last_ip"] = ip

    with open(CACHE_FILE, "w") as f:
        json.dump(data, f, indent=2)


def load_ip() -> str | None:
    if not os.path.exists(CACHE_FILE):
        return None

    try:
        with open(CACHE_FILE, "r") as f:
            data = json.load(f)
        return data.get("last_ip")
    except Exception:
        return None
