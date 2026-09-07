#!/usr/bin/env python3
"""Reproduce the intentional fixture bug; exits non-zero until patched."""

from buggy_calculator import discounted_total_cents


def main() -> int:
    expected = 900
    actual = discounted_total_cents(1000, 10)
    if actual == expected:
        print("fixture passes")
        return 0
    print(f"fixture fails: expected {expected}, got {actual}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
