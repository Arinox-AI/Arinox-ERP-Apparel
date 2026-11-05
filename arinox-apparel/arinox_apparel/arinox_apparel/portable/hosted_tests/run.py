from arinox_apparel.portable.hosted_tests import harness


def run(only=None):
	import importlib
	import pkgutil

	from arinox_apparel.portable import hosted_tests

	for m in pkgutil.iter_modules(hosted_tests.__path__):
		if m.name.startswith("test_"):
			importlib.import_module(f"arinox_apparel.portable.hosted_tests.{m.name}")
	return harness.run_all(only)
