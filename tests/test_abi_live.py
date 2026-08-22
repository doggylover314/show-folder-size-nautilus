#!/usr/bin/env python3
"""Run the extension's registration path against real Nautilus libraries.

test_abi_selection.py proves the right ABI gets chosen. This proves the code
behind that choice actually works on ABIs this machine does not have: it
builds the column with the same arguments the extension uses, sets the same
property, subclasses the same two interfaces, instantiates the provider and
calls get_columns(), against the genuine libnautilus-extension from Nautilus
42.6 (ABI 3.0) and 50.2.2 (ABI 4.1).

What this does NOT prove: that the column appears. That needs a running file
manager on those releases, which is not something a test here can do. Read a
pass as "registers cleanly", not as "works".

Needs tests/fetch-abi-fixtures.sh to have been run; skips cleanly if not.

    tests/test_abi_live.py            # every ABI with fixtures present
    tests/test_abi_live.py 3.0        # one, with the env already set up
"""
import glob
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")


def fixture_paths(abi):
    """(dir holding the .so, dir holding the .typelib) or None if absent."""
    libs = glob.glob(os.path.join(FIXTURES, "lib-%s" % abi, "usr", "lib", "*",
                                  "libnautilus-extension.so.*"))
    types = glob.glob(os.path.join(FIXTURES, "typelib-%s" % abi, "usr", "lib",
                                   "*", "girepository-1.0",
                                   "Nautilus-%s.typelib" % abi))
    if not libs or not types:
        return None
    return os.path.dirname(libs[0]), os.path.dirname(types[0])


# --- driver: re-exec per ABI with the loader environment set ---------------
#
# LD_LIBRARY_PATH has to be set before the process starts, so each ABI runs
# in its own child rather than being switched inside one interpreter. That
# also keeps a crash in one from taking the others down.
if len(sys.argv) < 2:
    if not os.path.isdir(FIXTURES):
        print("SKIP: no fixtures. Run tests/fetch-abi-fixtures.sh first.")
        sys.exit(0)

    failed, ran = [], 0
    for abi in ("3.0", "4.0", "4.1"):
        paths = fixture_paths(abi)
        if paths is None:
            print("SKIP ABI %s: no fixture" % abi)
            continue
        lib_dir, typelib_dir = paths
        env = dict(os.environ)
        env["LD_LIBRARY_PATH"] = lib_dir
        env["GI_TYPELIB_PATH"] = typelib_dir
        ran += 1
        if subprocess.run([sys.executable, os.path.abspath(__file__), abi],
                          env=env).returncode:
            failed.append(abi)
        print()

    if not ran:
        print("SKIP: fixtures directory has nothing usable in it.")
        sys.exit(0)
    print("%d ABI(s) exercised, %d failed" % (ran, len(failed)))
    sys.exit(1 if failed else 0)


# --- one ABI, in a child with the environment already right ----------------
ABI = sys.argv[1]

import gi                                                      # noqa: E402
gi.require_version("Nautilus", ABI)
from gi.repository import GObject, Nautilus                    # noqa: E402

fails = []


def check(label, fn):
    try:
        result = fn()
    except Exception as exc:
        print("  %-52s FAIL  %s: %s" % (label, type(exc).__name__, exc))
        fails.append(label)
        return None
    print("  %-52s PASS  %r" % (label, result))
    return result


# Kept deliberately identical to the extension's own values.
COLUMN_ID = "ShowFolderSize::total_size"
ATTRIBUTE = "total_size"
LABEL = "Total Size"
DESCRIPTION = "Recursive size of a folder's contents"

print("libnautilus-extension %s, live:" % ABI)
check("ColumnProvider is an interface",
      lambda: Nautilus.ColumnProvider.__name__)
check("InfoProvider is an interface", lambda: Nautilus.InfoProvider.__name__)
check("OperationResult.COMPLETE exists",
      lambda: int(Nautilus.OperationResult.COMPLETE))


def build_column():
    column = Nautilus.Column(name=COLUMN_ID, attribute=ATTRIBUTE, label=LABEL,
                             description=DESCRIPTION)
    # The extension guards this in a try/except because it was unsure the
    # property existed everywhere. It does, on all three ABIs -- but the
    # guard stays, because a future ABI is exactly what it is there for.
    column.set_property("xalign", 1.0)
    return (column.get_property("name"), column.get_property("attribute"),
            column.get_property("xalign"))


check("Column(name, attribute, label, description) + xalign", build_column)


class Probe(GObject.GObject, Nautilus.ColumnProvider, Nautilus.InfoProvider):
    """The same class shape as ShowFolderSizeColumn, minus the measuring."""

    def get_columns(self):
        return (Nautilus.Column(name=COLUMN_ID, attribute=ATTRIBUTE,
                                label=LABEL, description=DESCRIPTION),)

    def update_file_info_full(self, provider, handle, closure, file_info):
        return Nautilus.OperationResult.COMPLETE

    def update_file_info(self, file_info):
        pass

    def cancel_update(self, provider, handle):
        pass


probe = check("instantiate GObject + ColumnProvider + InfoProvider", Probe)
if probe is not None:
    check("get_columns() returns a Column",
          lambda: type(probe.get_columns()[0]).__name__)
    check("both interfaces registered on the instance",
          lambda: (isinstance(probe, Nautilus.ColumnProvider),
                   isinstance(probe, Nautilus.InfoProvider)))

print("  -> %d failure(s) on ABI %s" % (len(fails), ABI))
sys.exit(1 if fails else 0)
