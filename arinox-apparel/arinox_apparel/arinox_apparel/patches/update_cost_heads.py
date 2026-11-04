"""Bring seeded Cost Heads in line with the real costing sheet (percentages are on product cost,
profit is a markup on cost, fabric import/export is per metre). Dev sites only had the first seed."""

from arinox_apparel.setup.install import seed_cost_heads


def execute():
	seed_cost_heads(update=True)
