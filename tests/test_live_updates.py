#!/usr/bin/env python3
"""Does a change on disk reach the Total Size cell while you are looking?

Four defects, each found by running the extension inside a real Nautilus
46.4 under Xvfb, and each tested here without one:

  1. A file written INSIDE a subfolder of a row (Downloads/X/sub/file) was
     never noticed: only the row itself was watched.  Small trees are now
     watched all the way down -- _small_tree, _on_scanned.
  2. A change that WAS noticed dropped the cached total but never told
     Nautilus, so the cell kept the old number until you navigated away and
     back.  Rows are now re-measured and redrawn -- _on_fs_change,
     _schedule_refresh, _refresh_rows.
  3. While re-measuring, a changed row flipped to "Calculating...", which
     sorts as zero, so in a view sorted by this column it jumped to the far
     end and back on every update.  It now keeps its old size -- _invalidate,
     _resolve.
  4. Worker threads starved for the GIL whenever Nautilus was idle, so an
     EMPTY folder took 10s to measure.  _pump fixes that; here we check it
     starts and, as importantly, stops.

The methods are called with a stand-in for `self`, so none of this needs a
file manager, a display, or a main loop.  What that cannot show -- the cell
actually changing on screen -- was checked live, and is described in
tests/README.md.

Run directly, or via tests/run-tests.sh.  Exits non-zero on failure.
"""
import os
import sys
import tempfile
from collections import OrderedDict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

fails = []


def check(label, got, want):
    ok = got == want
    print("  %-62s %s" % (label, "PASS" if ok else "FAIL"))
    if not ok:
        fails.append("%s: wanted %r, got %r" % (label, want, got))


try:
    from nautilus_stub import load_extension
    m = load_extension()
except Exception as exc:
    print("SKIP: cannot import the extension here: %r" % (exc,))
    sys.exit(0)

from gi.repository import Gio, GLib  # noqa: E402

Col = m.ShowFolderSizeColumn
EV = Gio.FileMonitorEvent


class Stand:
    """A bare object to stand in for the provider's `self`."""

    def __init__(self, **state):
        self.__dict__.update(state)


class Monitor:
    def __init__(self):
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


class Changed:
    def __init__(self, path):
        self._path = path

    def get_path(self):
        return self._path


class Location:
    def __init__(self, path):
        self._path = path

    def get_path(self):
        return self._path


class Info:
    """Just enough of a Nautilus.FileInfo for _resolve."""

    def __init__(self, path):
        self._path = path

    def get_uri_scheme(self):
        return "file"

    def get_location(self):
        return Location(self._path)


def bind(stand, *names):
    """Give a stand-in the real methods it calls on itself."""
    for name in names:
        method = getattr(Col, name)
        setattr(stand, name,
                lambda *a, _m=method, **k: _m(stand, *a, **k))


# --- 1. which directories get watched ---------------------------------------
print("_small_tree -- what is watched below a row:")
with tempfile.TemporaryDirectory() as root:
    for sub in ("a", "a/deep", "b"):
        os.makedirs(os.path.join(root, sub))
    open(os.path.join(root, "a", "file"), "w").close()
    os.symlink(os.path.join(root, "a"), os.path.join(root, "link"))

    found = m._small_tree(root, 10)
    check("finds every directory, at every depth",
          sorted(os.path.relpath(p, root) for p in found),
          ["a", "a/deep", "b"])
    check("does not follow a symlink to a directory",
          any(p.endswith("link") for p in found), False)
    check("returns None once over the limit", m._small_tree(root, 2), None)
    check("exactly at the limit still returns the list",
          len(m._small_tree(root, 3)), 3)

    # The cost claim: however big the tree, at most limit + 1 reads.
    for i in range(60):
        os.makedirs(os.path.join(root, "b", "many-%02d" % i))
    reads = []
    real_scandir = os.scandir
    os.scandir = lambda p: (reads.append(p), real_scandir(p))[1]
    try:
        result = m._small_tree(root, 5)
    finally:
        os.scandir = real_scandir
    check("a 63-folder tree over a limit of 5 gives None", result, None)
    check("... after at most limit + 1 directory reads", len(reads) <= 6, True)

check("a directory that cannot be read is skipped, not fatal",
      m._small_tree("/nonexistent/path/for/test", 5), [])


# --- 2. stale, not gone -------------------------------------------------------
print("\n_invalidate -- keep the number, mark it out of date:")
st = Stand(_cache=OrderedDict({"/d": (123, 5_000_000)}), _dirty_shards=set())
check("marking a cached total stale reports a change",
      Col._invalidate(st, "/d"), True)
check("... and keeps the size, with the stale marker",
      st._cache.get("/d"), (m.STALE_MTIME, 5_000_000))
check("... and dirties its shard so the marker is saved",
      st._dirty_shards, {m.shard_for("/d")})
check("marking it again is not a change", Col._invalidate(st, "/d"), False)
check("remove=True drops it outright",
      (Col._invalidate(st, "/d", remove=True), "/d" in st._cache),
      (True, False))
check("an uncached path is not a change", Col._invalidate(st, "/x"), False)
check("no real directory can collide with the stale marker",
      m.STALE_MTIME < 0, True)


# --- 3. what the cell says while re-measuring --------------------------------
print("\n_resolve -- what the cell shows:")
with tempfile.TemporaryDirectory() as folder:
    mtime = os.lstat(folder).st_mtime_ns

    def resolve(cache):
        st = Stand(_cache=OrderedDict(cache), _awaiting_reread=set(),
                   _rows=OrderedDict(), _cost={}, _scanned=set(),
                   _watch=lambda p: None, _scan_tree=lambda p: None)
        bind(st, "_remember_row")
        text, path, _mtime = Col._resolve(st, Info(folder))
        return m.visible_text(text), path is not None, st

    text, queued, st = resolve({})
    check("never measured: Calculating..., and queued",
          (text, queued), (m.PENDING_TEXT, True))
    check("... and the folder is remembered as a row", folder in st._rows, True)

    text, queued, _st = resolve({folder: (m.STALE_MTIME, 5_000_000)})
    check("out of date: the OLD size, not Calculating..., and queued",
          (text, queued), (m.format_size(5_000_000), True))

    text, queued, _st = resolve({folder: (mtime - 1, 7_000_000)})
    check("mtime moved on: also the old size while re-measuring",
          (text, queued), (m.format_size(7_000_000), True))

    text, queued, _st = resolve({folder: (m.STALE_MTIME, -1)})
    check("a stale FAILED entry has no size to show: Calculating...",
          (text, queued), (m.PENDING_TEXT, True))

    text, queued, _st = resolve({folder: (mtime, 9_000_000)})
    check("current: the size, and nothing queued",
          (text, queued), (m.format_size(9_000_000), False))


# --- 4. a change on disk ----------------------------------------------------
print("\n_on_fs_change -- a change reaches the rows above it:")


def fs_stand(cache, rows, monitors=None, deep=None):
    st = Stand(_cache=OrderedDict(cache), _dirty_shards=set(),
               _monitors=OrderedDict(monitors or {}),
               _deep=OrderedDict(deep or {}),
               _rows=OrderedDict((r, object()) for r in rows),
               _cost={}, _scanned=set(rows), refreshed=[], saves=[0])
    st._schedule_save = lambda: st.saves.__setitem__(0, st.saves[0] + 1)
    st._schedule_refresh = lambda paths: st.refreshed.extend(paths)
    bind(st, "_invalidate")
    return st


st = fs_stand({"/h/Downloads/X": (1, 100), "/h/Downloads": (2, 900)},
              rows=["/h/Downloads/X"])
Col._on_fs_change(st, None, Changed("/h/Downloads/X/sub/new.pdf"), None,
                  EV.CHANGED)
check("a write two levels down marks the row stale, size kept",
      st._cache.get("/h/Downloads/X"), (m.STALE_MTIME, 100))
check("... and every cached ancestor", st._cache.get("/h/Downloads"),
      (m.STALE_MTIME, 900))
check("... and asks for the row to be refreshed",
      "/h/Downloads/X" in st.refreshed, True)
check("... and schedules one save", st.saves[0], 1)

mon = Monitor()
st = fs_stand({"/h/X": (1, 100), "/h/X/gone": (3, 40)}, rows=["/h/X"],
              deep={"/h/X/gone": mon})
Col._on_fs_change(st, None, Changed("/h/X/gone"), None, EV.DELETED)
check("a deleted folder is dropped outright, not kept as stale",
      "/h/X/gone" in st._cache, False)
check("... its watch is cancelled and released",
      (mon.cancelled, "/h/X/gone" in st._deep), (True, False))
check("... and its parent is marked stale, not dropped",
      st._cache.get("/h/X"), (m.STALE_MTIME, 100))
check("... and the deleted folder itself is not asked to refresh",
      "/h/X/gone" in st.refreshed, False)

st = fs_stand({"/h/X": (1, 100)}, rows=["/h/X"])
Col._on_fs_change(st, None, Changed("/h/X/f"), None, EV.CHANGES_DONE_HINT)
check("CHANGES_DONE_HINT is ignored (CHANGED already covered it)",
      (st._cache.get("/h/X"), st.refreshed), ((1, 100), []))


# --- 5. deep watches over the limit -----------------------------------------
print("\n_on_scanned -- a tree that outgrew the limit:")
under = {p: Monitor() for p in ("/r/root/a", "/r/root/a/b")}
beside = {p: Monitor() for p in ("/r/root-other/y", "/r/elsewhere")}
st = Stand(_scans_pending=1, _rows=OrderedDict({"/r/root": object()}),
           _deep=OrderedDict({**under, **beside}))
Col._on_scanned(st, "/r/root", None)
check("watches below it are cancelled", all(x.cancelled for x in under.values()),
      True)
check("... and released", sorted(st._deep), sorted(beside))
check("a sibling that merely shares the name prefix is untouched",
      any(x.cancelled for x in beside.values()), False)
check("the scan is counted as finished", st._scans_pending, 0)

watched = []
st = Stand(_scans_pending=1, _rows=OrderedDict({"/r/root": object()}),
           _deep=OrderedDict(), _watch_deep=watched.append)
Col._on_scanned(st, "/r/root", ["/r/root/a", "/r/root/b"])
check("a small tree gets every folder watched", watched,
      ["/r/root/a", "/r/root/b"])

st = Stand(_scans_pending=1, _rows=OrderedDict(), _deep=OrderedDict(),
           _watch_deep=watched.append)
watched.clear()
Col._on_scanned(st, "/r/closed", ["/r/closed/a"])
check("a row that has gone meanwhile arms nothing", watched, [])


# --- 6. refresh throttling --------------------------------------------------
print("\n_schedule_refresh / _refresh_rows -- when a row is re-measured:")
timers = []
real_timeout_add = m.GLib.timeout_add
m.GLib.timeout_add = lambda ms, fn, *a: (timers.append(ms), 1)[1]
try:
    st = Stand(_rows=OrderedDict({"/a": 1, "/big": 2}), _cost={"/big": 2.0},
               _refresh_due=set(), _refresh_id=None,
               _refresh_rows=lambda: None)
    Col._schedule_refresh(st, ["/nope"])
    check("paths that are not rows schedule nothing", timers, [])
    Col._schedule_refresh(st, ["/a"])
    check("a cheap row waits REFRESH_MIN_MS", timers, [m.REFRESH_MIN_MS])
    Col._schedule_refresh(st, ["/big"])
    check("a second change while a timer is pending adds no timer",
          (len(timers), st._refresh_due), (1, {"/a", "/big"}))
    st._refresh_id = None
    timers.clear()
    Col._schedule_refresh(st, ["/big"])
    check("a 2s measurement is re-done at most every 8s",
          timers, [int(2.0 * m.REFRESH_COST_FACTOR * 1000)])
    st._cost["/big"] = 3600.0
    st._refresh_id = None
    timers.clear()
    Col._schedule_refresh(st, ["/big"])
    check("... capped at REFRESH_MAX_MS", timers, [m.REFRESH_MAX_MS])
finally:
    m.GLib.timeout_add = real_timeout_add

with tempfile.TemporaryDirectory() as folder:
    enqueued, again = [], []
    st = Stand(_rows=OrderedDict({folder: "info", "/busy": "i2",
                                  "/gone/x": "i3"}),
               _jobs={"/busy": ["x"]}, _scanned={folder},
               _refresh_due={folder, "/busy", "/gone/x", "/not-a-row"},
               _refresh_id=7,
               _enqueue=lambda p, mt, fi: enqueued.append((p, mt, fi)),
               _schedule_refresh=lambda paths: again.extend(paths))
    Col._refresh_rows(st)
    check("a changed row is queued with its current mtime and FileInfo",
          enqueued, [(folder, os.lstat(folder).st_mtime_ns, "info")])
    check("... and re-scanned, since it may have new folders",
          folder in st._scanned, False)
    check("a row already mid-measurement is retried later, not joined",
          again, ["/busy"])
    check("the timer is cleared and the queue emptied",
          (st._refresh_id, st._refresh_due), (None, set()))


# --- 7. the GIL pump --------------------------------------------------------
print("\n_pump -- runs while there is work, and only then:")
idle = dict(_jobs={}, _scans_pending=0, _saves_pending=0, _cache_loaded=True)
check("idle: not busy", Col._busy(Stand(**idle)), False)
for field, value in (("_jobs", {"/x": []}), ("_scans_pending", 1),
                     ("_saves_pending", 1), ("_cache_loaded", False)):
    check("busy while %s = %r" % (field, value),
          Col._busy(Stand(**{**idle, field: value})), True)

st = Stand(**idle, _pump_id=99)
bind(st, "_busy")
check("idle: the pump removes itself", Col._pump(st), GLib.SOURCE_REMOVE)
check("... and forgets its timer id so it can start again", st._pump_id, None)
st = Stand(**{**idle, "_jobs": {"/x": []}}, _pump_id=99)
bind(st, "_busy")
check("busy: the pump keeps going", Col._pump(st), GLib.SOURCE_CONTINUE)


print("\n%d failure(s)" % len(fails))
for line in fails:
    print("  " + line)
sys.exit(1 if fails else 0)
