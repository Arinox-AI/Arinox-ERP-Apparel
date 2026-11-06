"""A tiny test runner for the hosted case: ERPNext only, the app is NOT installed on the site, so only the loaded records
(DocTypes, data, Server Scripts) can act. Run from the bench:

    bench --site hosted.localhost execute arinox_apparel.portable.hosted_tests.run.run [--kwargs "{'only': 'naming'}"]

Each test runs in a transaction that is rolled back afterwards. Prints one line per test and a count; a failure prints the
exception. Nothing here imports app code (the modules sit in the app's folder only because that is where the repo is)."""

import traceback

import frappe

TESTS = []


def test(group):
	def deco(fn):
		TESTS.append((group, fn.__name__, fn))
		return fn
	return deco


def run_all(only=None):
	passed, failed = 0, []
	for group, name, fn in TESTS:
		if only and only != group and only != name:
			continue
		frappe.db.savepoint("t")
		try:
			fn()
			print(f"  ok    {group}.{name}")
			passed += 1
		except Exception as e:
			print(f"  FAIL  {group}.{name}: {type(e).__name__}: {str(e)[:300]}")
			if "-v" in str(only or ""):
				traceback.print_exc()
			failed.append((group, name, str(e)[:300]))
		finally:
			frappe.db.rollback(save_point="t")
	print(f"RESULT passed {passed} failed {len(failed)} of {passed + len(failed)}")
	return {"passed": passed, "failed": failed}


def throws(fn, text=None):
	"""True when fn raises (and the message contains `text`, when given)."""
	try:
		fn()
	except Exception as e:
		return text is None or text.lower() in str(e).lower()
	return False


def eq(a, b, msg=""):
	assert a == b, f"{msg} expected {b!r}, got {a!r}"


def true(v, msg=""):
	assert v, f"expected true: {msg}"


def raises(fn, text):
    """Like true(throws(...)) but a failure says what actually happened."""
    try:
        fn()
    except Exception as e:
        assert text.lower() in str(e).lower(), f"expected an error with {text!r}, got {type(e).__name__}: {str(e)[:300]}"
        return
    raise AssertionError(f"expected an error with {text!r}, but nothing was raised")
