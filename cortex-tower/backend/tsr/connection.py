"""Build the ERP backend from configuration. Config is read in ``config.py`` only."""

from __future__ import annotations

from .backend import HttpBackend

_cached = None


def get_backend(timeout: int = 40) -> HttpBackend:
    """The Arinox ERP: ``ARINOX_ERP_BASE`` + ``ARINOX_ERP_TOKEN`` if set, else the KOGO_SAS credentials erp.py discovers."""
    global _cached
    if _cached is not None:
        return _cached
    import config
    base, token = config.ARINOX_ERP_BASE, config.ARINOX_ERP_TOKEN
    if not (base and token):
        import erp
        creds = erp.get_creds() or {}
        base = base or creds.get("BASE") or ""
        auth = (creds.get("AUTH") or {}).get("Authorization", "")
        token = token or auth.replace("token ", "", 1)
    if not base:
        raise RuntimeError("No ERP connection: set ARINOX_ERP_BASE and ARINOX_ERP_TOKEN (or connect the KOGO ERP).")
    _cached = HttpBackend(base, token, timeout=timeout)
    return _cached
