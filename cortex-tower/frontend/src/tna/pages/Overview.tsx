import HeaderStrip from "../components/HeaderStrip";
import KpiRow from "../components/KpiRow";
import GanttChart from "../components/GanttChart";
import ExceptionPanel from "../components/ExceptionPanel";
import type { TnaCalendar, HolidayCalendar } from "../types";

export default function Overview({
  payload, calendar, onSelect,
}: {
  payload: TnaCalendar;
  calendar: HolidayCalendar | null;
  onSelect: (code: string) => void;
}) {
  const { header, kpis, milestones, exceptions } = payload;
  return (
    <div className="stack">
      <HeaderStrip header={header} />
      <KpiRow
        kpis={kpis}
        orderId={header.order_id}
        calendar={header.calendar || payload.calendar?.calendar || ""}
        asOf={payload.as_of}
      />

      <section className="card" style={{ padding: 0, overflow: "hidden" }}>
        <div style={{ padding: "16px 20px 0" }}>
          <div className="card-head" style={{ marginBottom: 10 }}>
            <div>
              <div className="card-title">Timeline — backward schedule from ship date</div>
              <div className="card-sub">
                {milestones.length} milestones · planned bar + actual bar · critical path highlighted · holiday shading.
                Click a row to open the detail drawer.
              </div>
            </div>
          </div>
        </div>
        <GanttChart
          milestones={milestones}
          calendar={calendar}
          shipDate={header.ship_date}
          asOf={payload.as_of}
          onSelect={onSelect}
        />
      </section>

      <section>
        <div className="card-head">
          <div className="card-title">Top exceptions</div>
          <div className="card-sub">{exceptions.length} total this run — see the Exceptions tab for the full ranked list</div>
        </div>
        <ExceptionPanel exceptions={exceptions.slice(0, 5)} nextAction={kpis.next_action} onSelect={onSelect} />
      </section>
    </div>
  );
}
