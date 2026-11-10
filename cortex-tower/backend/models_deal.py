"""A deal: one buyer conversation followed from the first inquiry to the Sales Order and beyond.

The ERP stays the system of record. A deal keeps what the ERP has no place for while the work is in progress (the
mail thread it lives in, the styles as read from the buyer's mail before they become Tech Packs, the quote e-mail, the
timeline) and the *names* of the ERP documents made from it. Figures that the ERP computes (cost, price, margin) are
read back from the ERP document, never recomputed here.
"""

import json as _json
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from models import Base

#: the stages a deal moves through, in order. ``lost`` can follow any of the first five.
STAGES = ["inquiry", "costing", "quoted", "negotiating", "accepted", "contract", "order"]
STAGE_LABEL = {"inquiry": "Inquiry", "costing": "Costing", "quoted": "Quote sent", "negotiating": "Negotiating",
               "accepted": "Accepted", "contract": "Contract", "order": "Sales order", "lost": "Lost"}


def _loads(txt, default):
    try:
        return _json.loads(txt) if txt else default
    except Exception:
        return default


class DealModel(Base):
    __tablename__ = "deal"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(300), default="")
    stage: Mapped[str] = mapped_column(String(20), default="inquiry", index=True)
    thread_key: Mapped[Optional[str]] = mapped_column(String(320), nullable=True, index=True)
    mail_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    customer: Mapped[Optional[str]] = mapped_column(String(200), nullable=True, index=True)
    customer_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    contact_email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    contact_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    incoterm: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    destination: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    season: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    product_type: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    ex_factory: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    in_warehouse: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    styles: Mapped[str] = mapped_column(Text, default="[]")              # JSON list, see deals.new_style()
    refs: Mapped[str] = mapped_column(Text, default="{}")                # ERP names: opportunity, price_negotiation, …
    contract_draft: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    events: Mapped[str] = mapped_column(Text, default="[]")              # the timeline
    attention: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # what is waiting on us (buyer replied …)
    owner: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    quote_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    buyer_reply_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    def styles_list(self) -> list:
        return _loads(self.styles, [])

    def refs_dict(self) -> dict:
        return _loads(self.refs, {})

    def to_dict(self) -> dict:
        styles = self.styles_list()
        qty = sum(int(s.get("qty") or 0) for s in styles if s.get("status") != "dropped")
        value = 0.0
        for s in styles:
            if s.get("status") == "dropped":
                continue
            price = s.get("agreed_price") or s.get("offer_price") or (s.get("cost") or {}).get("quoted_price") or 0
            value += float(price or 0) * int(s.get("qty") or 0)
        return {
            "id": self.id, "title": self.title, "stage": self.stage, "stage_label": STAGE_LABEL.get(self.stage, self.stage),
            "thread_key": self.thread_key, "mail_id": self.mail_id,
            "customer": self.customer, "customer_name": self.customer_name or self.customer,
            "contact_email": self.contact_email, "contact_name": self.contact_name,
            "currency": self.currency, "incoterm": self.incoterm, "destination": self.destination, "season": self.season,
            "product_type": self.product_type, "ex_factory": self.ex_factory, "in_warehouse": self.in_warehouse,
            "notes": self.notes, "styles": styles, "refs": self.refs_dict(),
            "contract_draft": _loads(self.contract_draft, None), "events": _loads(self.events, []),
            "attention": _loads(self.attention, None), "owner": self.owner,
            "total_qty": qty, "total_value": round(value, 2),
            "quote_sent_at": self.quote_sent_at.isoformat() if self.quote_sent_at else None,
            "buyer_reply_at": self.buyer_reply_at.isoformat() if self.buyer_reply_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
