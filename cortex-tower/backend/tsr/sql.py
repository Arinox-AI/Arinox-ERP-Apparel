"""``frappe.db.sql`` over REST.

REST cannot run SQL, and the hosted scripts issue 80 different read-only queries (joins, sub-selects,
``group by``, ``group_concat``, ``date_sub`` …). Mapping each by hand would break on the next script
change, so this is generic:

1. find every ``tab<Doctype>`` table the query names;
2. fetch **only the rows the query can touch** through the ERP's own list API — the WHERE conjuncts of the
   form ``alias.col = / != / in / < / > / <= / >= <param|literal>`` are pushed down as filters (a superset
   of what the query needs; the exact WHERE is re-applied below);
3. load those rows into an in-memory SQLite database (columns are case-insensitive like MySQL's default
   collation);
4. translate the MySQL dialect that the scripts use and run the query there.

Anything that is not a plain read (``insert``/``update``/``delete``/DDL) is refused with
:class:`TSRUnsupported` — the hosted sandbox refuses it too. A query that would pull more than
``backend.MAX_ROWS`` rows from one table is refused, never truncated.
"""

from __future__ import annotations

import datetime as _dt
import re
import sqlite3
from decimal import Decimal
from typing import Any

from .errors import TSRUnsupported

_STD_COLS = ["name", "owner", "creation", "modified", "modified_by", "docstatus", "idx", "parent", "parentfield", "parenttype"]
_LAYOUT = {"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Heading", "Fold", "Image", "Table", "Table MultiSelect"}
_KEYWORDS = {"on", "where", "join", "left", "right", "inner", "outer", "cross", "group", "order", "limit", "having",
             "union", "using", "natural", "full", "straight_join", "set", "as"}
_FORBIDDEN = re.compile(r"^\s*(insert|update|delete|replace|alter|drop|create|truncate|grant|call|set)\b", re.I)


class DotDict(dict):
    """A row for ``as_dict=True``: attribute access like ``frappe._dict``."""
    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError:
            return None


# ───────────────────────── tokenising helpers ─────────────────────────

def _mask_strings(sql: str) -> tuple[str, list[str]]:
    """Replace every quoted literal by a placeholder so keyword search cannot match inside text."""
    lits: list[str] = []

    def rep(m):
        lits.append(m.group(0))
        return f"\x00{len(lits) - 1}\x00"
    return re.sub(r"'(?:[^'\\]|\\.|'')*'|\"(?:[^\"\\]|\\.)*\"", rep, sql), lits


def _unmask(sql: str, lits: list[str]) -> str:
    return re.sub(r"\x00(\d+)\x00", lambda m: lits[int(m.group(1))], sql)


def _balanced(s: str, i: int) -> int:
    """Index just after the ')' that closes the '(' at ``s[i]``."""
    depth = 0
    for j in range(i, len(s)):
        if s[j] == "(":
            depth += 1
        elif s[j] == ")":
            depth -= 1
            if depth == 0:
                return j + 1
    raise TSRUnsupported("unbalanced parentheses in SQL")


def _split_args(s: str) -> list[str]:
    out, depth, cur = [], 0, []
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur).strip())
    return out


def _rewrite_call(sql: str, name: str, fn) -> str:
    pat = re.compile(r"\b" + name + r"\s*\(", re.I)
    pos = 0
    while True:
        m = pat.search(sql, pos)
        if not m:
            return sql
        open_i = m.end() - 1
        end = _balanced(sql, open_i)
        args = _split_args(sql[open_i + 1:end - 1])
        new = fn(args)
        sql = sql[:m.start()] + new + sql[end:]
        pos = m.start() + len(new)


# ───────────────────────── params ─────────────────────────

def _py(v):
    if isinstance(v, (_dt.datetime,)):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, _dt.date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, bool):
        return int(v)
    return v


def _bind(sql: str, values) -> tuple[str, list]:
    """Turn ``%s`` / ``%(name)s`` into ``?`` and flatten list/tuple values (``in %s``)."""
    masked, lits = _mask_strings(sql)
    params: list = []
    if isinstance(values, dict):
        def rep(m):
            v = values[m.group(1)]
            return _expand(v, params)
        masked = re.sub(r"%\((\w+)\)s", rep, masked)
    else:
        if values is None:
            vals = []
        elif isinstance(values, (list, tuple)):
            vals = list(values)
        else:
            vals = [values]
        it = iter(vals)

        def rep(m):
            try:
                v = next(it)
            except StopIteration:
                raise TSRUnsupported("SQL has more %s placeholders than values")
            return _expand(v, params)
        masked = re.sub(r"%s", rep, masked)
    return _unmask(masked, lits), params


def _expand(v, params: list) -> str:
    if isinstance(v, (list, tuple, set, frozenset)):
        items = [_py(x) for x in v]
        if not items:
            return "(NULL)"
        params.extend(items)
        return "(" + ",".join("?" * len(items)) + ")"
    params.append(_py(v))
    return "?"


# ───────────────────────── dialect ─────────────────────────

def _dialect(sql: str) -> str:
    masked, lits = _mask_strings(sql)
    # integer division is not MySQL's
    masked = re.sub(r"(?<![/*])/(?![/*])", " * 1.0 / ", masked)
    masked = _rewrite_call(masked, "weekday", lambda a: f"((CAST(strftime('%w', {a[0]}) AS INTEGER) + 6) % 7)")
    masked = _rewrite_call(masked, "date_sub", _date_sub)
    masked = _rewrite_call(masked, "date_add", lambda a: _date_sub(a, sign="+"))
    masked = _rewrite_call(masked, "datediff", lambda a: f"CAST(julianday({a[0]}) - julianday({a[1]}) AS INTEGER)")
    masked = _rewrite_call(masked, "curdate", lambda a: "date('now')")
    masked = re.sub(r"\bnow\s*\(\s*\)", "datetime('now')", masked, flags=re.I)
    # `group by 1, 2` is fine in SQLite; `if(a,b,c)` is not
    masked = _rewrite_call(masked, "if", lambda a: f"(CASE WHEN {a[0]} THEN {a[1]} ELSE {a[2]} END)")
    return _unmask(masked, lits)


def _date_sub(args: list[str], sign: str = "-") -> str:
    base, interval = args[0], args[1]
    m = re.match(r"interval\s+(.+?)\s+(day|days|month|months|year|years)\s*$", interval, re.I | re.S)
    if not m:
        raise TSRUnsupported(f"date_sub interval not supported: {interval}")
    unit = m.group(2).lower().rstrip("s")
    return f"date({base}, '{sign}' || ({m.group(1)}) || ' {unit}')"


# ───────────────────────── pushdown ─────────────────────────

_TABLE_RE = re.compile(r"`tab([^`]+)`")


def _blocks(masked: str) -> list[dict]:
    """Split into SELECT blocks (the outer query and each parenthesised sub-select), each with its
    own FROM/JOIN tables and its own top-level WHERE text."""
    blocks: list[dict] = []

    def scan(text: str, base: int):
        # find sub-selects at any depth; blank them out of this level's text
        level = list(text)
        i = 0
        while i < len(text):
            if text[i] == "(":
                end = _balanced(text, i)
                inner = text[i + 1:end - 1]
                if re.match(r"\s*select\b", inner, re.I):
                    scan(inner, base + i + 1)
                    for k in range(i + 1, end - 1):
                        level[k] = " "
                i = end
            else:
                i += 1
        blocks.append({"text": "".join(level), "start": base, "raw": text})

    scan(masked, 0)
    return blocks


def _tables_of(block_text: str) -> list[tuple[str, str]]:
    """[(doctype, alias)] of a block's FROM/JOIN clauses (sub-selects already blanked)."""
    out = []
    for m in re.finditer(r"\b(?:from|join)\s+`tab([^`]+)`(?:\s+(?:as\s+)?(\w+))?", block_text, re.I):
        alias = m.group(2)
        if alias and alias.lower() in _KEYWORDS:
            alias = None
        out.append((m.group(1), alias or m.group(1)))
    return out


def _where_of(block_text: str) -> str:
    m = re.search(r"\bwhere\b(.*?)(?=\bgroup\s+by\b|\border\s+by\b|\blimit\b|\bhaving\b|$)", block_text, re.I | re.S)
    return m.group(1) if m else ""


def _conjuncts(where: str) -> list[tuple[str, int]]:
    """Top-level AND-ed parts with their offset into ``where``. Returns [] if there is a top-level OR."""
    prot = re.sub(r"(\bbetween\b\s+\S+\s+)and(\s+\S+)", lambda m: m.group(1) + "\x01\x01\x01" + m.group(2), where, flags=re.I)
    depth, parts, start = 0, [], 0
    i = 0
    while i < len(prot):
        c = prot[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif depth == 0:
            if re.match(r"\bor\b", prot[i:], re.I) and (i == 0 or not prot[i - 1].isalnum()):
                return []
            if re.match(r"\band\b", prot[i:], re.I) and (i == 0 or not (prot[i - 1].isalnum() or prot[i - 1] == "_")) and not prot[i + 3:i + 4].isalnum():
                parts.append((prot[start:i], start))
                start = i + 3
                i += 3
                continue
        i += 1
    parts.append((prot[start:], start))
    return [(p.replace("\x01\x01\x01", "and"), off) for p, off in parts]


_COND = re.compile(r"^\s*(?:(\w+)\.)?`?(\w+)`?\s*(=|!=|<>|<=|>=|<|>|\bin\b)\s*(.+?)\s*$", re.I | re.S)


def _pushdown(sql_q: str, params: list) -> dict[str, list[list]]:
    """{doctype: [filters-of-occurrence-1, …]} where an empty filter list means 'no safe pushdown'."""
    masked, lits = _mask_strings(sql_q)
    blocks = _blocks(masked)
    result: dict[str, list[list]] = {}
    for b in blocks:
        tables = _tables_of(b["text"])
        if not tables:
            continue
        where = _where_of(b["text"])
        # parameter index of each '?' is its position in the whole masked query
        where_off = b["start"] + b["text"].lower().find("where") + 5 if where else 0
        conj = _conjuncts(where) if where else []
        per_alias: dict[str, list] = {a: [] for _, a in tables}
        for text, off in conj:
            m = _COND.match(text)
            if not m:
                continue
            qual, col, op, rhs = m.group(1), m.group(2), m.group(3).lower(), m.group(4)
            if qual is None:
                if len(tables) != 1:
                    continue
                qual = tables[0][1]
            if qual not in per_alias:
                continue
            absolute = where_off + off
            n_before = masked[:absolute].count("?")
            val = _rhs_value(rhs, masked, absolute, params, n_before, lits)
            if val is _NO:
                continue
            frappe_op = {"<>": "!=", "=": "=", "!=": "!="}.get(op, op)
            if op == "in":
                if not isinstance(val, list) or not val:
                    continue
                per_alias[qual].append([col, "in", val])
            else:
                if isinstance(val, list):
                    continue
                if frappe_op == "!=":
                    continue          # NULL semantics differ; never needed for a superset
                per_alias[qual].append([col, frappe_op, val])
        for dt, alias in tables:
            result.setdefault(dt, []).append(per_alias.get(alias, []))
    return result


_NO = object()


def _rhs_value(rhs: str, masked: str, pos: int, params: list, n_before: int, lits: list[str]):
    rhs = rhs.strip()
    if rhs == "?":
        return params[n_before]
    m = re.fullmatch(r"\x00(\d+)\x00", rhs)
    if m:
        return lits[int(m.group(1))][1:-1].replace("''", "'")
    if re.fullmatch(r"-?\d+(\.\d+)?", rhs):
        return float(rhs) if "." in rhs else int(rhs)
    if rhs.startswith("(") and rhs.endswith(")"):
        items = _split_args(rhs[1:-1])
        out, k = [], n_before
        for it in items:
            it = it.strip()
            if it == "?":
                out.append(params[k])
                k += 1
            else:
                v = _rhs_value(it, masked, pos, params, k, lits)
                if v is _NO or isinstance(v, list):
                    return _NO
                out.append(v)
        # a '(?,?,?)' expansion
        return out
    return _NO


# ───────────────────────── execution ─────────────────────────

def _columns(backend, doctype: str, rows: list[dict]) -> list[str]:
    cols = list(_STD_COLS)
    try:
        for f in backend.meta(doctype)["fields"]:
            if f["fieldtype"] not in _LAYOUT and f["fieldname"] not in cols:
                cols.append(f["fieldname"])
    except Exception:
        pass
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    return cols


def _val(v):
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (list, dict)):
        return None
    return v


def execute(backend, query: str, values=None, as_dict: bool = False, pluck: str | None = None, cache: dict | None = None):
    """Run one read-only query. ``cache`` (per request) avoids fetching the same table slice twice."""
    if _FORBIDDEN.match(query or ""):
        raise TSRUnsupported("only read-only SQL is allowed (same as the hosted sandbox)")
    cache = cache if cache is not None else {}
    stripped = query.strip().rstrip(";")
    if re.search(r"information_schema\.columns", stripped, re.I):
        m = re.search(r"table_name\s*=\s*'tab([^']+)'", stripped)
        if not m:
            raise TSRUnsupported("information_schema query not understood")
        cols = [c for c in _columns(backend, m.group(1), [])]
        return cols if pluck else [(c,) for c in cols]

    sql_q, params = _bind(stripped, values)
    sql_q = _dialect(sql_q)
    push = _pushdown(sql_q, params)
    db = sqlite3.connect(":memory:")
    try:
        names: dict[str, str] = {}
        for dt in {m for m in _TABLE_RE.findall(sql_q)}:
            names[dt] = "t_" + re.sub(r"\W", "_", dt)
            occurrences = push.get(dt) or [[]]
            fetched: dict[str, dict] = {}
            for flt in occurrences:
                key = (dt, repr(sorted(map(repr, flt))))
                rows = cache.get(key)
                if rows is None:
                    rows = backend.get_list(dt, flt or None, ["*"])
                    cache[key] = rows
                for r in rows:
                    fetched.setdefault(str(r.get("name")), r)
            rows = list(fetched.values())
            cols = _columns(backend, dt, rows)
            ddl = ", ".join(f'"{c}" COLLATE NOCASE' for c in cols)
            db.execute(f'CREATE TABLE "{names[dt]}" ({ddl})')
            if rows:
                ph = ",".join("?" * len(cols))
                db.executemany(f'INSERT OR IGNORE INTO "{names[dt]}" VALUES ({ph})',
                               [[_val(r.get(c)) for c in cols] for r in rows])
        final = _TABLE_RE.sub(lambda m: f'"{names[m.group(1)]}"', sql_q)
        cur = db.execute(final, params)
        desc = [d[0] for d in cur.description or []]
        data = cur.fetchall()
    except sqlite3.Error as e:
        raise TSRUnsupported(f"SQL not supported by the runtime: {e}  [{query[:160]}]")
    finally:
        db.close()
    if pluck:
        return [r[0] for r in data]
    if as_dict:
        return [DotDict(zip(desc, r)) for r in data]
    return [tuple(r) for r in data]
