"""Structural guardrails of the Arinox layer. Run from backend/: python3 tests/test_pipeline_guard.py"""
import os, re, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
N = {"ok": 0, "bad": 0}


def check(label, cond, extra=""):
    N["ok" if cond else "bad"] += 1
    if not cond:
        print("  FAIL", label, extra)


def src(rel):
    return open(os.path.join(HERE, rel)).read()


NEW = ["cx_users.py", "cortex_api.py", "pipeline.py", "changefeed.py", "guardrails.py", "docs.py", "catalog.py", "inquiry_v2.py",
       "models_cx.py", "order_flow.py", "order_api.py", "order_samples.py", "order_materials.py", "allocation.py", "order_alloc.py", "tna_plan.py", "models_tna.py"] + [f"tsr/{f}" for f in os.listdir(os.path.join(HERE, "tsr")) if f.endswith(".py")]
for m in NEW:
    check(f"config discipline: {m} has no os.environ", "os.environ" not in src(m))

# 1 · only the journal calls ERP write primitives on a backend
WRITE_CALL = re.compile(r"\b(?:backend|be|b)\.(insert|save|submit|cancel|delete|set_value)\(")
for m in NEW:
    if m in ("tsr/journal.py", "tsr/backend.py", "tsr/fake.py", "tsr/compat.py"):
        continue
    hits = WRITE_CALL.findall(src(m))
    check(f"single write path: {m} never writes through a backend directly", not hits, hits)

# 2 · the legacy ERP write primitives are not used by any new module
for m in NEW:
    check(f"no legacy primitive in {m}", not re.search(r"erp\.erp_(create|update|delete|submit|cancel)\(", src(m)))

# 3 · frontend talks to the middleware only (appster non-negotiable)
fe = os.path.join(os.path.dirname(HERE), "frontend", "src")
bad = []
for root, _, files in os.walk(fe):
    for f in files:
        if f.endswith((".ts", ".tsx")):
            t = open(os.path.join(root, f)).read()
            for m in re.finditer(r"""(?:fetch|axios\.\w+|XMLHttpRequest)\s*\(\s*[`'"](https?://[^`'"]+)""", t):
                bad.append((f, m.group(1)))
            if re.search(r"localhost:\d{2,5}", t):
                bad.append((f, "localhost"))
check("frontend: no direct URL calls", not bad, bad)

# 4 · every public function is documented (the platform builds its allowlist from document.md headings)
sys.path.insert(0, HERE)
import cortex_api
doc = src("document.md")
import deal_api, order_api, order_samples, order_materials
missing = [n for n in list(cortex_api.FUNCTIONS) + list(deal_api.FUNCTIONS) + list(order_api.FUNCTIONS) + list(order_samples.FUNCTIONS) + list(order_materials.FUNCTIONS) if f"### `{n}`" not in doc]
check("document.md lists every Arinox function", not missing, missing)

# 5 · every Arinox function except the ERP/identity entry points starts from an identity
for n, fn in cortex_api.FUNCTIONS.items():
    if n in cortex_api.PUBLIC:
        continue
    code = fn.__code__.co_names + fn.__code__.co_varnames if hasattr(fn, "__code__") else ()
    guarded = fn.__closure__ is not None or "require" in code or n.startswith(("kogo_", "list_tower", "set_tower")) or n == "sync_changes"
    check(f"{n} is guarded", guarded)

# 6 · vendored scripts match the bundle they came from
import hashlib, json
vend = os.path.join(HERE, "tsr", "vendor")
sums = json.load(open(os.path.join(vend, "CHECKSUMS.json")))
recs = json.load(open(os.path.join(vend, "server_scripts.json")))["records"]
drift = [r["name"] for r in recs if sums.get(r["name"]) != hashlib.sha256(r["script"].encode()).hexdigest()]
check("vendored scripts match their checksums", not drift, drift[:5])
bundle = os.path.join(os.path.dirname(os.path.dirname(HERE)), "arinox-apparel", "hosted_bundle", "17_server_scripts.json")
if os.path.exists(bundle):
    b = {r["name"]: hashlib.sha256(r["script"].encode()).hexdigest() for r in json.load(open(bundle))["records"]}
    check("vendored scripts equal the repo bundle (no drift)", {k: v for k, v in b.items()} == {r["name"]: sums[r["name"]] for r in recs}, "re-run tools/vendor_scripts.py")

# 7 · every Arinox script's SQL is understood: no query string the SQL layer cannot translate
import tsr.sql as tsql
qs = 0
for r in recs:
    for m in re.finditer(r"frappe\.db\.sql\(", r["script"]):
        qs += 1
check("the vendored scripts contain SQL (inlined libraries repeat queries)", qs >= 60, qs)

print(f"\n{'✅' if not N['bad'] else '❌'} {N['ok']} assertions passed, {N['bad']} failed")
sys.exit(1 if N["bad"] else 0)
