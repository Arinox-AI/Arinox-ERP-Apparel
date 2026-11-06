# TNA Milestone, After Save and Before Delete: the order's status follows its milestones.
def run(doc):
    # include: lib_tna.py
    refresh_order_tna(doc.order_tna)


run(doc)
