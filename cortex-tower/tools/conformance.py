#!/usr/bin/env python3
"""Run the repo's hosted tests THROUGH the Tower Script Runtime against a real (test) ERPNext site.

The ERP's own Server Scripts must be OFF on that site (``bench --site <site> set-config server_script_enabled 0``),
otherwise every script would run twice. Each test gets a fresh journal; whatever it created is undone afterwards.

    python3 tools/conformance.py [--only group_or_test] [--base http://hosted.localhost:8001] [--list]

Needs: ARINOX_API_TOKEN or ~/.arinox_hosted_token ("key:secret"), and the repo's hosted tests on the path.
"""
import argparse, importlib, os, pkgutil, sys, time, traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "backend"))
APP = os.path.join(os.path.dirname(ROOT), "arinox-apparel", "arinox_apparel")
sys.path.insert(0, APP)

from tsr import compat                                  # noqa: E402
from tsr.backend import HttpBackend                     # noqa: E402
from tsr.runner import Context, Engine, Registry        # noqa: E402


def drain(every_s=0):
    """ERPNext queues background jobs for every write; the site refuses new writes at 600 queued (HTTP 503)."""
    import subprocess
    bench = os.environ.get("BENCH_DIR", "/workspaces/frappe-bench")
    site = os.environ.get("BENCH_SITE", "hosted.localhost")
    try:
        subprocess.run(["bench", "--site", site, "worker", "--burst"], cwd=bench, capture_output=True, timeout=240)
    except Exception as e:
        print("        (drain failed:", e, ")", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://hosted.localhost:8001")
    ap.add_argument("--only")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--skip", default="")
    a = ap.parse_args()
    token = os.environ.get("ARINOX_API_TOKEN") or open(os.path.expanduser("~/.arinox_hosted_token")).read().strip()
    backend = HttpBackend(a.base, token)
    engine = Engine(Registry.load())
    ctx_box = {}

    def make_ctx():
        return Context(backend, engine, user="Administrator", roles=[], mode="live")
    compat.install(engine, backend, make_ctx)

    from arinox_apparel.portable.hosted_tests import harness   # imports the stub `frappe`
    pkg = importlib.import_module("arinox_apparel.portable.hosted_tests")
    for m in pkgutil.iter_modules(pkg.__path__):
        if m.name.startswith("test_"):
            importlib.import_module(f"arinox_apparel.portable.hosted_tests.{m.name}")

    skip = {s for s in a.skip.split(",") if s}
    todo = [(g, n, fn) for g, n, fn in harness.TESTS if not a.only or a.only in (g, n)]
    todo = [t for t in todo if t[1] not in skip and t[0] not in skip]
    if a.list:
        for g, n, _ in todo:
            print(g, n)
        return
    passed, failed, unsupported = 0, [], []
    t0 = time.time()
    for i, (g, n, fn) in enumerate(todo):
        if i and i % 6 == 0:
            drain()
        compat.S.ctx = make_ctx()
        compat._local.form_dict.clear()
        t1 = time.time()
        try:
            fn()
            passed += 1
            print(f"  ok    {g}.{n}  ({time.time() - t1:.1f}s)", flush=True)
        except Exception as e:
            from tsr.errors import TSRUnsupported
            kind = "UNSUP" if isinstance(e, TSRUnsupported) else "FAIL "
            (unsupported if kind == "UNSUP" else failed).append((g, n, f"{type(e).__name__}: {str(e)[:300]}"))
            print(f"  {kind} {g}.{n}: {type(e).__name__}: {str(e)[:260]}", flush=True)
            if os.environ.get("TSR_TRACE"):
                traceback.print_exc()
        finally:
            compat.S.ctx.user = "Administrator"
            undo = compat.S.ctx.sink.compensate()
            if undo["failed"]:
                print(f"        cleanup failed: {undo['failed'][:3]}", flush=True)
    print(f"RESULT passed {passed} failed {len(failed)} unsupported {len(unsupported)} of {len(todo)}  in {time.time() - t0:.0f}s")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
