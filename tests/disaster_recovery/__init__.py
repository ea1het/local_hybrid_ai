"""Centralized disaster-recovery tests.

Production DR modules remain under ``bkp-dr``.  This package deliberately does not
modify ``sys.path``: each test that imports implementation modules owns that
bootstrap explicitly, which avoids the package name ``tests.dr`` shadowing the
production ``bkp-dr/dr.py`` module during unittest discovery.
"""
