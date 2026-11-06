# Purchase Order, After Cancel: the requisitions are refreshed and the stamps cleared.
def run(doc):
    # include: lib_samples.py
    # include: lib_mat.py
    # include: lib_purchasing.py
    refresh_for_documents(doc)
    unstamp_safe("Purchase Order", doc.name)


run(doc)
