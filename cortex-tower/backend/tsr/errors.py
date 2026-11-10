"""Exceptions of the Tower Script Runtime. Everything a caller must tell apart has its own class."""


class TSRError(Exception):
    """Base class."""


class TSRValidationError(TSRError):
    """A script called ``frappe.throw``. The message is for the user and is shown unchanged."""

    def __init__(self, message: str, title: str = ""):
        super().__init__(message)
        self.message = message
        self.title = title


class TSRUnsupported(TSRError):
    """The script used something the runtime does not implement. Never swallowed, never guessed."""


class TSRConflict(TSRError):
    """The ERP document changed after it was read (its ``modified`` differs)."""

    def __init__(self, doctype: str, name: str, mine: str, theirs: str):
        super().__init__(f"{doctype} {name} was changed in the ERP at {theirs} (read at {mine}).")
        self.doctype, self.name, self.mine, self.theirs = doctype, name, mine, theirs


class TSRNotFound(TSRError):
    """A document the script asked for does not exist."""

    def __init__(self, doctype: str, name: str):
        super().__init__(f"{doctype} {name} not found")
        self.doctype, self.name = doctype, name


class TSRBackendError(TSRError):
    """The ERP refused or failed a call. ``detail`` carries the ERP's own message."""

    def __init__(self, message: str, status: int = 0, detail: str = ""):
        super().__init__(message)
        self.status, self.detail = status, detail


class TSRNeedsSchemaFix(TSRUnsupported):
    """A script wrote a field of a submitted document that the ERP only lets us change if the field is
    ``allow_on_submit``. Fixed by data on the ERP (a Property Setter), see ``erp_setup/allow_on_submit.json``."""

    def __init__(self, doctype: str, fields):
        self.doctype, self.fields = doctype, list(fields)
        super().__init__(f"{doctype}: the ERP does not allow changing {', '.join(self.fields)} after submission. "
                         f"Load erp_setup/allow_on_submit.json (a Property Setter per field) on the ERP.")
