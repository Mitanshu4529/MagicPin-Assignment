#!/usr/bin/env python3
"""
Zero-dependency test runner for all tests in tests/ directory.
Executes all test_* functions in test_*.py and reports results.
"""
import importlib
import inspect
import os
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def run_all_tests():
    test_dir = ROOT / "tests"
    test_files = sorted(test_dir.glob("test_*.py"))

    total_passed = 0
    total_failed = 0
    total_tests = 0
    start_time = time.time()

    print("=" * 70)
    print("RUNNING VERA MESSAGE ENGINE AUTOMATED TEST SUITE".center(70))
    print("=" * 70)

    for tf in test_files:
        module_name = f"tests.{tf.stem}"
        try:
            mod = importlib.import_module(module_name)
        except Exception as e:
            print(f"[FAIL] Could not import {module_name}: {e}")
            total_failed += 1
            continue

        test_funcs = [
            (name, obj)
            for name, obj in inspect.getmembers(mod, inspect.isfunction)
            if name.startswith("test_")
        ]

        print(f"\n--- {tf.name} ({len(test_funcs)} tests) ---")

        for name, fn in test_funcs:
            total_tests += 1
            try:
                # Check if fn accepts client fixture or args
                sig = inspect.signature(fn)
                if "client" in sig.parameters:
                    from fastapi.testclient import TestClient
                    from bot import app
                    c = TestClient(app)
                    c.post("/v1/teardown", json={})
                    fn(c)
                else:
                    fn()
                print(f"  [PASS] {name}")
                total_passed += 1
            except Exception as e:
                print(f"  [FAIL] {name}: {e}")
                import traceback
                traceback.print_exc()
                total_failed += 1

    elapsed = (time.time() - start_time) * 1000
    print("\n" + "=" * 70)
    print(f"RESULTS: {total_passed}/{total_tests} passed, {total_failed} failed in {elapsed:.1f}ms")
    print("=" * 70 + "\n")

    if total_failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    run_all_tests()
