def main(filters):

    def execute(filters):
        f = filters
        conds = ['sc.docstatus = 1']
        vals = {}
        if f.customer:
            conds.append('sc.customer = %(customer)s')
            vals['customer'] = f.customer
        if f.from_date and f.to_date:
            conds.append('i.ex_factory_date between %(from_date)s and %(to_date)s')
            vals.update(from_date=f.from_date, to_date=f.to_date)
        if not f.include_ordered:
            conds.append("ifnull(sc.sales_order, '') = ''")
        rows = frappe.db.sql(f"select sc.name as contract, sc.customer, sc.currency, sc.sales_order, i.style_no, i.style_item, i.colour,\n    \t\t\ti.qty, i.tolerance_pct, i.rate, i.amount, i.ex_factory_date, i.etd, i.in_warehouse_date, sc.incoterm,\n    \t\t\tsc.port_of_loading, sc.shipment_mode\n    \t\tfrom `tabSales Contract Item` i join `tabSales Contract` sc on sc.name = i.parent\n    \t\twhere {' and '.join(conds)} order by i.ex_factory_date, sc.name", vals, as_dict=True)
        today = frappe.utils.getdate(frappe.utils.nowdate())
        for r in rows:
            r.days_to_ex_factory = frappe.utils.date_diff(r.ex_factory_date, today) if r.ex_factory_date else None
        cols = [{'label': 'Contract', 'fieldname': 'contract', 'fieldtype': 'Link', 'options': 'Sales Contract', 'width': 150}, {'label': 'Customer', 'fieldname': 'customer', 'fieldtype': 'Link', 'options': 'Customer', 'width': 150}, {'label': 'Style', 'fieldname': 'style_no', 'fieldtype': 'Data', 'width': 100}, {'label': 'Colour', 'fieldname': 'colour', 'fieldtype': 'Data', 'width': 90}, {'label': 'Qty', 'fieldname': 'qty', 'fieldtype': 'Int', 'width': 75}, {'label': 'Tol ±%', 'fieldname': 'tolerance_pct', 'fieldtype': 'Percent', 'width': 65}, {'label': 'Amount', 'fieldname': 'amount', 'fieldtype': 'Currency', 'options': 'currency', 'width': 105}, {'label': 'Ex-Factory', 'fieldname': 'ex_factory_date', 'fieldtype': 'Date', 'width': 95}, {'label': 'Days Left', 'fieldname': 'days_to_ex_factory', 'fieldtype': 'Int', 'width': 75}, {'label': 'ETD', 'fieldname': 'etd', 'fieldtype': 'Date', 'width': 95}, {'label': 'In-Warehouse', 'fieldname': 'in_warehouse_date', 'fieldtype': 'Date', 'width': 100}, {'label': 'Incoterm', 'fieldname': 'incoterm', 'fieldtype': 'Data', 'width': 70}, {'label': 'Mode', 'fieldname': 'shipment_mode', 'fieldtype': 'Data', 'width': 65}, {'label': 'Port of Loading', 'fieldname': 'port_of_loading', 'fieldtype': 'Data', 'width': 110}, {'label': 'Sales Order', 'fieldname': 'sales_order', 'fieldtype': 'Link', 'options': 'Sales Order', 'width': 130}, {'label': 'Currency', 'fieldname': 'currency', 'fieldtype': 'Link', 'options': 'Currency', 'hidden': 1}]
        return (cols, rows)
    return execute(filters)
data = list(main(filters))
