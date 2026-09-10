#!/usr/bin/env python3
"""The invisible sort key: does the "Total Size" header sort numerically?

Nautilus compares extension columns with strcmp() on the very string it draws
in the cell (nautilus_file_compare_for_sort_by_attribute_q in
src/nautilus-file.c, and update_label in src/nautilus-label-cell.c).  The
extension therefore puts a fixed-width key of zero-width characters in front
of every value.  Two things have to hold for that to be a fix rather than a
mess, and this checks both:

  1. Byte order equals numeric order, for every pair that matters --
     including the ones plain alphabetical sorting gets wrong.
  2. The key is invisible.  Not "should be": laid out through Pango and
     measured, when PangoCairo is available here.

Needs no network and no fixtures.  Nautilus itself is stubbed with two empty
GInterfaces, which is enough to import the extension on a machine that has
PyGObject but no file manager -- the code under test is pure arithmetic on
strings and touches nothing else.

Run directly, or via tests/run-tests.sh.  Exits non-zero on failure.
"""
import os
import subprocess
import sys
import tempfile
import types

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

fails = []
skips = []


def check(label, got, want):
    ok = got == want
    print("  %-58s %s" % (label, "PASS" if ok else "FAIL"))
    if not ok:
        fails.append("%s: wanted %r, got %r" % (label, want, got))


def skip(label, why):
    print("  %-58s SKIP  %s" % (label, why))
    skips.append(label)


def load_extension():
    """Import show_folder_size with Nautilus stubbed out.

    gi.require_version is made to say yes to Nautilus, and a module holding
    two GInterface subclasses is put where `from gi.repository import
    Nautilus` will find it.  GInterface and not a plain class: the provider
    subclasses both, and GObject's metaclass will not register a type over a
    base that is not a GObject one.
    """
    import gi
    from gi.repository import GObject

    real_require = gi.require_version

    def require(namespace, version):
        if namespace == "Nautilus":
            return None
        return real_require(namespace, version)

    gi.require_version = require

    stub = types.ModuleType("gi.repository.Nautilus")

    class ColumnProvider(GObject.GInterface):
        pass

    class InfoProvider(GObject.GInterface):
        pass

    class Column(GObject.GObject):
        pass

    class OperationResult:
        COMPLETE = 0

    stub.ColumnProvider = ColumnProvider
    stub.InfoProvider = InfoProvider
    stub.Column = Column
    stub.OperationResult = OperationResult
    sys.modules["gi.repository.Nautilus"] = stub

    sys.path.insert(0, REPO)
    import show_folder_size
    return show_folder_size


try:
    import warnings
    with warnings.catch_warnings():
        # The stub interfaces have no implementation support, which GObject
        # says out loud. Nothing here calls into them.
        warnings.simplefilter("ignore", RuntimeWarning)
        m = load_extension()
except Exception as exc:
    print("SKIP: cannot import the extension here: %r" % (exc,))
    print("      (needs PyGObject; nautilus itself is not required)")
    sys.exit(0)


# --- 1. shape of the key ----------------------------------------------------
print("key shape:")

check("numeric sorting is on by default", m.NUMERIC_SORT, True)
check("the key is four distinct digits", len(set(m.SORT_DIGITS)), 4)
check("digits are in ascending code point order",
      list(m.SORT_DIGITS), sorted(m.SORT_DIGITS))
check("SORT_KEY_MAX covers the whole unsigned 64-bit range",
      m.SORT_KEY_MAX, (1 << 64) - 1)

widths = {len(m.sort_key(n)) for n in
          (0, 1, 999, 1 << 20, 1 << 40, (1 << 64) - 1)}
check("every key is the same length", widths, {m.SORT_KEY_DIGITS})

check("a negative byte count does not crash or grow the key",
      len(m.sort_key(-1)), m.SORT_KEY_DIGITS)
check("a byte count past the range clamps rather than overflowing",
      m.sort_key(1 << 70), m.sort_key((1 << 64) - 1))


# --- 2. the ordering itself -------------------------------------------------
#
# strcmp compares bytes, so the test compares bytes. Python's own str
# comparison is by code point and would agree -- UTF-8 preserves code point
# order -- but agreeing by luck is not the same as testing the right thing.
print("\nordering (compared as UTF-8 bytes, the way strcmp does):")


def as_strcmp_sees_it(value):
    return value.encode("utf-8")


SIZES = [0, 1, 2, 999, 1000, 1023, 1024, 9999,
         10 ** 5, 10 ** 6 - 1, 10 ** 6, 1 << 20,
         10 ** 9, 1 << 30, 1288490188, 10 ** 12, 1 << 40,
         10 ** 15, 1 << 50, 10 ** 18, (1 << 63) - 1, (1 << 64) - 1]

ordered = sorted(SIZES)
by_bytes = sorted(ordered, key=lambda n: as_strcmp_sees_it(m.cell_value(n)))
check("%d sizes sort into numeric order" % len(SIZES), by_bytes, ordered)

# The pairs the old alphabetical sort got wrong, which is the whole point.
WRONG_BEFORE = [
    (9900, 1288490188),          # "9.9 kB" vs "1.2 GB"
    (999, 1000000),              # "999 bytes" vs "1.0 MB"
    (9 * 10 ** 9, 12 * 10 ** 9),  # "9.0 GB" vs "12.0 GB"
    (500 * 10 ** 6, 1 * 10 ** 9),  # "500.0 MB" vs "1.0 GB"
    (2 * 10 ** 12, 30 * 10 ** 9),  # "2.0 TB" vs "30.0 GB"
]
for smaller, larger in WRONG_BEFORE:
    if smaller > larger:
        smaller, larger = larger, smaller
    label = "%s sorts before %s" % (m.format_size(smaller),
                                    m.format_size(larger))
    check(label,
          as_strcmp_sees_it(m.cell_value(smaller)) <
          as_strcmp_sees_it(m.cell_value(larger)), True)
    # And confirm this is a pair the visible text alone gets wrong, so the
    # test would still be meaningful if someone "simplified" the key away.
    check("  ... and plain text alone would get that pair wrong",
          m.format_size(smaller).encode("utf-8") >
          m.format_size(larger).encode("utf-8"), True)

check("equal sizes give equal keys",
      m.sort_key(4096) == m.sort_key(4096), True)
check("one byte more is one step up",
      as_strcmp_sees_it(m.cell_value(4096)) <
      as_strcmp_sees_it(m.cell_value(4097)), True)


# --- 3. the placeholder and the blanks --------------------------------------
print("\nplaceholder and blank cells:")

pending = m.cell_value(0, m.PENDING_TEXT)
check("a folder being measured still carries a key",
      len(pending) - len(m.PENDING_TEXT), m.SORT_KEY_DIGITS)
check("it sorts below every real size",
      all(as_strcmp_sees_it(pending) < as_strcmp_sees_it(m.cell_value(n))
          for n in SIZES if n > 0), True)
check("a file's blank cell sorts below the placeholder",
      b"" < as_strcmp_sees_it(pending), True)


# --- 4. what the user actually reads ----------------------------------------
print("\nvisible text:")

check("the rendered half is byte-identical to format_size()",
      all(m.visible_text(m.cell_value(n)) == m.format_size(n) for n in SIZES),
      True)
check("stripping the key off the placeholder gives it back",
      m.visible_text(pending), m.PENDING_TEXT)
check("no key character appears in any formatted size",
      any(d in m.format_size(n) for n in SIZES for d in m.SORT_DIGITS), False)


# --- 5. is it really invisible ----------------------------------------------
print("\nrendering (Pango, measured not assumed):")

try:
    import gi
    gi.require_version("Pango", "1.0")
    gi.require_version("PangoCairo", "1.0")
    from gi.repository import Pango, PangoCairo
except (ImportError, ValueError) as exc:
    skip("the key draws as nothing", "no PangoCairo here (%s)" % exc)
else:
    context = PangoCairo.FontMap.get_default().create_context()
    context.set_font_description(Pango.FontDescription.from_string("Sans 11"))

    def extents(text):
        layout = Pango.Layout(context)
        layout.set_text(text, -1)
        ink, logical = layout.get_pixel_extents()
        return ink.width, ink.height, logical.width

    bare = "1.2 GB"
    baseline = extents(bare)
    check("the key adds no width and no ink",
          extents(m.sort_key(1288490188) + bare),
          baseline)
    for digit in m.SORT_DIGITS:
        check("  U+%04X on its own draws nothing" % ord(digit),
              extents(digit * m.SORT_KEY_DIGITS + bare), baseline)
    check("a full real cell value is no wider than its text",
          extents(m.cell_value(1288490188)),
          extents(m.format_size(1288490188)))


# --- 6. the escape hatch ----------------------------------------------------
#
# End to end rather than by poking the module: a config file in a fake HOME,
# a fresh interpreter, and then look at what the value actually comes out as.
print("\nnumeric_sort=0 in the config:")

probe = (
    "import sys, types, warnings; sys.path.insert(0, %r);"
    "import gi;"
    "_r = gi.require_version;"
    "gi.require_version = lambda n, v: None if n == 'Nautilus' else _r(n, v);"
    "from gi.repository import GObject;"
    "s = types.ModuleType('gi.repository.Nautilus');"
    "s.ColumnProvider = type('ColumnProvider', (GObject.GInterface,), {});"
    "s.InfoProvider = type('InfoProvider', (GObject.GInterface,), {});"
    "s.Column = type('Column', (GObject.GObject,), {});"
    "s.OperationResult = type('OperationResult', (), {'COMPLETE': 0});"
    "sys.modules['gi.repository.Nautilus'] = s;"
    "warnings.simplefilter('ignore', RuntimeWarning);"
    "import show_folder_size as m;"
    "print(repr((m.NUMERIC_SORT, m.cell_value(1000))))" % REPO)


def value_with_config(contents):
    with tempfile.TemporaryDirectory() as home:
        os.makedirs(os.path.join(home, ".config"))
        if contents is not None:
            with open(os.path.join(home, ".config",
                                   "show-folder-size-nautilus.conf"),
                      "w", encoding="utf-8") as handle:
                handle.write(contents)
        env = dict(os.environ)
        env["HOME"] = home
        env.pop("SHOW_FOLDER_SIZE_CACHE", None)
        out = subprocess.run([sys.executable, "-c", probe], env=env,
                             capture_output=True, text=True)
        if out.returncode:
            return "error: " + out.stderr.strip().splitlines()[-1]
        return eval(out.stdout.strip())


off = value_with_config("numeric_sort=0\ncache_dir=\n")
check("switched off, the value is the plain text",
      off, (False, m.format_size(1000)))

on = value_with_config("cache_dir=\n")
check("absent from the config, it stays on",
      on, (True, m.sort_key(1000) + m.format_size(1000)))

for word in ("no", "off", "false", "FALSE"):
    check("numeric_sort=%s switches it off" % word,
          value_with_config("numeric_sort=%s\ncache_dir=\n" % word)[0], False)


print("\n%d failure(s), %d skipped" % (len(fails), len(skips)))
for line in fails:
    print("  " + line)
sys.exit(1 if fails else 0)
