# Autonomerce offline integration demo

Run the complete credential-free sales loop from the repository root:

```bash
python3 projects/autonomerce/examples/run_offline_demo.py
```

The repository command reads only the JSON fixtures in `examples/fixtures/` and
prints a deterministic public delivery/revenue receipt. Installed wheels use
byte-identical copies bundled under `autonomerce.demo/fixtures`; a regression
test prevents the two fixture sets from drifting. The demo performs no network
calls, uses no credentials, and moves no funds. Add `--compact` for one-line
JSON or `--output /tmp/autonomerce-receipt.json` to save the same public bundle.

The package entry point is also available when the API package is on
`PYTHONPATH`:

```bash
PYTHONPATH=projects/autonomerce/apps/api \
  python3 -m autonomerce.demo
```
