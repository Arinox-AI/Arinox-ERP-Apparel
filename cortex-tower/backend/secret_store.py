"""Secrets at rest — one place where a secret is sealed and unsealed.

Created 2026-11-04 (D-125). Two secrets were sitting in the clear:

* ``backend/data/sas_creds.json`` — the ERP API key **and** secret, plaintext JSON,
  readable by anyone who can read the folder (and shipped in any backup of it);
* ``mail_settings.password`` — the SMTP/IMAP password, plaintext in the SQLite file.
  It was masked in the UI, which is not the same thing as encrypted on disk.

Design:

* **AES-GCM** (``cryptography``, already installed) with a random 96-bit nonce per value.
  The sealed value is ``enc:v1:<base64(nonce||ciphertext||tag)>``.
* The key comes from ``config.SECRET_KEY`` (env ``CORTEX_SECRET_KEY``) when set. When it
  is absent a machine-local key file ``backend/data/.secret.key`` is created with 0600
  permissions — so a copy of ``data/`` alone no longer discloses anything. The env key is
  the stronger path: with it, the key never touches the disk at all.
* :func:`dec` returns a value that is **not** sealed unchanged. That keeps every legacy
  plaintext row and the old credentials cache working: nothing breaks on the upgrade, and
  the next write seals it.
* :func:`migrate` seals everything that is still plaintext, and is idempotent.

This is not a KMS and does not pretend to be one: someone who can read the key file *and*
the database still wins. It removes the "secret in the clear, in a file that gets copied
around" failure, which is the one that actually happens.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Optional

import config

PREFIX = "enc:v1:"
DATA_DIR = Path(__file__).resolve().parent / "data"
KEY_PATH = DATA_DIR / ".secret.key"
# A second, NON-hidden copy of the key (2026-11-07). The project is moved between machines as a
# zip, and zip/upload tools routinely drop dot-files: the DB (with the sealed mail password) made
# the trip, ``.secret.key`` did not, a fresh key was generated, and every sealed value became
# unreadable — mail sync then reported "mailbox_not_configured". Both files are written; either
# one is enough to read the key back.
KEY_PATH_VISIBLE = DATA_DIR / "secret_key.bin"

_key: Optional[bytes] = None


class SecretUnreadable(ValueError):
    """A sealed value exists but cannot be opened with the current key (the key changed or was lost).

    Raised instead of returning ``""`` so the caller can say *"re-enter the password"* rather than the
    misleading *"not configured"*.
    """


def _key_from_env() -> Optional[bytes]:
    raw = (getattr(config, "SECRET_KEY", "") or "").strip()
    if not raw:
        return None
    try:
        # accept a hex or base64 key of any length, then normalise to 32 bytes
        if len(raw) == 64:
            return bytes.fromhex(raw)
        pad = raw + "=" * (-len(raw) % 4)
        return base64.urlsafe_b64decode(pad.encode())[:32].ljust(32, b"\0")
    except Exception:
        import hashlib
        return hashlib.sha256(raw.encode()).digest()


def _write_key(path: Path, key: bytes) -> None:
    try:
        path.write_bytes(key)
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass
    except Exception:
        pass


def _key_from_file() -> bytes:
    try:
        for p in (KEY_PATH, KEY_PATH_VISIBLE):
            if p.exists():
                data = p.read_bytes()
                if len(data) >= 32:
                    key = data[:32]
                    # heal the other copy, so the next move keeps at least one of them
                    for other in (KEY_PATH, KEY_PATH_VISIBLE):
                        if other != p and not other.exists():
                            _write_key(other, key)
                    return key
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        key = os.urandom(32)
        _write_key(KEY_PATH, key)
        _write_key(KEY_PATH_VISIBLE, key)
        return key
    except Exception:
        import hashlib
        return hashlib.sha256(b"cortex-fallback-key").digest()


def key() -> bytes:
    global _key
    if _key is None:
        _key = _key_from_env() or _key_from_file()
    return _key


def is_sealed(value) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)


def enc(value) -> str:
    """Seal one string. Already-sealed input is returned unchanged (idempotent)."""
    if value is None or value == "":
        return value
    if is_sealed(value):
        return value
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        nonce = os.urandom(12)
        blob = AESGCM(key()).encrypt(nonce, str(value).encode(), None)
        return PREFIX + base64.b64encode(nonce + blob).decode()
    except Exception:
        # never lose the value because sealing failed — but say so loudly in the log
        import sys as _sys; print("secret_store: could not seal a value (storing as-is)", file=_sys.stderr)
        return str(value)


def dec(value) -> str:
    """Unseal. A plaintext (legacy) value is returned unchanged.

    Raises :class:`SecretUnreadable` when the value is sealed but the current key cannot open it.
    (It used to return ``""``, which every caller read as "no password saved" — 2026-11-07.)
    """
    if value is None or value == "" or not is_sealed(value):
        return value
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        raw = base64.b64decode(value[len(PREFIX):])
        return AESGCM(key()).decrypt(raw[:12], raw[12:], None).decode()
    except Exception as e:                                        # noqa: BLE001
        raise SecretUnreadable(
            "A saved secret can no longer be unlocked (the encryption key changed — usually after the "
            "project was moved or re-uploaded). Enter it again to fix this.") from e


def dec_soft(value) -> str:
    """Like :func:`dec`, but an unreadable value becomes ``""``. Only for callers that re-fetch the
    secret anyway (e.g. the ERP credentials cache, which is rediscovered from the gateway)."""
    try:
        return dec(value)
    except SecretUnreadable:
        return ""


def readable(value) -> bool:
    """True when ``value`` is empty, plaintext, or sealed with the current key."""
    try:
        dec(value)
        return True
    except SecretUnreadable:
        return False


def seal_dict(data: dict) -> dict:
    return {k: (enc(v) if isinstance(v, str) else v) for k, v in (data or {}).items()}


def open_dict(data: dict) -> dict:
    return {k: (dec_soft(v) if isinstance(v, str) else v) for k, v in (data or {}).items()}


def seal_json_file(path: Path, payload: dict) -> None:
    """Write ``payload`` sealed, with 0600 permissions."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"v": 2, "sealed": enc(json.dumps(payload))}))
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass
    except Exception:
        pass


def open_json_file(path: Path) -> dict:
    """Read a file written by :func:`seal_json_file`, or a legacy plaintext JSON file."""
    try:
        raw = json.loads(path.read_text())
    except Exception:
        return {}
    if isinstance(raw, dict) and raw.get("sealed"):
        try:
            return json.loads(dec_soft(raw["sealed"]) or "{}")
        except Exception:
            return {}
    return raw if isinstance(raw, dict) else {}


# ────────────────────────────────────────────────────────────────────────────
# One-time migration (idempotent, safe to run on every boot)
# ────────────────────────────────────────────────────────────────────────────

def migrate(db=None) -> dict:
    """Seal what is still plaintext: the credentials cache and the mail password."""
    report = {"creds": "absent", "mail_password": "absent"}
    try:
        from erp import CREDS_PATH
        if CREDS_PATH.exists():
            raw = json.loads(CREDS_PATH.read_text())
            if raw.get("sealed"):
                report["creds"] = "already sealed"
            elif raw.get("BASE"):
                seal_json_file(CREDS_PATH, raw)
                report["creds"] = "sealed"
    except Exception as e:                                    # noqa: BLE001
        report["creds"] = f"error: {type(e).__name__}"

    if db is not None:
        try:
            from models import MailSettingsModel
            row = db.query(MailSettingsModel).first()
            if row is not None:
                if is_sealed(row.password):
                    report["mail_password"] = "already sealed"
                elif row.password:
                    row.password = enc(row.password)
                    db.commit()
                    report["mail_password"] = "sealed"
                else:
                    report["mail_password"] = "empty"
        except Exception as e:                                # noqa: BLE001
            db.rollback()
            report["mail_password"] = f"error: {type(e).__name__}"
    return report


if __name__ == "__main__":
    print(json.dumps({"key": "env" if _key_from_env() else "file", "migrate": migrate()}, indent=2))
