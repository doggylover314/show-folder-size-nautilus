# Tests

```bash
tests/fetch-abi-fixtures.sh   # once, ~60 KB of downloads, extracts only
tests/run-tests.sh
```

`run-tests.sh` works without the fixtures too; the tests that need them skip
themselves and say so.

## What is here, and what it is evidence for

This project claims to support three libnautilus-extension ABIs. Any given
machine has exactly one of them, so that claim is untestable by ordinary
means, and an untested claim in a README is how a package ends up silently
doing nothing on two thirds of its users' desktops. That is not hypothetical:
it is what this project shipped until 1.0.0, and the fix for it was itself
wrong on the newest releases. Hence these.

| File | Needs fixtures | Proves |
|---|---|---|
| `test_sort_key.py` | no | the "Total Size" header sorts numerically, and the key that makes it do so draws as nothing |
| `test_abi_selection.py` | no | the right ABI is chosen, on every combination of what might be installed |
| `test_abi_live.py` | yes | the registration path runs on ABIs this machine does not have |
| `fetch-abi-fixtures.sh` | — | downloads and extracts the real libraries to make the above possible |

### `test_sort_key.py`

Nautilus sorts an extension's column by running `strcmp()` over the same
string it draws in the cell, so the extension prefixes each value with a
fixed-width key built from four zero-width characters. Two claims, two halves
of this test:

- **It sorts.** Cell values are compared as UTF-8 *bytes*, which is what
  `strcmp` does, over sizes spanning 0 to 2^64-1. The pairs alphabetical
  sorting got wrong are listed explicitly, and each one is checked twice:
  that the key orders it correctly, and that the visible text alone would
  still get it wrong -- so the test keeps its teeth if somebody ever decides
  the key looks unnecessary.
- **It is invisible.** Every digit is laid out through PangoCairo and its ink
  and logical extents compared against the bare text. This is not decoration:
  it is how U+034F and U+FE00, both default-ignorable and both plausible
  candidates, were caught drawing a dotted circle.

The last section writes a config file into a temporary `HOME` and imports the
extension in a fresh interpreter, to check `numeric_sort=0` really does turn
the whole thing off.

Nautilus itself is stubbed with two empty `GInterface`s, so this runs on any
machine with PyGObject -- no file manager, no fixtures, no network.

### `test_abi_selection.py`

Stubs the two things that vary between machines, `gi.require_version` and
`/proc/self/maps`, then asks for a decision on each combination: one ABI
installed, two installed, none, a future 4.2, `10.0` against `9.0`. Two of
these exist because they caught real bugs during development, and both are
the kind that produce no error at all, just a missing column:

- sorting versions by an ascending key and then reversing the list puts an
  unparseable version *first* rather than last;
- narrowing candidates by shared-library name can select a version that came
  from the fallback list and is not actually installed, leaving nothing to
  load. Narrowing therefore reorders and never filters.

### `test_abi_live.py`

Downloads aside, this is the interesting one. It runs the extension's actual
registration path -- same `Nautilus.Column` arguments, same `xalign` property,
same two interfaces subclassed, same `get_columns()` call -- against the
genuine `libnautilus-extension.so.1` from Nautilus 42.6 and `.so.4` from
50.2.2, loaded via `LD_LIBRARY_PATH` in a child process.

**Read a pass as "registers cleanly", not as "works."** There is no running
file manager here, so nothing in this directory can show that the column
appears on screen. That distinction is deliberate and the README's support
table uses the same wording.

## Fixtures

`fetch-abi-fixtures.sh` pulls four `.deb` files from the Ubuntu archive and
**extracts** them into `tests/fixtures/`, which is gitignored. Nothing is
installed, no root is required, and `rm -rf tests/fixtures` is a complete
uninstall.

If a download fails, the archive has probably dropped that version after a
release went end-of-life. The script says so and points at the pool directory;
update the version strings in it and it will work again.
