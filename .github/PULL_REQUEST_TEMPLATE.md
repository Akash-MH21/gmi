## Problem and resulting behaviour

Describe the problem and what changes for the user. Include a command example
when helpful. Never include keys or tokens.

## Validation

State the commands you ran and their results. Distinguish offline tests from
live verification and list anything unverified.

## Checklist

- [ ] Ran `pytest -q -m "not live and not live_media"`.
- [ ] Ran `python tools/gen_api.py --check`.
- [ ] Committed regenerated manifest output if specs or the generator changed.
- [ ] Updated help text and docs for user-visible changes.
- [ ] Preserved existing limits and stated verification precisely.
- [ ] Used plain English with no em or en dashes and no comma before "and".
- [ ] Checked the diff for keys and tokens.

See [CONTRIBUTING.md](../CONTRIBUTING.md) for setup and the full checklist.
