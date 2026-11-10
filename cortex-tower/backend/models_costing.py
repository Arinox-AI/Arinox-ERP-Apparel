"""The costing sheet — a document the tower owns, not a file it borrows.

A factory costs a style in a standard worksheet long before the ERP is involved: raw materials with a usage per piece, a
wastage, a rate; the fabric export/import cost per metre; the processing charges (making/CMT, washing, printing,
embroidery, testing); the percentage expenses (rejection, financing, banking, freight, overheads, buying agent
commission); profit; FOB per piece in USD and in local currency; the order value.

That worksheet is **APPAREL_COSTING_DETAILED_REVISED.xlsx**, sheet ``DETAILED COSTING`` (the factory's own template, kept
in the user's Drive). :data:`TEMPLATE` below is that page, line for line and in the same order, so the app's sheet and the
merchandiser's spreadsheet are the same document.

This module is that sheet, **inside the app**:

* it is **already there** — opening a style's costing sheet seeds it from :data:`TEMPLATE` with the style's order quantity,
  pcs per carton and the material lines the buyer's BOM already gave us, so there is never an empty page to fill in;
* **anything the template does not have can still be added by hand** on the page (a fusing, an extra trim, a line only
  this style needs) and it stays on the sheet;
* the **rules are the app's own** (:func:`costing_sheet.compute`) — usage × (1 + wastage) × rate per material, the fabric
  export/import lines priced on the total fabric metres, carton at 1 per pcs-per-carton, percentages on the product cost,
  profit on the total cost, FOB in USD and in VND, order value;
* it is **saved in the database** per style, so a person can leave it, come back, and tweak a price;
* and **one click transfers the prices** into the ERP Cost Sheet (:func:`costing_sheet.transfer`), which stays a draft for
  the ERP's own rules and a person's last look.

The ERP is still the system of record for the *price*. The sheet is where the numbers are worked out.
"""

import json as _json
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from models import Base

#: The sheet's rules, in the order a costing is read out loud.
KINDS = ("material", "processing", "expense")

#: A line whose ``rule`` is set has its own usage, worked out by the sheet instead of typed:
#:
#: ``per_carton``     one carton per ``pcs_per_carton`` pieces (the workbook's ``=1/G9``)
#: ``fabric_metres``  the total fabric metres including wastage (the workbook's ``=C17*(1+E17)+C18*(1+E18)``)
RULES = ("per_carton", "fabric_metres")

#: The standard sheet — APPAREL_COSTING_DETAILED_REVISED.xlsx, sheet "DETAILED COSTING", line for line.
#:
#: ``tpl`` is the slot. It is what the app matches a stored line to, so renaming a line on screen does not lose its place
#: and the four OTHERS rows stay four rows. ``from_bom`` are the words/type a buyer's BOM line is matched by; ``share`` is
#: the template's own percentage (the policy the workbook starts from, not a price someone typed); ``apply_default`` is
#: the workbook's APPLY 1/0 column.
#:
#: ``usage_default`` / ``wastage_default`` / ``rate_default`` are the **working figures the workbook itself carries** — the
#: rate on every line (main fabric 3.000 a metre, main label 0.050, making 5.000 …) and the usage of the lines a buyer's
#: BOM does not speak about (hang tag 2, tissue 6, thread 200 …). A sheet opens the way the spreadsheet does instead of
#: opening at zero, and the merchandiser changes only what is different for this style. They are only ever used to fill a
#: blank: a usage from the buyer's BOM, and anything a person typed (a deliberate 0 included), always wins.
TEMPLATE: list[dict] = [
    # ── RAW MATERIALS (workbook rows 17-34, SNO 1-15) ──────────────────────────────────────────────
    {"tpl": "M01", "kind": "material", "label": "MAIN FABRIC", "material_type": "Fabric", "uom": "MTR",
     "from_bom": ("self", "shell", "body"),
     "usage_default": 0.600, "wastage_default": 0.05, "rate_default": 3.000},
    {"tpl": "M02", "kind": "material", "label": "TRIM / CONTRAST FABRIC", "material_type": "Contrast Fabric", "uom": "MTR",
     "from_bom": ("contrast", "content", "combo", "trim fabric", "lining"),
     "usage_default": 0.600, "wastage_default": 0.05, "rate_default": 3.000},
    {"tpl": "M03", "kind": "material", "label": "FABRIC EXPORT COST PER METER", "material_type": "Other", "uom": "MTR",
     "rule": "fabric_metres", "cost_head": "Fabric Export Cost", "rate_default": 0.250},
    {"tpl": "M04", "kind": "material", "label": "FABRIC IMPORT COST PER METER", "material_type": "Other", "uom": "MTR",
     "rule": "fabric_metres", "cost_head": "Fabric Import Cost", "rate_default": 0.250},
    {"tpl": "M05", "kind": "material", "label": "MAIN LABEL", "material_type": "Label", "uom": "PCS",
     "from_bom": ("main label", "label"), "usage_default": 1.000, "rate_default": 0.050},
    {"tpl": "M06", "kind": "material", "label": "WASH CARE LABEL", "material_type": "Label", "uom": "PCS",
     "from_bom": ("care label", "care"), "usage_default": 1.000, "rate_default": 0.050},
    {"tpl": "M07", "kind": "material", "label": "HANG TAG", "material_type": "Label", "uom": "PCS",
     "from_bom": ("hang", "tag"), "usage_default": 2.000, "rate_default": 0.050},
    {"tpl": "M08", "kind": "material", "label": "POLY BAG", "material_type": "Packaging", "uom": "PCS",
     "from_bom": ("poly", "bag"), "usage_default": 1.000, "rate_default": 0.050},
    {"tpl": "M09", "kind": "material", "label": "TISSUE PAPER", "material_type": "Packaging", "uom": "PCS",
     "from_bom": ("tissue",), "usage_default": 6.000, "rate_default": 0.020},
    {"tpl": "M10", "kind": "material", "label": "THREAD", "material_type": "Thread", "uom": "MTR",
     "from_bom": ("thread",), "usage_default": 200.000, "rate_default": 0.001},
    {"tpl": "M11", "kind": "material", "label": "CARTON", "material_type": "Packaging", "uom": "PCS",
     "from_bom": ("carton",), "rule": "per_carton", "rate_default": 0.150},
    {"tpl": "M12", "kind": "material", "label": "TAPE", "material_type": "Packaging", "uom": "MTR",
     "from_bom": ("tape",), "usage_default": 0.500, "rate_default": 0.100},
    {"tpl": "M13", "kind": "material", "label": "ZIPPER", "material_type": "Trim", "uom": "PCS",
     "from_bom": ("zip",), "usage_default": 1.000, "rate_default": 0.100},
    {"tpl": "M14", "kind": "material", "label": "BUTTON", "material_type": "Trim", "uom": "PCS",
     "from_bom": ("button",), "usage_default": 1.000, "rate_default": 0.100},
    {"tpl": "M15", "kind": "material", "label": "OTHERS", "material_type": "Other", "uom": "PCS",
     "usage_default": 0.010, "rate_default": 0.300},
    {"tpl": "M16", "kind": "material", "label": "OTHERS", "material_type": "Other", "uom": "PCS",
     "usage_default": 0.010, "rate_default": 0.300},
    {"tpl": "M17", "kind": "material", "label": "OTHERS", "material_type": "Other", "uom": "PCS",
     "usage_default": 0.010, "rate_default": 0.300},
    {"tpl": "M18", "kind": "material", "label": "OTHERS", "material_type": "Other", "uom": "PCS",
     "usage_default": 0.010, "rate_default": 0.300},
    # ── PROCESSING CHARGES (workbook rows 38-42, APPLY 1/0) ────────────────────────────────────────
    {"tpl": "P01", "kind": "processing", "label": "MAKING CHARGES (CMT)", "cost_head": "Stitching (CMT)",
     "apply_default": True, "rate_default": 5.000},
    {"tpl": "P02", "kind": "processing", "label": "WASHING CHARGES", "apply_default": False, "cost_head": "Washing",
     "rate_default": 0.500},
    {"tpl": "P03", "kind": "processing", "label": "PRINTING CHARGES", "apply_default": False, "cost_head": "Printing"},
    {"tpl": "P04", "kind": "processing", "label": "EMBROIDERY / EMBELLISHMENT", "apply_default": False, "cost_head": "Embellishment"},
    {"tpl": "P05", "kind": "processing", "label": "TESTING & INSPECTION", "apply_default": False, "cost_head": "Testing"},
    # ── OTHER EXPENSES, % OF PRODUCT COST (workbook rows 47-52) ────────────────────────────────────
    {"tpl": "E01", "kind": "expense", "label": "REJECTION", "cost_head": "Rejection Allowance", "share": True,
     "share_default": 0.03},
    {"tpl": "E02", "kind": "expense", "label": "FINANCING", "cost_head": "Finance", "share": True, "share_default": 0.01},
    {"tpl": "E03", "kind": "expense", "label": "BANKING", "cost_head": "Bank Charges", "share": True,
     "share_default": 0.01},
    {"tpl": "E04", "kind": "expense", "label": "FREIGHT / LOCAL CHARGES TO FOB PORT", "cost_head": "Freight",
     "share": True, "share_default": 0.02},
    {"tpl": "E05", "kind": "expense", "label": "OVERHEADS", "cost_head": "Overhead", "share": True,
     "share_default": 0.15},
    {"tpl": "E06", "kind": "expense", "label": "BUYING AGENT COMMISSION", "cost_head": "Buying Agent Commission",
     "share": True, "share_default": 0.0},
    # ── PROFIT (workbook row 55: % on the total cost) ──────────────────────────────────────────────
    {"tpl": "E07", "kind": "expense", "label": "PROFIT (% ON COST)", "cost_head": "Profit", "share": True,
     "share_default": 0.15, "profit": True},
]

#: The workbook's four sign-off boxes, in order. Stored per sheet as JSON.
SIGNOFF_ROLES = ("FABRIC COST CHECKED BY", "FIRST COSTING DONE BY", "2ND ROUND CHECKED BY",
                 "FINAL CHECKED & APPROVED BY")


class CostingSheetModel(Base):
    """One style's costing sheet: the header block and the rule inputs that are not per line."""

    __tablename__ = "costing_sheet"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    deal_id: Mapped[int] = mapped_column(Integer, index=True)
    style_key: Mapped[str] = mapped_column(String(40), index=True)
    style_no: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    style_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    buyer: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    season: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    factory: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    costing_date: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    order_qty: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pcs_per_carton: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fob_port: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    vnd_per_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)   # the workbook's local-currency line
    version: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    profit_pct: Mapped[float] = mapped_column(Float, default=0.15)       # % on cost, like the standard sheet
    signoffs: Mapped[str] = mapped_column(Text, default="{}")            # {role: {"name": ..., "date": ...}}
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # where the numbers first came from, when they were imported from a sheet someone sent
    imported_from: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    totals: Mapped[str] = mapped_column(Text, default="{}")             # last computed totals (JSON)
    transferred_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    def totals_dict(self) -> dict:
        try:
            return _json.loads(self.totals or "{}")
        except Exception:
            return {}

    def signoffs_dict(self) -> dict:
        try:
            data = _json.loads(self.signoffs or "{}")
        except Exception:
            data = {}
        return {role: (data.get(role) or {}) for role in SIGNOFF_ROLES}

    def to_dict(self) -> dict:
        return {"id": self.id, "deal_id": self.deal_id, "style_key": self.style_key, "style_no": self.style_no,
                "style_name": self.style_name, "buyer": self.buyer, "season": self.season, "factory": self.factory,
                "costing_date": self.costing_date, "currency": self.currency, "order_qty": self.order_qty,
                "pcs_per_carton": self.pcs_per_carton, "fob_port": self.fob_port, "vnd_per_usd": self.vnd_per_usd,
                "version": self.version, "profit_pct": self.profit_pct,
                "signoffs": self.signoffs_dict(), "note": self.note, "imported_from": self.imported_from,
                "totals": self.totals_dict(),
                "transferred_at": self.transferred_at.isoformat() if self.transferred_at else None,
                "updated_at": self.updated_at.isoformat() if self.updated_at else None}


class CostingLineModel(Base):
    """One line of the sheet: a material, a processing charge, or a percentage expense."""

    __tablename__ = "costing_line"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sheet_id: Mapped[int] = mapped_column(Integer, index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    #: which template slot this line is. ``None`` = a line somebody added by hand (kept, never reordered away).
    tpl: Mapped[Optional[str]] = mapped_column(String(40), nullable=True, index=True)
    #: the BOM item this line covers (the buyer's own item code and description), so a price typed here is stored
    #: against that item and can be put on the BOM with one click.
    item_code: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    item_desc: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    kind: Mapped[str] = mapped_column(String(16), default="material")      # material | processing | expense
    label: Mapped[str] = mapped_column(String(140), default="")
    material_type: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    cost_head: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    usage: Mapped[Optional[float]] = mapped_column(Float, nullable=True)         # per piece (material)
    uom: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    wastage_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)   # fraction: 0.05 = 5%
    wastage_reason: Mapped[Optional[str]] = mapped_column(String(140), nullable=True)
    rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    share: Mapped[Optional[float]] = mapped_column(Float, nullable=True)         # fraction for a % expense
    apply: Mapped[bool] = mapped_column(Boolean, default=True)                   # carried to the ERP (0 → N/A)
    #: ``per_carton`` or ``fabric_metres``: the sheet works the usage out instead of taking a typed one.
    rule: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    from_fabric: Mapped[bool] = mapped_column(Boolean, default=False)            # kept for old rows
    note: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    @property
    def derived(self) -> bool:
        return bool(self.rule)

    def to_dict(self) -> dict:
        return {"id": self.id, "seq": self.seq, "tpl": self.tpl, "item_code": self.item_code,
                "item_desc": self.item_desc, "kind": self.kind, "label": self.label,
                "material_type": self.material_type, "cost_head": self.cost_head, "usage": self.usage,
                "uom": self.uom, "wastage_pct": self.wastage_pct, "wastage_reason": self.wastage_reason,
                "rate": self.rate, "share": self.share, "apply": bool(self.apply), "rule": self.rule,
                "derived": self.derived, "from_fabric": bool(self.from_fabric), "note": self.note,
                "custom": not bool(self.tpl)}


class ItemPriceModel(Base):
    """What one item costs — the price book.

    The costing sheet says *what item* and *what price*. Once a price is typed on the sheet it is kept here, against the
    item itself (the buyer's item code, or its description when the sheet has no code), so the same price can be put on
    the BOM of the style with one click — and be looked up again next time the same item appears on another style.
    """

    __tablename__ = "item_price"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(240), index=True)      # "code:<item>" when there is a code, else the words
    desc_key: Mapped[Optional[str]] = mapped_column(String(240), nullable=True, index=True)   # the description's words
    item_code: Mapped[Optional[str]] = mapped_column(String(80), nullable=True, index=True)
    description: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    uom: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    rate: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    source: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    def to_dict(self) -> dict:
        return {"id": self.id, "key": self.key, "item_code": self.item_code, "description": self.description,
                "uom": self.uom, "rate": self.rate, "currency": self.currency, "source": self.source,
                "updated_at": self.updated_at.isoformat() if self.updated_at else None}
