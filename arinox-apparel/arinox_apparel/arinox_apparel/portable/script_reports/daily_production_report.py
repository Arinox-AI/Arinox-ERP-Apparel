def main(filters):
    STAGES = [('cut', 'CUT', 'Cut'), ('sew', 'SEW_OUT', 'Sewn'), ('sent', 'SC_OUT', 'Sent Out'), ('back', 'SC_BACK_GOOD', 'Received Back'), ('fin', 'FIN_A', 'Finished A'), ('packed', 'PACKED', 'Packed'), ('shipped', 'SHIPPED', 'Shipped')]

    def execute(filters):
        filters = filters
        day = frappe.utils.getdate(filters.date or frappe.utils.nowdate())
        columns = [{'fieldname': 'production_card', 'label': 'Production Card', 'fieldtype': 'Link', 'options': 'Production Card', 'width': 130}, {'fieldname': 'customer', 'label': 'Buyer', 'fieldtype': 'Data', 'width': 110}, {'fieldname': 'style_no', 'label': 'Style', 'fieldtype': 'Data', 'width': 110}, {'fieldname': 'colour', 'label': 'Colour', 'fieldtype': 'Data', 'width': 90}, {'fieldname': 'order_qty', 'label': 'Order Qty', 'fieldtype': 'Int', 'width': 80}]
        for key, x_stage, label in STAGES:
            columns.append({'fieldname': f'{key}_today', 'label': '%s Today' % (label,), 'fieldtype': 'Int', 'width': 90})
            columns.append({'fieldname': f'{key}_total', 'label': '%s Total' % (label,), 'fieldtype': 'Int', 'width': 90})
        columns += [{'fieldname': 'rejects', 'label': 'Rejects', 'fieldtype': 'Int', 'width': 80}, {'fieldname': 'rejection_pct', 'label': 'Rejection %', 'fieldtype': 'Percent', 'width': 95}, {'fieldname': 'cut_to_ship', 'label': 'Cut to Ship', 'fieldtype': 'Percent', 'width': 90}]
        cond = ['c.docstatus = 1', "c.status not in ('Superseded', 'Cancelled', 'Closed')"]
        args = {}
        for key, col in (('production_card', 'c.name'), ('customer', 'c.customer'), ('sales_order', 'c.sales_order')):
            if filters.get(key):
                cond.append(f'{col} = %({key})s')
                args[key] = filters[key]
        cards = frappe.db.sql(f"select c.name, c.customer, c.style_no from `tabProduction Card` c where {' and '.join(cond)} order by c.creation desc limit 200", args, as_dict=True)
        data = []
        for c in cards:
            colours = frappe.db.sql('select colour, sum(order_qty) from `tabProduction Card Line` where parent = %s group by colour order by min(idx)', c.name)
            for colour, order_qty in colours:
                row = {'production_card': c.name, 'customer': c.customer, 'style_no': c.style_no, 'colour': colour, 'order_qty': order_qty}
                for key, stage, x_label in STAGES:
                    pair1 = frappe.db.sql("select ifnull(sum(qty), 0), ifnull(sum(case when posting_date = %s then qty else 0 end), 0) from `tabProduction Movement` where production_card = %s and colour = %s and stage = %s and purpose != 'Pilot'", (day, c.name, colour, stage))[0]
                    tot = pair1[0]
                    today = pair1[1]
                    row[f'{key}_total'] = tot
                    row[f'{key}_today'] = today
                rej = frappe.utils.flt(frappe.db.sql("select ifnull(sum(qty), 0) from `tabProduction Movement` where production_card = %s and colour = %s and stage in ('CUT_REJECT', 'SEW_REJECT', 'SC_BACK_REJECT_VENDOR', 'SC_BACK_REJECT_FACTORY', 'FIN_REJECT')", (c.name, colour))[0][0])
                row['rejects'] = rej
                row['rejection_pct'] = rej * 100 / row['cut_total'] if row['cut_total'] else None
                row['cut_to_ship'] = row['shipped_total'] * 100 / row['cut_total'] if row['cut_total'] else None
                if any((row[f'{k}_total'] for k, x_s, x_l in STAGES)):
                    data.append(row)
        return (columns, data)
    return execute(filters)
data = list(main(filters))
