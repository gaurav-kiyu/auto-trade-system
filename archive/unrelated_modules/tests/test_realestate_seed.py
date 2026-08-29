"""Regression tests for realestate seed-data provisioning.

Covers the bug where ``seed_properties`` called ``create_property(prop_data)``
with a single dict while the service method requires explicit keyword
arguments — every listing failed silently and the seeder returned 0.
"""

from realestate.application.services import create_default_services
from realestate.seed_data import SEED_PROPERTIES, seed_properties


def test_seed_properties_seeds_all_listings():
    svcs = create_default_services()
    count = seed_properties(svcs["property_service"])
    assert count == len(SEED_PROPERTIES)
    assert count > 0


def test_seeded_properties_are_queryable():
    svcs = create_default_services()
    seed_properties(svcs["property_service"])
    properties = svcs["property_service"].list_all()
    assert len(properties) == len(SEED_PROPERTIES)


def test_seed_properties_does_not_mutate_seed_source():
    keys_before = [sorted(p.keys()) for p in SEED_PROPERTIES]
    svcs = create_default_services()
    seed_properties(svcs["property_service"])
    keys_after = [sorted(p.keys()) for p in SEED_PROPERTIES]
    assert keys_after == keys_before
