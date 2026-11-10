"""Read a chain's tech pack into the ERP — by handing it to the ONE builder that reads packs.

Why a hand-off and not a second reader
--------------------------------------
`build/phaseA/techpack.py` already turns a buyer's pack into a `Buyer Tech Pack` record:
the header block, the material lines exactly as the buyer wrote them, the POM x size grid,
and a mapping attempt per line that never guesses. `buyer_bom.py` and `bom_from_pack.py`
carry it on into a Buyer BOM and one BOM per size. Re-implementing any of that inside the
Tower would create a second reader with a second set of bugs and two answers to the same
question (RULES 02: one maths, one writer).

So the Tower runs the builders, reads back what they created, and records it on the chain.

The failure that matters
------------------------
If the builders are not on disk next to the deployment, this REFUSES — loudly, with the
path it looked for. It never reports "ingested" without a record name to prove it.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(BACKEND_DIR)

# Where the phase-A builders live. Resolved, in order:
#   1. PACK_BUILDER_DIR (explicit)
#   2. <workspace>/build/phaseA  — three levels up from the app folder
_CANDIDATES = (
    os.environ.get("PACK_BUILDER_DIR") or "",
    os.path.join(APP_DIR, "..", "..", "build", "phaseA"),
    os.path.join(APP_DIR, "..", "build", "phaseA"),
    os.path.join(APP_DIR, "build", "phaseA"),
)

_NEW_PACK = re.compile(r"\bBTP-\d{4}-\d{5}\b")
_NEW_BBOM = re.compile(r"Buyer BOM:\s*(BBOM-\d{4}-\d{5})")
_NEW_BOMS = re.compile(r"created\s+\d+\s+BOM\(s\):\s*(.+)")


def builder_dir() -> str:
    for cand in _CANDIDATES:
        if cand and os.path.isfile(os.path.join(cand, "techpack.py")):
            return os.path.abspath(cand)
    return ""


def resolve_path(stored: str) -> str:
    """The attachment's absolute path, from what the DB holds.

    Only the part below ``backend/`` is stored, because the same project runs from a
    different mount on the platform (2026-11-03). An absolute path from one runtime is
    dead in the other.
    """
    if not stored:
        return ""
    p = str(stored)
    if os.path.isabs(p):
        if "/backend/" in p:
            return os.path.join(BACKEND_DIR, p.split("/backend/", 1)[1])
        return p if os.path.exists(p) else ""
    return os.path.join(BACKEND_DIR, p)


def _run(script: str, args: list[str], timeout: int = 300) -> dict:
    """Run one builder. Returns its exit code, output and the records it named."""
    path = os.path.join(builder_dir(), script)
    if not os.path.isfile(path):
        return {"ok": False, "code": -2, "out": f"{script} is not on disk at {path}", "names": []}
    cmd = [sys.executable, path] + args
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              cwd=builder_dir(), env={**os.environ, "PYTHONUNBUFFERED": "1"})
    except subprocess.TimeoutExpired:
        return {"ok": False, "code": -3, "out": f"{script} timed out after {timeout}s", "names": []}
    except Exception as ex:                                            # noqa: BLE001
        return {"ok": False, "code": -4, "out": f"{script} could not start: {type(ex).__name__}: {ex}",
                "names": []}
    out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    return {"ok": proc.returncode == 0, "code": proc.returncode, "out": out.strip()}


def _tail(text: str, n: int = 1200) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else "…" + text[-n:]


def ingest(payload: dict, apply: bool = True) -> dict:
    """Ingest one pack. ``payload`` carries the resolved file path and who it is for.

    Returns ``{"ok", "refs":[{doctype,name}], "note"}``. Every claim in the note is
    something the builders printed; nothing is inferred.
    """
    path = payload.get("path") or ""
    filename = payload.get("filename") or (os.path.basename(path) if path else "")
    customer = (payload.get("customer") or "").strip()
    style = (payload.get("style_code") or payload.get("style") or "").strip()
    opportunity = (payload.get("opportunity") or "").strip()
    already = payload.get("already") or []

    if not path or not os.path.isfile(path):
        return {"ok": False, "refs": [],
                "note": f"the file for {filename or 'this mail'} is not on disk — re-read the mail, "
                        "then ingest again"}
    if already:
        return {"ok": True, "refs": [], "skipped": True,
                "note": f"already ingested in this chain: {', '.join(already)} — nothing written twice"}
    if not builder_dir():
        return {"ok": False, "refs": [],
                "note": ("the pack builder is not reachable from this deployment "
                         f"(looked for techpack.py in: {', '.join(p for p in _CANDIDATES if p)}). "
                         "Set PACK_BUILDER_DIR to the folder holding techpack.py.")}
    if not customer:
        return {"ok": False, "refs": [],
                "note": "no Customer on this chain yet — the pack cannot be read without the buyer"}

    # `techpack.py` reads the style number out of the pack itself — there is no --style
    # flag, and passing one made the builder exit 2 on the first live attempt (2026-11-03).
    args = ["--files", path, "--customer", customer]
    if opportunity:
        args += ["--opportunity", opportunity]
    if apply:
        args += ["--apply"]

    tech = _run("techpack.py", args, timeout=420)
    packs = _NEW_PACK.findall(tech.get("out") or "")
    refs = [{"doctype": "Buyer Tech Pack", "name": name} for name in packs]
    notes = [f"techpack.py → {'ok' if tech['ok'] else 'failed'}"]
    notes.append(_tail(tech.get("out")))
    if not tech["ok"]:
        return {"ok": False, "refs": refs, "note": "\n".join(notes)}
    if not packs:
        if not apply:
            return {"ok": True, "refs": [], "dry_run": True,
                    "note": "\n".join(notes) + "\n(dry run — the builder read the pack and wrote nothing)"}
        return {"ok": False, "refs": refs,
                "note": "\n".join(notes) + "\n(the builder reported ok but named no Buyer Tech Pack — "
                                            "nothing was created that can be found again)"}

    pack = packs[-1]
    # one BOM per size — only when the pack carries a measurement grid, which the builder
    # itself decides: a pack with no size columns has nothing to make a per-size BOM from.
    sizes = _run("bom_from_pack.py", ["--pack", pack] + (["--apply"] if apply else []), timeout=420)
    for name in _NEW_BOMS.findall(sizes.get("out") or ""):
        for one in re.split(r"[,\s]+", name.strip()):
            if one.startswith(("BOM-", "BOM")):
                refs.append({"doctype": "BOM", "name": one.strip().rstrip(",")})
    notes.append(f"bom_from_pack.py → {'ok' if sizes['ok'] else 'refused'}")
    if sizes["out"]:
        notes.append(_tail(sizes["out"]))

    return {"ok": True, "refs": refs, "note": "\n\n".join(notes)[:3500]}
