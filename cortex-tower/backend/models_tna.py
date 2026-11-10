"""The tower's own T&A tables (TNA plan section 5.2): immutable baselines and re-plan revisions. The ERP holds the plan itself
(`Order TNA`, `TNA Milestone`); these two tables keep what the ERP has no place for: every baseline version, kept forever, and every
move after the lock with its reason, party and approver."""

import json as _json
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from models import Base


class PlanBaselineModel(Base):
    __tablename__ = "tna_plan_baseline"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_tna: Mapped[str] = mapped_column(String(80), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    locked_by: Mapped[str] = mapped_column(String(120), default="")
    locked_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    ex_factory: Mapped[str] = mapped_column(String(12), default="")
    feasible: Mapped[int] = mapped_column(Integer, default=1)
    note: Mapped[str] = mapped_column(Text, default="")
    rows_json: Mapped[str] = mapped_column(Text, default="[]")          # every milestone's planned start / finish at the lock

    def rows(self) -> list:
        try:
            return _json.loads(self.rows_json or "[]")
        except ValueError:
            return []


class PlanRevisionModel(Base):
    __tablename__ = "tna_plan_revision"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_tna: Mapped[str] = mapped_column(String(80), index=True)
    baseline_version: Mapped[int] = mapped_column(Integer, default=1)
    code: Mapped[str] = mapped_column(String(60), default="")
    old_date: Mapped[str] = mapped_column(String(12), default="")
    new_date: Mapped[str] = mapped_column(String(12), default="")
    reason_code: Mapped[str] = mapped_column(String(20), default="")      # the ERP's own five: Buyer, Supplier, Factory, Logistics, Other
    reason_note: Mapped[str] = mapped_column(Text, default="")
    actor: Mapped[str] = mapped_column(String(120), default="")
    approved_by: Mapped[str] = mapped_column(String(120), default="")
    ship_impact_wd: Mapped[int] = mapped_column(Integer, default=0)
    moves_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
