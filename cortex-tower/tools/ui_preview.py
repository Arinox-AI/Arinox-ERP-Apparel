#!/usr/bin/env python3
"""Dev tool: serve the built index.html against a MOCK API and take screenshots at phone / tablet / desktop sizes.

    python3 tools/ui_preview.py [outdir]          (needs: playwright + a Chromium; no ERP, no network)

The mock answers only what the new screens ask. It exists so the layout can be looked at, not to test the backend.
"""
import json, os, sys, threading, http.server, socketserver
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
import catalog

OUT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/ui_shots"
os.makedirs(OUT, exist_ok=True)
FIELDS = [
    {"fieldname": "customer", "label": "Customer", "fieldtype": "Link", "options": "Customer", "reqd": 1, "in_list_view": 1},
    {"fieldname": "style_no", "label": "Style no", "fieldtype": "Data", "reqd": 1, "in_list_view": 1},
    {"fieldname": "status", "label": "Status", "fieldtype": "Select", "options": "Draft\nUnder Review\nAccepted\nCancelled", "in_list_view": 1},
    {"fieldname": "season", "label": "Season", "fieldtype": "Data"},
    {"fieldname": "received_on", "label": "Received on", "fieldtype": "Date"},
    {"fieldname": "extracted_by_ai", "label": "Read by AI", "fieldtype": "Check"},
    {"fieldname": "materials", "label": "Materials", "fieldtype": "Table", "options": "Tech Pack Material",
     "columns": [{"fieldname": "description", "label": "Description", "fieldtype": "Data", "reqd": 1}, {"fieldname": "consumption", "label": "Consumption", "fieldtype": "Float"}]},
]
DOC = {"name": "TP-2026-00012", "docstatus": 0, "status": "Under Review", "customer": "ACME Apparel", "style_no": "C9533-U71-725", "season": "SS27",
       "received_on": "2026-11-02", "extracted_by_ai": 1, "modified": "2026-11-05 10:00:00.1",
       "materials": [{"description": "Shell fabric twill 180gsm", "consumption": 1.35}, {"description": "Main label", "consumption": 1}]}
ROWS = [{"name": f"TP-2026-{i:05d}", "customer": c, "style_no": s, "status": st, "docstatus": 0, "modified": "2026-11-05"} for i, (c, s, st) in enumerate(
    [("ACME Apparel", "C9533-U71-725", "Under Review"), ("Aster Oak", "AO-5644", "Accepted"), ("ACME Apparel", "C9112-U71-701", "Draft"), ("North Star", "NS-1180", "Cancelled")], 9)]


def answer(fn, p):
    if fn == "kogo_me":
        return {"authenticated": True, "registered": True, "email": "ajay@arinox.ai", "name": "Ajay", "role": "admin", "is_admin": True, "tower_roles": ["Admin"]}
    if fn == "cx_catalog":
        return {"ok": True, "nav": catalog.NAV, "write_mode": "draft", "me": {}}
    if fn == "cx_nav_counts":
        return {"ok": True, "counts": {"tech_pack": 4, "sales_order": 12, "production_card": 3, "approvals": 2}}
    if fn == "cx_today":
        return {"ok": True, "approvals": 2, "breaches": 1, "sync_failed": 0, "inquiries_waiting": 5, "erp": "up", "overdue_milestones": [
            {"name": "TAM-1", "label": "PP sample approval", "sales_order": "SAL-ORD-2026-00006", "planned_date": "2026-10-28", "department": "Merchandising"},
            {"name": "TAM-2", "label": "Fabric in-house", "sales_order": "SAL-ORD-2026-00009", "planned_date": "2026-11-01", "department": "Purchase"}]}
    if fn == "cx_doc_meta":
        return {"ok": True, "fields": FIELDS, "is_submittable": True, "numbered": True, "can_create": True}
    if fn == "cx_doc_list":
        return {"ok": True, "columns": [{"fieldname": "name", "label": "ID"}, {"fieldname": "customer", "label": "Customer"}, {"fieldname": "style_no", "label": "Style"}, {"fieldname": "status", "label": "Status"}],
                "rows": ROWS, "total": 4, "page": 1}
    if fn == "cx_doc_get":
        return {"ok": True, "doc": DOC, "actions": ["arinox_tech_pack_make_cost_sheet", "arinox_tech_pack_create_style_item"], "can_write": True, "can_submit": True, "can_cancel": True}
    if fn == "cx_write":
        if p.get("preview"):
            return {"ok": True, "class": "draft", "preview": {"class": "draft", "operations": [{"op": "save", "doctype": "Tech Pack", "name": "TP-2026-00012", "changes": {"season": {"from": "SS27", "to": "FW27"}}}], "warnings": [], "scripts": ["a", "b", "c"]}}
        return {"ok": True, "written": ["save Tech Pack TP-2026-00012"], "doc": DOC}
    if fn == "cx_inquiry_queue":
        return {"ok": True, "mails": [{"id": 1, "subject": "RFQ C9533-U71-725 polo shirt", "from": "jane@acme-apparel.com", "received_at": "2026-11-05 09:00:00", "attachments": 2, "analysed": True, "score": 78},
                                      {"id": 2, "subject": "Enquiry - jackets", "from": "buyer@northstar.com", "received_at": "2026-11-04 14:00:00", "attachments": 0, "analysed": False}]}
    if fn == "cx_inquiry_analyse":
        return {"ok": True, "mail": {"subject": "RFQ C9533-U71-725 polo shirt", "from": "jane@acme-apparel.com"}, "classification": {"type": "new_inquiry"},
                "completeness": {"score": 78, "have": ["Style reference", "Quantity", "Sizes", "BOM"], "missing": ["Delivery date", "Artwork"], "note": "A missing BOM or tech pack is normal."},
                "fields": {"style_refs": {"value": ["C9533-U71-725"], "confidence": "high"}, "quantity": {"value": 12000, "confidence": "high"}, "sizes": {"value": "S-XXL", "confidence": "high"},
                           "delivery_date": {"value": "03/04/2027", "confidence": "low", "ambiguous": True}, "bom": {"value": [], "confidence": "high", "rows": 6}},
                "parts": [{"filename": "bom.xlsx", "ok": True, "chars": 2200}, {"filename": "photo.jpg", "ok": False, "needs_reading": True, "error": "scan_or_image", "chars": 0}], "needs_reading": ["photo.jpg"], "links": [],
                "steps_done": {}, "proposals": [{"id": "opportunity", "label": "Create the Opportunity", "request": {"op": "insert"}}, {"id": "tech_pack", "label": "Start a Tech Pack from it", "request": {"op": "api"}, "needs": "opportunity"},
                                              {"id": "ask_buyer", "label": "Draft a reply asking the buyer for: Delivery date, Artwork", "request": None, "reply_draft": "x"}]}
    if fn == "cx_reports":
        return {"ok": True, "reports": [{"name": "Sewing WIP", "ref_doctype": "Line Input", "filters": []}]}
    if fn == "cx_report_run":
        return {"ok": True, "name": "Sewing WIP", "columns": [{"label": "Line", "fieldname": "line"}, {"label": "Style", "fieldname": "style_no"}, {"label": "Loaded", "fieldname": "loaded"}, {"label": "Sewn", "fieldname": "sewn"}, {"label": "WIP", "fieldname": "wip"}],
                "rows": [{"line": f"L{i}", "style_no": "C9533", "loaded": 1200 + i, "sewn": 900 + i * 7, "wip": 300 - i} for i in range(1, 15)], "truncated": False, "ms": 120}
    if fn == "cx_approvals":
        return {"ok": True, "can_decide": True, "approvals": [{"id": 1, "requester": "sam@x.com", "class": "risky", "reason": "cancel Delivery Note DN-0007", "status": "pending", "created_at": "2026-11-06 08:00:00", "preview": {"operations": [{"op": "cancel", "doctype": "Delivery Note", "name": "DN-0007"}], "note": "Cancelling reverses the stock entries."}}]}
    if fn == "cx_runs":
        return {"ok": True, "runs": [{"id": 3, "actor": "ann@x.com", "op": "submit", "doctype": "Tech Pack", "name": "TP-1", "status": "done", "started_at": "2026-11-06 07:00:00"}]}
    if fn == "cx_sync_status":
        return {"ok": True, "queue": {"new": 3, "failed": 0, "done": 120}, "breaches_open": 1, "webhook_configured": False, "doctypes": []}
    if fn == "cx_breaches":
        return {"ok": True, "breaches": [{"id": 1, "doctype": "Work Order", "name": "WO-12", "script": "x", "message": "Bulk gate: PP meeting missing for Navy", "state": "open"}]}
    if fn == "tsr_status":
        return {"ok": True, "rules_off": False, "count": 251, "vendor": {"ok": True, "scripts": 251}, "scripts": [{"name": f"arinox_script_{i}", "type": "DocType Event", "doctype": "Tech Pack", "event": "Before Save", "enabled": True, "runs": i * 3, "failures": 0, "avg_ms": 40} for i in range(12)]}
    if fn == "list_tower_users":
        return {"ok": True, "all_roles": ["Merchandiser", "Costing", "Planner", "Management", "Admin"], "users": [{"email": "ajay@arinox.ai", "name": "Ajay", "is_admin": True, "roles": ["Admin"], "erp_user": "", "active": True}, {"email": "sam@x.com", "name": "Sam", "is_admin": False, "roles": [], "erp_user": "", "active": True}]}
    if fn == "sync_changes":
        return {"ok": True, "poll": {"polled": 6}}
    if fn == "cx_search":
        return {"ok": True, "results": [{"doctype": "Sales Order", "name": "SAL-ORD-2026-00006"}, {"doctype": "Tech Pack", "name": "TP-2026-00012"}]}
    if fn == "cx_link_search":
        return {"ok": True, "results": [{"value": "ACME Apparel", "description": ""}]}
    return {"ok": False, "error": "mock: " + fn}


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        path = os.path.join(ROOT, "index.html") if self.path.split("?")[0] in ("/", "/index.html") else None
        if self.path.startswith("/config.js"):
            body = b"window.APP_CONFIG={API_BASE:'/api',API_HEALTH:'/health',PROJECT:'p',AGENT_ID:'a',DEPLOYMENT_ID:'d',SWARM_ID:'s',ORIGIN_ID:'o',USER_ID:'u'};"
            ct = "text/javascript"
        elif path:
            body, ct = open(path, "rb").read(), "text/html"
        else:
            self.send_response(404); self.end_headers(); return
        self.send_response(200); self.send_header("Content-Type", ct); self.end_headers(); self.wfile.write(body)
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0)); req = json.loads(self.rfile.read(n) or b"{}")
        data = answer(req.get("function"), req.get("params") or {})
        body = json.dumps({"success": True, "data": data}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)


def main():
    from playwright.sync_api import sync_playwright
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), H); srv.daemon_threads = True
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    exe = None
    base = os.path.expanduser("~/.cache/ms-playwright")
    for d in sorted(os.listdir(base)):
        for cand in (f"{base}/{d}/chrome-linux/chrome", f"{base}/{d}/chrome-linux/headless_shell", f"{base}/{d}/chrome-headless-shell-linux64/chrome-headless-shell"):
            if os.path.exists(cand): exe = cand
    sizes = {"phone": (390, 844, 3), "tablet": (820, 1180, 2), "desktop": (1440, 900, 1)}
    shots = [("boot", "#/today", "boot"), ("today", "#/today", None), ("list", "#/tech_pack", None), ("doc", "#/tech_pack", "open_doc"),
             ("inquiries", "#/inquiries", None), ("inquiry", "#/inquiries", "open_inq"), ("report", "#/r_sewing_wip", None), ("approvals", "#/approvals", None),
             ("sync", "#/sync", None), ("tsr", "#/tsr", None), ("menu", "#/today", "menu")]
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe, args=["--no-sandbox"])
        for dev, (w, h, dpr) in sizes.items():
            for dark in (True,):
                ctx = b.new_context(viewport={"width": w, "height": h}, device_scale_factor=dpr, has_touch=dev != "desktop", is_mobile=dev == "phone", color_scheme="dark")
                pg = ctx.new_page()
                errs = []
                pg.on("pageerror", lambda e: errs.append(str(e)))
                pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
                pg.add_init_script("window.postMessage({type:'KOGO_AUTH',jwt:'x'},'*')")
                for name, hash_, act in shots:
                    pg.goto(f"http://127.0.0.1:{port}/{hash_}")
                    pg.evaluate("window.postMessage({type:'KOGO_AUTH',jwt:'x'},'*')")
                    if act == "boot":
                        pg.wait_for_timeout(420)
                        pg.screenshot(path=f"{OUT}/{dev}-{name}.png")
                        continue
                    try:
                        pg.wait_for_selector(".cx-app .cx-page", timeout=15000)
                    except Exception:
                        errs.append(f"{name}: shell did not appear")
                    pg.wait_for_timeout(900)
                    try:
                        if act == "open_doc": pg.get_by_text("TP-2026-00009").first.click(); pg.wait_for_timeout(700)
                        elif act == "review": pg.get_by_text("TP-2026-00009").first.click(); pg.wait_for_timeout(500); pg.get_by_role("button", name="Edit").first.click(); pg.wait_for_timeout(500); pg.get_by_label("Season").fill("FW27") if False else None
                        elif act == "new": pg.get_by_role("button", name="New").first.click(); pg.wait_for_timeout(700)
                        elif act == "open_inq": pg.get_by_text("RFQ C9533").first.click(); pg.wait_for_timeout(900)
                        elif act == "menu": pg.get_by_label("Open work areas").first.click(); pg.wait_for_timeout(600)
                    except Exception as e:
                        errs.append(f"{name}: {e}"[:160])
                    pg.screenshot(path=f"{OUT}/{dev}{'-dark' if dark else ''}-{name}.png")
                if errs:
                    print(dev, "dark" if dark else "", "console:", sorted(set(errs))[:5])
                ctx.close()
        b.close()
    print("screenshots in", OUT)


if __name__ == "__main__":
    main()
