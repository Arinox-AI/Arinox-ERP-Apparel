def main(filters):

    def execute(filters):
        filters = filters
        to_date = frappe.utils.getdate(filters.to_date or frappe.utils.nowdate())
        from_date = frappe.utils.getdate(filters.from_date or frappe.utils.add_days(to_date, -6))
        columns = [{'fieldname': 'line', 'label': 'Line', 'fieldtype': 'Link', 'options': 'Workstation', 'width': 160}, {'fieldname': 'style_no', 'label': 'Style', 'fieldtype': 'Data', 'width': 120}, {'fieldname': 'production_card', 'label': 'Production Card', 'fieldtype': 'Link', 'options': 'Production Card', 'width': 130}, {'fieldname': 'loaded', 'label': 'Loaded in Period', 'fieldtype': 'Int', 'width': 120}, {'fieldname': 'cumulative', 'label': 'Cumulative', 'fieldtype': 'Int', 'width': 100}, {'fieldname': 'note', 'label': 'Note', 'fieldtype': 'Data', 'width': 200}]
        cond = ''
        args = {'f': from_date, 't': to_date}
        if filters.line:
            cond += ' and m.line = %(line)s'
            args['line'] = filters.line
        if filters.production_card:
            cond += ' and m.production_card = %(production_card)s'
            args['production_card'] = filters.production_card
        rows = frappe.db.sql(f"select m.line, c.style_no, m.production_card,\n    \t\tsum(case when m.posting_date between %(f)s and %(t)s then m.qty else 0 end) loaded, sum(case when m.posting_date <= %(t)s then m.qty else 0 end) cumulative\n    \t\tfrom `tabProduction Movement` m join `tabProduction Card` c on c.name = m.production_card\n    \t\twhere m.stage = 'SEW_IN' and m.line is not null{cond} group by m.line, m.production_card order by m.line, c.style_no", args, as_dict=True)
        return (columns, [r for r in rows if r.loaded or r.cumulative])
    return execute(filters)
data = list(main(filters))
