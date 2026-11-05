def main(filters):

    def execute(filters):
        filters = filters
        columns = [{'fieldname': 'line', 'label': 'Line', 'fieldtype': 'Link', 'options': 'Workstation', 'width': 160}, {'fieldname': 'production_card', 'label': 'Production Card', 'fieldtype': 'Link', 'options': 'Production Card', 'width': 130}, {'fieldname': 'style_no', 'label': 'Style', 'fieldtype': 'Data', 'width': 110}, {'fieldname': 'colour', 'label': 'Colour', 'fieldtype': 'Data', 'width': 90}, {'fieldname': 'loaded', 'label': 'Loaded', 'fieldtype': 'Int', 'width': 80}, {'fieldname': 'sewn', 'label': 'Sewn', 'fieldtype': 'Int', 'width': 80}, {'fieldname': 'rejected', 'label': 'Rejected', 'fieldtype': 'Int', 'width': 80}, {'fieldname': 'wip', 'label': 'WIP', 'fieldtype': 'Int', 'width': 80}]
        cond = ''
        args = {}
        for key in ('line', 'production_card'):
            if filters.get(key):
                cond += f' and m.{key} = %({key})s'
                args[key] = filters[key]
        rows = frappe.db.sql(f"select m.line, m.production_card, c.style_no, m.colour,\n    \t\tsum(case when m.stage = 'SEW_IN' then m.qty else 0 end) loaded, sum(case when m.stage = 'SEW_OUT' then m.qty else 0 end) sewn,\n    \t\tsum(case when m.stage = 'SEW_REJECT' then m.qty else 0 end) rejected\n    \t\tfrom `tabProduction Movement` m join `tabProduction Card` c on c.name = m.production_card\n    \t\twhere m.stage in ('SEW_IN', 'SEW_OUT', 'SEW_REJECT') and m.line is not null{cond}\n    \t\tgroup by m.line, m.production_card, m.colour order by m.line, c.style_no, m.colour", args, as_dict=True)
        for r in rows:
            r.wip = r.loaded - r.sewn - r.rejected
        return (columns, [r for r in rows if r.loaded or r.wip])
    return execute(filters)
data = list(main(filters))
