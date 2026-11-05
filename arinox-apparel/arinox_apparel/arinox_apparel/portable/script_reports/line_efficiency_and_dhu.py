def main(filters):

    def execute(filters):
        filters = filters
        to_date = frappe.utils.getdate(filters.to_date or frappe.utils.nowdate())
        from_date = frappe.utils.getdate(filters.from_date or frappe.utils.add_days(to_date, -6))
        columns = [{'fieldname': 'report_date', 'label': 'Date', 'fieldtype': 'Date', 'width': 95}, {'fieldname': 'line', 'label': 'Line', 'fieldtype': 'Link', 'options': 'Workstation', 'width': 160}, {'fieldname': 'operators', 'label': 'Operators', 'fieldtype': 'Int', 'width': 85}, {'fieldname': 'output', 'label': 'Output', 'fieldtype': 'Int', 'width': 80}, {'fieldname': 'target', 'label': 'Target', 'fieldtype': 'Float', 'precision': 1, 'width': 80}, {'fieldname': 'variance', 'label': 'vs Target', 'fieldtype': 'Float', 'precision': 1, 'width': 85}, {'fieldname': 'efficiency', 'label': 'Efficiency %', 'fieldtype': 'Percent', 'width': 100}, {'fieldname': 'learning', 'label': 'Day on Line', 'fieldtype': 'Int', 'width': 90}, {'fieldname': 'checked', 'label': 'Checked', 'fieldtype': 'Int', 'width': 80}, {'fieldname': 'dhu', 'label': 'DHU', 'fieldtype': 'Float', 'precision': 2, 'width': 70}, {'fieldname': 'rft', 'label': 'RFT %', 'fieldtype': 'Percent', 'width': 80}, {'fieldname': 'downtime', 'label': 'Downtime (min)', 'fieldtype': 'Int', 'width': 110}]
        cond = ''
        args = {'f': from_date, 't': to_date}
        if filters.line:
            cond = ' and d.line = %(line)s'
            args['line'] = filters.line
        rows = frappe.db.sql(f'select d.report_date, d.line, d.operators_present operators, d.total_output output, d.target_qty target, d.variance_to_target variance,\n    \t\td.efficiency_pct efficiency, d.learning_day learning, d.downtime_minutes downtime from `tabDaily Line Report` d\n    \t\twhere d.docstatus = 1 and d.report_date between %(f)s and %(t)s{cond} order by d.report_date desc, d.line', args, as_dict=True)
        for r in rows:
            q = frappe.db.sql("select ifnull(sum(total_checked), 0), ifnull(sum(total_passed), 0), ifnull(sum(total_defects), 0) from `tabLine QC Report` where docstatus = 1 and line = %s and report_date = %s and audit_type = 'End-line'", (r.line, r.report_date))[0]
            r.checked = q[0]
            r.dhu = round(q[2] * 100 / q[0], 2) if q[0] else None
            r.rft = round(q[1] * 100 / q[0], 2) if q[0] else None
        return (columns, rows)
    return execute(filters)
data = list(main(filters))
