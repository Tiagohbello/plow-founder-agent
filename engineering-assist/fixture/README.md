# Engineering Assist fixture

Run from this directory:

```sh
python3 reproduce.py
```

It must fail with `expected 900, got 990`. A valid prepared patch changes the
calculation to `total_cents - (total_cents * discount_percent // 100)`, then
the same command passes. Keep the diff small and do not deploy or open a PR.
