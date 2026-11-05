def main(filters):

    def execute(filters):
        f = filters
        conds = ['1=1']
        vals = {}
        for key, col in (('customer', 'pn.customer'), ('price_negotiation', 'pn.name'), ('cost_sheet', 'r.cost_sheet'), ('direction', 'r.direction')):
            if f.get(key):
                conds.append(f'{col} = %({key})s')
                vals[key] = f.get(key)
        if f.style_no:
            conds.append('r.style_no like %(style_no)s')
            vals['style_no'] = f'%{f.style_no}%'
        if f.from_date and f.to_date:
            conds.append('r.round_date between %(from_date)s and %(to_date)s')
            vals.update(from_date=f.from_date, to_date=f.to_date)
        rows = frappe.db.sql(f"select r.round_date, pn.name as price_negotiation, pn.customer, pn.currency, r.style_no, r.cost_sheet,\n    \t\t\tr.direction, r.price, r.qty, r.margin_pct, r.below_floor, r.channel, r.quotation, r.remarks,\n    \t\t\tr.recorded_by, r.recorded_by_ai, cs.quoted_price as costed_fob\n    \t\tfrom `tabPrice Negotiation Round` r\n    \t\tjoin `tabPrice Negotiation` pn on pn.name = r.parent and r.parenttype = 'Price Negotiation'\n    \t\tleft join `tabCost Sheet` cs on cs.name = r.cost_sheet\n    \t\twhere {' and '.join(conds)}\n    \t\torder by pn.name, r.style_no, r.round_date, r.idx", vals, as_dict=True)
        cols = [{'label': 'Date', 'fieldname': 'round_date', 'fieldtype': 'Date', 'width': 95}, {'label': 'Negotiation', 'fieldname': 'price_negotiation', 'fieldtype': 'Link', 'options': 'Price Negotiation', 'width': 130}, {'label': 'Customer', 'fieldname': 'customer', 'fieldtype': 'Link', 'options': 'Customer', 'width': 150}, {'label': 'Style', 'fieldname': 'style_no', 'fieldtype': 'Data', 'width': 100}, {'label': 'Cost Sheet', 'fieldname': 'cost_sheet', 'fieldtype': 'Link', 'options': 'Cost Sheet', 'width': 130}, {'label': 'Who / What', 'fieldname': 'direction', 'fieldtype': 'Data', 'width': 110}, {'label': 'Price', 'fieldname': 'price', 'fieldtype': 'Currency', 'options': 'currency', 'width': 90}, {'label': 'Costed FOB', 'fieldname': 'costed_fob', 'fieldtype': 'Currency', 'options': 'currency', 'width': 95}, {'label': 'Qty', 'fieldname': 'qty', 'fieldtype': 'Int', 'width': 70}, {'label': 'Margin %', 'fieldname': 'margin_pct', 'fieldtype': 'Percent', 'width': 80}, {'label': 'Below Floor', 'fieldname': 'below_floor', 'fieldtype': 'Check', 'width': 85}, {'label': 'Channel', 'fieldname': 'channel', 'fieldtype': 'Data', 'width': 80}, {'label': 'Quotation', 'fieldname': 'quotation', 'fieldtype': 'Link', 'options': 'Quotation', 'width': 130}, {'label': 'By AI', 'fieldname': 'recorded_by_ai', 'fieldtype': 'Check', 'width': 60}, {'label': 'Recorded By', 'fieldname': 'recorded_by', 'fieldtype': 'Link', 'options': 'User', 'width': 130}, {'label': 'Remarks', 'fieldname': 'remarks', 'fieldtype': 'Data', 'width': 220}, {'label': 'Currency', 'fieldname': 'currency', 'fieldtype': 'Link', 'options': 'Currency', 'hidden': 1}]
        return (cols, rows)
    return execute(filters)
data = list(main(filters))
