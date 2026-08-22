#!/usr/bin/env python3
"""Which libnautilus-extension ABI does the extension choose, and why.

Needs no network and no fixtures: the two seams (gi.require_version and
/proc/self/maps) are stubbed, so every combination can be tested here,
including ones no single machine can produce -- a 4.1-only desktop, a future
4.2, both 3.0 and 4.x installed at once.

There is one unstubbed check first, against whatever this machine really has.

Run directly, or via tests/run-tests.sh.  Exits non-zero on failure.
"""
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")

# Where fetch-abi-fixtures.sh puts the extracted Ubuntu 22.04 typelib.
THREE_0_TYPELIB = os.path.join(
    FIXTURES, "typelib-3.0", "usr", "lib", "x86_64-linux-gnu",
    "girepository-1.0")

fails = []
skips = []


def check(label, got, want):
    ok = got == want
    print("  %-56s %s  (got %r)" % (label, "PASS" if ok else "FAIL", got))
    if not ok:
        fails.append("%s: wanted %r, got %r" % (label, want, got))


def skip(label, why):
    print("  %-56s SKIP  %s" % (label, why))
    skips.append(label)


# --- 1. the real thing, on this machine ------------------------------------
print("real import:")
probe = ("import sys; sys.path.insert(0, %r); "
         "import show_folder_size as m; print(m.NAUTILUS_ABI)" % REPO)

env = dict(os.environ)
env.pop("GI_TYPELIB_PATH", None)
out = subprocess.run([sys.executable, "-c", probe], env=env,
                     capture_output=True, text=True)
if out.returncode:
    skip("imports and picks an ABI", "no usable Nautilus typelib here")
    print(("    " + out.stderr.strip().replace("\n", "\n    "))[:500])
else:
    picked = out.stdout.strip()
    check("imports and picks an ABI", bool(picked) and picked[0].isdigit(),
          True)
    print("    this machine resolved to ABI %s" % picked)

    # Adding an older typelib to the path must not drag the choice backwards.
    if os.path.isdir(THREE_0_TYPELIB):
        env["GI_TYPELIB_PATH"] = THREE_0_TYPELIB
        out = subprocess.run([sys.executable, "-c", probe], env=env,
                             capture_output=True, text=True)
        check("3.0 also on the path does not downgrade the choice",
              out.stdout.strip(), picked)
    else:
        skip("3.0 also on the path does not downgrade the choice",
             "run tests/fetch-abi-fixtures.sh")

# --- 2. the selection logic, with both seams stubbed -----------------------
print("\nselection logic (stubbed):")
sys.path.insert(0, REPO)
try:
    import show_folder_size as m
except Exception as exc:
    print("  cannot import the extension here: %r" % (exc,))
    print("\n%d failure(s), %d skipped" % (len(fails), len(skips)))
    sys.exit(1 if fails else 0)


def pick(installed, loaded_soname, enumerated=None):
    """Run the real _pick_nautilus_abi() against a pretend system.

    `installed` is what require_version will accept; `enumerated` is what
    enumerate_versions reports, which is deliberately allowed to differ --
    an old pygobject reports nothing and the fallback list has to carry it.
    """
    real_require = m.gi.require_version
    real_loaded = m._loaded_soname
    gi_module = sys.modules["gi"]
    real_repo = getattr(gi_module, "Repository", None)

    def fake_require(namespace, version):
        if namespace == "Nautilus" and version not in installed:
            raise ValueError("no %s %s" % (namespace, version))

    class FakeRepo:
        @staticmethod
        def get_default():
            return FakeRepo()

        def enumerate_versions(self, namespace):
            return list(installed if enumerated is None else enumerated)

    m.gi.require_version = fake_require
    m._loaded_soname = lambda: loaded_soname
    gi_module.Repository = FakeRepo
    try:
        return m._pick_nautilus_abi()
    finally:
        m.gi.require_version = real_require
        m._loaded_soname = real_loaded
        if real_repo is not None:
            gi_module.Repository = real_repo


SO1 = "libnautilus-extension.so.1"      # ABI 3.0
SO4 = "libnautilus-extension.so.4"      # ABI 4.0 and 4.1

# One ABI installed: take it.
check("4.1 only (Nautilus 49, 50)", pick(["4.1"], SO4), "4.1")
check("4.0 only (Nautilus 43-48)", pick(["4.0"], SO4), "4.0")
check("3.0 only (Nautilus 42 and earlier)", pick(["3.0"], SO1), "3.0")

# Newest wins, including versions no list here knows about.
check("4.0 and 4.1 both present -> newest", pick(["4.0", "4.1"], SO4), "4.1")
check("a future 4.2 is picked up with no code change",
      pick(["4.2"], SO4), "4.2")
check("a future 5.0 beats 4.1", pick(["5.0", "4.1"], SO4), "5.0")
check("10.0 outranks 9.0 (int compare, not string)",
      pick(["9.0", "10.0"], SO4), "10.0")

# The case /proc/self/maps exists for: two ABIs installed, one is wrong.
check("both installed, nautilus holds so.1 -> 3.0",
      pick(["3.0", "4.1"], SO1), "3.0")
check("both installed, nautilus holds so.4 -> 4.1",
      pick(["3.0", "4.1"], SO4), "4.1")
check("both installed, no nautilus (the indexer) -> newest",
      pick(["3.0", "4.1"], None), "4.1")

# Narrowing reorders, it must never eliminate. A filter here would raise
# ImportError on a machine that had a perfectly good typelib.
check("so.1 loaded but only 4.1 installed -> still 4.1",
      pick(["4.1"], SO1), "4.1")

# enumerate_versions blind (very old pygobject): the fallback list carries it.
check("enumerate blind, 3.0 installed", pick(["3.0"], SO1, enumerated=[]),
      "3.0")
check("enumerate blind, 4.1 installed", pick(["4.1"], SO4, enumerated=[]),
      "4.1")

# Degenerate input must not raise inside a running file manager.
check("nothing installed -> None, caller raises ImportError",
      pick([], None, enumerated=[]), None)
check("an unparseable version sorts last instead of first",
      pick(["weird", "4.0"], SO4), "4.0")

print("\n%d failure(s), %d skipped" % (len(fails), len(skips)))
for f in fails:
    print("  " + f)
sys.exit(1 if fails else 0)
