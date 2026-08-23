"""VM instance status via GCP's metadata server (no credentials needed — it's
only reachable from inside the VM itself) plus a static cost estimate, for the
Status page. Fails fast and returns "unknown" off-GCP (e.g. local dev)."""

import requests

_METADATA_BASE = "http://169.254.169.254/computeMetadata/v1/instance"
_METADATA_HEADERS = {"Metadata-Flavor": "Google"}
_METADATA_TIMEOUT = 1.5


def _metadata(path: str) -> str | None:
    try:
        resp = requests.get(f"{_METADATA_BASE}/{path}", headers=_METADATA_HEADERS, timeout=_METADATA_TIMEOUT)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException:
        return None


def _system_uptime() -> str | None:
    try:
        with open("/proc/uptime") as f:
            seconds = float(f.read().split()[0])
    except OSError:
        return None
    days, rem = divmod(int(seconds), 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    parts = [f"{days}d"] if days else []
    if days or hours:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


def get_vm_status() -> dict:
    zone = _metadata("zone")
    if zone is None:
        return {
            "state": "unknown",
            "label": "Not on GCP",
            "detail": "Metadata server unreachable (local dev or non-GCP host).",
        }
    zone_name = zone.rsplit("/", 1)[-1]
    machine_type = _metadata("machine-type")
    machine_name = machine_type.rsplit("/", 1)[-1] if machine_type else "unknown machine type"
    external_ip = _metadata("network-interfaces/0/access-configs/0/external-ip") or "unknown IP"
    uptime = _system_uptime()
    detail = f"{machine_name} in {zone_name} · {external_ip}"
    if uptime:
        detail += f" · up {uptime}"
    return {"state": "good", "label": "Running", "detail": detail}


def get_cost_estimate() -> dict:
    # Deliberately not a live GCP Billing API query — that needs a service
    # account granted billing.viewer at the billing-account level (a
    # sensitive, separate grant) and billing data itself only updates ~daily.
    # An e2-micro in an Always Free-eligible region is free outright as long
    # as disk and egress stay under the free limits, so a static estimate is
    # both simpler and, for this single-VM setup, exactly as accurate.
    return {
        "label": "$0.00 / month",
        "detail": (
            "e2-micro in an Always Free-eligible region — free as long as the boot "
            "disk stays ≤30GB and network egress stays within the free monthly "
            "allowance. Check the GCP Billing console for your actual bill."
        ),
    }
