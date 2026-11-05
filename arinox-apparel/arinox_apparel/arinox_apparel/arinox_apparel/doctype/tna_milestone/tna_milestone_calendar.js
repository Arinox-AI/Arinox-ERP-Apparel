// Calendar and Gantt views for the T&A milestones (shipped with the app; no server access needed).
frappe.views.calendar["TNA Milestone"] = {
	field_map: { start: "planned_start", end: "planned_date", id: "name", title: "label", allDay: "allDay", progress: "progress" },
	gantt: true,
	order_by: "planned_start",
	get_events_method: "arinox_apparel.arinox_apparel.doctype.tna_milestone.tna_milestone.get_events",
};
