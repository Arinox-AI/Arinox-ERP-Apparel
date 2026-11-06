# Purchase Order, After Submit / After Save (Submitted Document): the requisitions' ordered quantities and status are refreshed, and booked / PI / ETD are stamped.
def run(doc):
    # include: lib_samples.py
    # include: lib_mat.py
    # include: lib_purchasing.py
    # include: lib_po.py
    refresh_for_documents(doc)
    stamp_po(doc)


run(doc)
