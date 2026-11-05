def main(filters):

    def execute(filters):
        f = filters
        cond = {'docstatus': ('<', 2)}
        if f.customer:
            cond['customer'] = f.customer
        if f.product_type:
            cond['product_type'] = f.product_type
        if f.from_date and f.to_date:
            cond['costing_date'] = ('between', [f.from_date, f.to_date])
        if f.below_floor:
            cond['below_floor'] = 1
        if f.approval_status:
            cond['approval_status'] = f.approval_status
        rows = frappe.get_all('Cost Sheet', filters=cond, order_by='costing_date desc', fields=['name', 'customer', 'style_no', 'product_type', 'costing_date', 'revision_no', 'currency', 'material_cost', 'conversion_cost', 'subtotal', 'computed_price', 'quoted_price', 'margin_pct', 'margin_floor_pct', 'below_floor', 'approval_status', 'approved_by', 'docstatus', 'order_qty', 'order_value'])
        for r in rows:
            r.state = {0: 'Draft', 1: 'Submitted'}[r.docstatus]
        cols = [{'label': 'Cost Sheet', 'fieldname': 'name', 'fieldtype': 'Link', 'options': 'Cost Sheet', 'width': 140}, {'label': 'Customer', 'fieldname': 'customer', 'fieldtype': 'Link', 'options': 'Customer', 'width': 150}, {'label': 'Style', 'fieldname': 'style_no', 'fieldtype': 'Data', 'width': 110}, {'label': 'Product Type', 'fieldname': 'product_type', 'fieldtype': 'Data', 'width': 100}, {'label': 'Date', 'fieldname': 'costing_date', 'fieldtype': 'Date', 'width': 95}, {'label': 'Rev', 'fieldname': 'revision_no', 'fieldtype': 'Int', 'width': 50}, {'label': 'State', 'fieldname': 'state', 'fieldtype': 'Data', 'width': 85}, {'label': 'Material', 'fieldname': 'material_cost', 'fieldtype': 'Currency', 'options': 'currency', 'width': 95}, {'label': 'Other Heads', 'fieldname': 'conversion_cost', 'fieldtype': 'Currency', 'options': 'currency', 'width': 95}, {'label': 'Computed FOB', 'fieldname': 'computed_price', 'fieldtype': 'Currency', 'options': 'currency', 'width': 105}, {'label': 'Quoted FOB', 'fieldname': 'quoted_price', 'fieldtype': 'Currency', 'options': 'currency', 'width': 100}, {'label': 'Margin %', 'fieldname': 'margin_pct', 'fieldtype': 'Percent', 'width': 85}, {'label': 'Floor %', 'fieldname': 'margin_floor_pct', 'fieldtype': 'Percent', 'width': 75}, {'label': 'Below Floor', 'fieldname': 'below_floor', 'fieldtype': 'Check', 'width': 90}, {'label': 'Approval', 'fieldname': 'approval_status', 'fieldtype': 'Data', 'width': 95}, {'label': 'Approved By', 'fieldname': 'approved_by', 'fieldtype': 'Link', 'options': 'User', 'width': 130}, {'label': 'Order Qty', 'fieldname': 'order_qty', 'fieldtype': 'Int', 'width': 85}, {'label': 'Order Value', 'fieldname': 'order_value', 'fieldtype': 'Currency', 'options': 'currency', 'width': 115}, {'label': 'Currency', 'fieldname': 'currency', 'fieldtype': 'Link', 'options': 'Currency', 'hidden': 1}]
        top = rows[:15]
        chart = {'data': {'labels': [r.style_no for r in top], 'datasets': [{'name': 'Margin %', 'values': [r.margin_pct for r in top]}, {'name': 'Floor %', 'values': [r.margin_floor_pct for r in top]}]}, 'type': 'bar', 'colors': ['#e8590c', '#16120f']}
        return (cols, rows, None, chart)
    return execute(filters)
data = list(main(filters))
