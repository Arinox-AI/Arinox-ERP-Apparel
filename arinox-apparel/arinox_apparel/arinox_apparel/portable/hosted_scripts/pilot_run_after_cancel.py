# Pilot Run, After Cancel: back to draft, the stamp cleared.
def run(doc):
    # include: lib_mat.py
    doc.db_set("status", "Draft")
    unstamp_safe("Pilot Run", doc.name)


run(doc)
