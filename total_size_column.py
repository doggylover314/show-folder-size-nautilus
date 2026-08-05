#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
total_size_column.py -- a "Total Size" column for GNOME Files (Nautilus) 46.

WHAT IT DOES
------------
Nautilus' built-in "Size" column shows an item count for folders ("12 items").
This extension adds a second, optional column called "Total Size" that shows
the recursive on-disk size of a folder's contents, the same number you get
from right-click -> Properties.

Sizes are measured in the background and cached on disk, keyed by directory
mtime, so scrolling a folder list never blocks the UI and re-visiting a folder
is instant -- across restarts, not just within a session.  Directories you
visit are watched, so edits anywhere beneath them drop the stale total.  While
a folder is being measured the column shows "Calculating...".

Regular files are left BLANK in this column on purpose: Nautilus' own "Size"
column already shows them, and printing a second copy next to it just invites
a mismatch.  This column is only about folders.

SAFETY / AUDIT NOTES  (this is the whole story -- grep the file to confirm)
--------------------------------------------------------------------------
READ THIS IF YOU AUDITED AN EARLIER VERSION.  Up to and including v0.2.2 this
extension wrote nothing at all.  That is no longer true: since v0.3.0 it
writes exactly ONE file, its size cache.  Everything else is unchanged.

  * Writes exactly one file: the size cache (see CACHE_PATH below, by default
    ~/.cache/nautilus-total-size/sizes.json).  It is written atomically --
    a temporary file in the same directory, then os.replace() -- so a crash
    mid-write cannot corrupt it.  It contains directory paths, their
    modification times and their sizes in bytes.  Nothing else.  It is safe to
    delete at any time; the extension just rebuilds it.
    If you want the old no-writes behaviour, set the cache path to an empty
    value (see CONFIGURATION) and nothing is ever written.
  * All other filesystem access is reads.  Sizes come from
    Gio.File.measure_disk_usage() (the same GIO call Nautilus' own Properties
    window uses), with os.walk() + os.stat() as a fallback.  There is no
    unlink, rename, mkdir outside the cache directory, or chmod.
    (CPython itself writes a __pycache__/ bytecode directory next to this file
    when nautilus imports it, as it does for any Python module.  That is the
    interpreter, not this extension, and it is safe to delete.)
  * No network.  There is no socket, urllib, requests, http, or DNS use.
  * No subprocesses.  There is no os.system, subprocess, popen, exec*, or
    fork.  Nothing external is invoked.
  * No symlink following.  GIO does not descend into symlinked directories,
    and the os.walk fallback passes followlinks=False and skips symlinks, so
    there are no link loops and no directory tree is counted twice.
  * Imports are stdlib + PyGObject only: os, stat, sys, json, queue, tempfile,
    threading, time, collections, gi (GObject/GLib/Gio/Nautilus).  No
    third-party dependencies.

The only side effects are: CPU/IO from directory traversal, memory for the
result cache (bounded, see CACHE_LIMIT), inotify watches (bounded, see
MONITOR_LIMIT), the one cache file above, and the text drawn in the column.

CONFIGURATION
-------------
Where the cache lives, in order of precedence:

  1. the NAUTILUS_TOTAL_SIZE_CACHE environment variable
  2. cache_dir= in ~/.config/nautilus-total-size.conf
  3. cache_dir= in /etc/nautilus-total-size.conf   (set by the .deb installer)
  4. $XDG_CACHE_HOME/nautilus-total-size, i.e. ~/.cache/nautilus-total-size

Setting any of them to the empty string disables the on-disk cache entirely:
nothing is written, and sizes are remembered only for the current session.

WHY IT IS BUILT THIS WAY (three bugs' worth of hard-won detail)
--------------------------------------------------------------
* Sizes are formatted with GLib.format_size(), which is exactly what Nautilus
  uses for its own Size column.  That means base-10 units (kB/MB/GB, so 1 GiB
  reads as "1.1 GB") and correct localisation.  An earlier version hardcoded
  base-1024 with "KB" labels, which disagreed with the built-in Size column on
  every single file.  Follow the host, don't invent a convention.

* Measurement uses Gio.File.measure_disk_usage() rather than a Python walk.
  It is ~6x faster (measured: 189 GB / 314k files in 0.8s vs 4.9s) and it
  releases the GIL properly -- four concurrent measurements take 0.14s against
  0.11s for one, and a measuring worker leaves the main thread running Python
  at full speed.  (An earlier revision of this comment claimed GIL contention
  from os.walk was starving Nautilus' main thread.  That was measured badly
  and overstated: the speed is the honest reason, not the contention.)

* Results are posted to the main thread with GLib.idle_add() at
  PRIORITY_DEFAULT, NOT PRIORITY_DEFAULT_IDLE.  A busy Nautilus main loop can
  defer idle-priority callbacks more or less forever; that starvation is the
  likeliest reason early versions left folders on "Calculating..." with the
  walk long since finished.

* Delivery NEVER returns OperationResult.IN_PROGRESS.  Every update returns
  COMPLETE immediately -- with the real size if we know it, otherwise with the
  "Calculating..." placeholder -- and when the measurement lands we write the
  attribute and call FileInfo.invalidate_extension_info(), which makes Nautilus
  re-ask.  That second ask hits the cache and renders the number.

  This is the third delivery design in this file, so it is worth writing down
  why the obvious one is not used.  The asynchronous protocol
  (return IN_PROGRESS, keep the operation handle, later call
  info_provider_update_complete_invoke()) is the documented approach and looks
  correct, but in practice the completion never reached the view here: a
  100 GB folder measured in well under a second and still sat on
  "Calculating..." indefinitely.  Worse, an IN_PROGRESS that never completes
  is unrecoverable -- Nautilus is left waiting on a promise nothing will keep,
  and there is no timeout.  Returning COMPLETE cannot wedge anything: the
  worst case is a stale-looking cell that the next refresh fixes.  Given a
  choice between a protocol that is theoretically righter and one that
  degrades safely when it goes wrong, take the one that degrades safely.

  Because nothing ever returns IN_PROGRESS, Nautilus has no operation to
  cancel, so cancel_update() has nothing to do and the measurement Cancellable
  that used to hang off it is gone with it.

* The invalidate is retried a few times (see REFRESH_ATTEMPTS).  Retrying
  stops the moment Nautilus asks for the value again -- a cache hit clears the
  key -- so this self-terminates rather than looping.  It exists because a
  single invalidate proved unreliable in earlier versions, and a folder that
  silently never updates is worse than one extra no-op refresh.

* The cache stores byte counts, not formatted strings.  Formatting depends on
  the user's locale, and a cache written under one locale must not force stale
  text on another.

* Filesystem monitoring watches directories with GIO, but a watch only reports
  changes to a directory's *direct* children -- there is no recursive watch on
  Linux, and putting one on every subdirectory would exhaust the inotify limit
  on any real disk.  So when a watched directory changes, the cached total for
  that directory AND for every one of its ancestors is dropped, because a file
  written three levels down changes all of their totals.  That is what makes
  deep changes show up despite shallow watches.  Watches are bounded by
  MONITOR_LIMIT and evicted least-recently-used.

KNOWN LIMITATIONS (by design, called out so they don't surprise you)
--------------------------------------------------------------------
* Nautilus' built-in "Size" column cannot be hidden by an extension.  If you
  want only this one, untick "Size" yourself in Visible Columns.
* Deep changes are only noticed in directories currently being watched (the
  ones you have visited recently, up to MONITOR_LIMIT).  Change a file three
  levels below a folder nobody is watching and its cached total stays stale
  until the folder's own mtime changes or the cache entry ages out.  Reload
  the window (Ctrl+R) to force a recount.
* Nautilus sorts columns as plain strings, so clicking the "Total Size" header
  sorts alphabetically ("9.9 kB" before "1.2 GB"), not numerically.  The
  extension API has no sort-key hook, so this cannot be fixed from here.
* Totals are apparent size (sum of file sizes), not allocated blocks, so they
  differ slightly from `du` on sparse files.
* Measurement crosses mount points, so a folder containing a mounted volume
  includes that volume's contents.
* Only local ("file://") locations are measured; other URI schemes get a blank
  cell rather than a very slow recursive walk over the network.

DEBUGGING
---------
Tracing goes to stderr and can be switched on two ways:

  * NAUTILUS_TOTAL_SIZE_DEBUG=1 in nautilus' environment -- but note this is
    easy to lose: nautilus is D-Bus activated, so `NAUTILUS_TOTAL_SIZE_DEBUG=1
    nautilus` often just hands your request to a nautilus that is already
    running with a different environment, and the variable never arrives.
  * creating the marker file ~/.config/nautilus-total-size-debug (its contents
    are irrelevant; only its existence is checked, and only at import).  This
    survives however nautilus happens to get started, which makes it the
    reliable option.

Either way the output lands in the session journal, so with the marker file in
place just run:

    journalctl --user -f | grep total-size

Install:  ~/.local/share/nautilus-python/extensions/total_size_column.py
Requires: nautilus-python (python3-nautilus) for libnautilus-extension 4.0.
"""

import json
import os
import queue
import stat
import sys
import tempfile
import threading
import time
from collections import OrderedDict

import gi

gi.require_version("Nautilus", "4.0")
from gi.repository import Gio, GLib, GObject, Nautilus  # noqa: E402

__version__ = "0.3.0"

# --- tunables ---------------------------------------------------------------

COLUMN_ID = "NautilusPython::total_size"
ATTRIBUTE = "total_size"
COLUMN_LABEL = "Total Size"
PENDING_TEXT = "Calculating..."

WORKER_COUNT = 4          # background threads driving the measurement
CACHE_LIMIT = 20000       # max remembered path -> (mtime, bytes) entries
REFRESH_ATTEMPTS = 4      # how many times to nudge Nautilus to re-read a value
REFRESH_INTERVAL_MS = 750
WATCHDOG_INTERVAL_S = 5   # how often to look for lost work
STUCK_SECONDS = 45        # a measurement taking this long was lost, not slow
MONITOR_LIMIT = 256       # max directories watched at once (inotify is finite)
SAVE_DELAY_S = 10         # quiet period before the cache is written to disk

CONFIG_FILES = (
    os.path.join(os.path.expanduser("~"), ".config",
                 "nautilus-total-size.conf"),
    "/etc/nautilus-total-size.conf",
)


def _configured_cache_dir():
    """Resolve the cache directory.  '' anywhere means 'do not cache to disk'.

    Precedence: environment, then user config, then system config (which is
    what the .deb installer writes), then the XDG default.  Read-only: this
    only ever opens config files for reading.
    """
    from_env = os.environ.get("NAUTILUS_TOTAL_SIZE_CACHE")
    if from_env is not None:
        return from_env.strip()

    for config_path in CONFIG_FILES:
        try:
            with open(config_path, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if line.startswith("#") or "=" not in line:
                        continue
                    name, _, value = line.partition("=")
                    if name.strip() == "cache_dir":
                        return os.path.expanduser(value.strip())
        except OSError:
            continue

    xdg = os.environ.get("XDG_CACHE_HOME") or \
        os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(xdg, "nautilus-total-size")


CACHE_DIR = _configured_cache_dir()
CACHE_PATH = os.path.join(CACHE_DIR, "sizes.json") if CACHE_DIR else ""
CACHE_FORMAT = 1

_DEBUG_MARKER = os.path.join(
    os.path.expanduser("~"), ".config", "nautilus-total-size-debug")

# The marker file is checked because the environment variable is unreliable:
# nautilus is D-Bus activated, so the variable frequently never reaches the
# process that actually loads this extension.  os.path.exists() is a read.
_DEBUG = bool(os.environ.get("NAUTILUS_TOTAL_SIZE_DEBUG")) or \
    os.path.exists(_DEBUG_MARKER)


def _log(message):
    """Trace to stderr.  Must never raise, and never on the caller's account.

    This is called from worker threads, and an exception here would kill the
    worker for good.  stderr is a pipe to the journal; a burst of logging can
    fill it, and if nautilus left it non-blocking the write raises
    BlockingIOError.  Losing a debug line is fine.  Losing a worker is not.
    """
    if not _DEBUG:
        return
    try:
        print("[total-size] %s" % message, file=sys.stderr, flush=True)
    except Exception:
        pass


# --- measurement ------------------------------------------------------------

def format_size(num_bytes):
    """Format like the rest of the desktop does.

    GLib.format_size() is what Nautilus itself calls, so our numbers agree
    with the built-in Size column and follow the user's locale.  It is base-10
    (1024 -> '1.0 kB', 1 GiB -> '1.1 GB').
    """
    return GLib.format_size(num_bytes)


def _measure_with_gio(path, cancellable):
    """Recursive apparent size via GIO -- the call Properties uses.

    Returns bytes, or raises GLib.Error (including on cancellation).
    Releases the GIL for the duration, which keeps Nautilus responsive.
    """
    gfile = Gio.File.new_for_path(path)
    _ok, disk_usage, _dirs, _files = gfile.measure_disk_usage(
        Gio.FileMeasureFlags.APPARENT_SIZE,
        cancellable,
        None,          # no progress callback: it would fire on this thread
    )
    return disk_usage


def _measure_with_walk(path):
    """Fallback: sum regular-file sizes with os.walk + os.stat.

    Read-only.  Symlinked directories are not descended into
    (followlinks=False) and symlinks to files are skipped, so nothing is
    counted twice and link loops are impossible.  Hard-linked files are
    counted once.  Unreadable entries are skipped rather than aborting.
    """
    total = 0
    seen_hardlinks = set()

    for dirpath, _dirnames, filenames in os.walk(path, topdown=True,
                                                 followlinks=False):
        for name in filenames:
            try:
                info = os.stat(os.path.join(dirpath, name),
                               follow_symlinks=False)
            except OSError:
                continue

            mode = info.st_mode
            if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
                continue

            if info.st_nlink > 1:
                identity = (info.st_dev, info.st_ino)
                if identity in seen_hardlinks:
                    continue
                seen_hardlinks.add(identity)

            total += info.st_size

    return total


def directory_size(path, cancellable=None):
    """Recursive size of `path`, preferring GIO and falling back to os.walk."""
    try:
        return _measure_with_gio(path, cancellable)
    except GLib.Error as error:
        if cancellable is not None and cancellable.is_cancelled():
            raise
        _log("gio measure failed for %s (%s); falling back to os.walk"
             % (path, error.message))
        return _measure_with_walk(path)


# --- persistent cache -------------------------------------------------------
#
# On-disk shape:
#   {"format": 1, "entries": {"<path>": [<mtime_ns>, <bytes>], ...}}
# Byte counts, not formatted text -- see the header.  A negative byte count
# means "this failed to measure"; it is kept so a permission-denied folder
# is not retried on every single redraw.


def load_cache():
    """Read the cache.  Any problem returns an empty cache, never raises.

    A corrupt or unreadable cache is not worth a broken file manager: the
    worst case of ignoring it is that sizes get measured again.
    """
    if not CACHE_PATH:
        return OrderedDict()

    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, ValueError):
        return OrderedDict()

    if not isinstance(raw, dict) or raw.get("format") != CACHE_FORMAT:
        return OrderedDict()

    entries = OrderedDict()
    for path, value in (raw.get("entries") or {}).items():
        try:
            mtime_ns, num_bytes = value
            entries[str(path)] = (int(mtime_ns), int(num_bytes))
        except (TypeError, ValueError):
            continue          # skip the bad row, keep the good ones

    _log("loaded %d cached sizes from %s" % (len(entries), CACHE_PATH))
    return entries


def save_cache(entries):
    """Write the cache atomically.  Never raises.

    Atomic because the alternative is a truncated JSON file if nautilus dies
    mid-write, which would silently poison every future start: write a
    temporary file in the same directory, then os.replace() onto the target.
    """
    if not CACHE_PATH:
        return False

    payload = {
        "format": CACHE_FORMAT,
        "entries": {path: [mtime, size] for path, (mtime, size)
                    in entries.items()},
    }

    handle = None
    temp_path = None
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(dir=CACHE_DIR, prefix=".sizes-",
                                         suffix=".tmp")
        handle = os.fdopen(fd, "w", encoding="utf-8")
        json.dump(payload, handle)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        handle = None
        os.replace(temp_path, CACHE_PATH)
        temp_path = None
        _log("saved %d cached sizes to %s" % (len(entries), CACHE_PATH))
        return True
    except Exception as exc:
        _log("could not save cache: %r" % (exc,))
        return False
    finally:
        if handle is not None:
            try:
                handle.close()
            except Exception:
                pass
        if temp_path is not None:
            try:
                os.unlink(temp_path)      # only ever our own temp file
            except OSError:
                pass


# --- the extension ----------------------------------------------------------

class TotalSizeColumn(GObject.GObject,
                      Nautilus.ColumnProvider,
                      Nautilus.InfoProvider):
    """Registers the column and fills it in, lazily and off the main thread."""

    def __init__(self):
        super().__init__()
        # Everything below is touched only from the GTK main thread except
        # _work_queue, which is the thread-safe handoff to the workers.
        self._cache = load_cache()    # path -> (mtime_ns, bytes)
        self._jobs = {}               # path -> [FileInfo, ...]
        self._queued_at = {}          # path -> monotonic seconds
        self._awaiting_reread = set()  # paths nudged but not yet re-asked for
        self._monitors = OrderedDict()  # path -> Gio.FileMonitor (LRU)
        self._watchdog_id = None
        self._save_id = None
        self._dirty = False
        self._work_queue = queue.SimpleQueue()
        self._workers = []

    # -- Nautilus.ColumnProvider --------------------------------------------

    def get_columns(self):
        column = Nautilus.Column(
            name=COLUMN_ID,
            attribute=ATTRIBUTE,
            label=COLUMN_LABEL,
            description="Recursive size of a folder's contents",
        )
        try:
            # Right-align sizes where the Nautilus build supports it.
            column.set_property("xalign", 1.0)
        except (TypeError, ValueError):
            pass
        return (column,)

    # -- Nautilus.InfoProvider ----------------------------------------------

    def update_file_info_full(self, provider, handle, closure, file_info):
        """Entry point used by libnautilus-extension 4.0.

        Always COMPLETE, never IN_PROGRESS -- see the header for why.
        """
        self._fill_in(file_info)
        return Nautilus.OperationResult.COMPLETE

    def update_file_info(self, file_info):
        """Legacy one-argument entry point.  Identical behaviour."""
        self._fill_in(file_info)

    def cancel_update(self, provider, handle):
        """Nothing to cancel: this provider never reports IN_PROGRESS."""

    def _fill_in(self, file_info):
        try:
            text, path, mtime_ns = self._resolve(file_info)
        except Exception as exc:                      # never break the view
            _log("update failed: %r" % (exc,))
            file_info.add_string_attribute(ATTRIBUTE, "")
            return

        file_info.add_string_attribute(ATTRIBUTE, text)
        if path is not None:
            self._enqueue(path, mtime_ns, file_info)

    # -- value resolution ----------------------------------------------------

    def _resolve(self, file_info):
        """Return (text, path, mtime_ns).

        `path` is None when the text is final; otherwise it names the folder
        the caller should queue a measurement for.
        """
        if file_info.get_uri_scheme() != "file":
            return "", None, 0

        location = file_info.get_location()
        path = location.get_path() if location is not None else None
        if not path:
            return "", None, 0

        try:
            info = os.lstat(path)
        except OSError:
            return "", None, 0

        # Folders only.  Regular files already have Nautilus' Size column;
        # duplicating it here just creates a second number to disagree with.
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            return "", None, 0

        mtime_ns = info.st_mtime_ns
        cached = self._cache.get(path)
        if cached is not None and cached[0] == mtime_ns:
            self._cache.move_to_end(path)
            # Nautilus came back for this value, so the nudging worked and
            # any pending retry can stop.
            self._awaiting_reread.discard(path)
            self._watch(path)
            return (format_size(cached[1]) if cached[1] >= 0 else ""), None, 0

        return PENDING_TEXT, path, mtime_ns

    # -- background work -----------------------------------------------------

    def _enqueue(self, path, mtime_ns, file_info):
        """Queue a measurement for `path`, or join one already running."""
        waiters = self._jobs.get(path)
        if waiters is not None:
            if file_info not in waiters:
                waiters.append(file_info)    # already being measured
            return

        self._jobs[path] = [file_info]
        self._queued_at[path] = time.monotonic()
        self._start_workers()
        self._work_queue.put((path, mtime_ns))
        self._start_watchdog()
        _log("queued %s" % (path,))

    def _start_watchdog(self):
        if self._watchdog_id is None:
            self._watchdog_id = GLib.timeout_add_seconds(
                WATCHDOG_INTERVAL_S, self._watchdog)

    def _watchdog(self):
        """Re-queue jobs that vanished, and stop once the queue drains.

        Belt and braces for the failure this version is about: if a job has
        been outstanding far longer than any real measurement takes, the work
        was lost rather than delayed.  Measurements here run in about a
        second, so STUCK_SECONDS is orders of magnitude clear of normal --
        this should never fire, and if it does the log says so plainly.
        """
        if not self._jobs:
            self._watchdog_id = None
            return GLib.SOURCE_REMOVE

        now = time.monotonic()
        for path, queued_at in list(self._queued_at.items()):
            if path not in self._jobs or now - queued_at < STUCK_SECONDS:
                continue
            _log("job for %s stuck for %.0fs; re-queueing (%d live workers)"
                 % (path, now - queued_at, len(self._workers)))
            self._queued_at[path] = now
            self._start_workers()
            try:
                mtime_ns = os.lstat(path).st_mtime_ns
            except OSError:
                self._jobs.pop(path, None)
                self._queued_at.pop(path, None)
                continue                      # folder went away; drop the job
            self._work_queue.put((path, mtime_ns))

        return GLib.SOURCE_CONTINUE

    def _start_workers(self):
        """Ensure WORKER_COUNT live workers, replacing any that have died.

        Called on every enqueue rather than once, so the pool heals itself.
        A pool that silently shrinks to zero looks exactly like "the extension
        stopped working": jobs queue up and nothing ever measures them, with
        no error in sight.  That happened, so it is now impossible.
        """
        self._workers = [t for t in self._workers if t.is_alive()]
        while len(self._workers) < WORKER_COUNT:
            thread = threading.Thread(
                target=self._worker_loop,
                name="total-size-%d" % len(self._workers),
                daemon=True,
            )
            thread.start()
            self._workers.append(thread)

    def _worker_loop(self):
        """Worker thread: measure, then hand the result to the main thread.

        Touches no GTK/Nautilus object -- the only crossing point back is
        GLib.idle_add(), which is documented as thread-safe.

        The entire body is guarded.  Anything that escapes here kills this
        thread permanently and silently, and four such deaths leave the queue
        filling up forever.  Nothing is worth that, so nothing is allowed out.
        """
        while True:
            try:
                path, mtime_ns = self._work_queue.get()
                started = time.monotonic()
                _log("start %s" % (path,))

                try:
                    num_bytes = directory_size(path)
                except GLib.Error as error:
                    _log("measure of %s failed: %s" % (path, error.message))
                    num_bytes = -1
                except Exception as exc:
                    _log("measure of %s failed: %r" % (path, exc))
                    num_bytes = -1

                _log("measured %s in %.2fs -> %s"
                     % (path, time.monotonic() - started,
                        format_size(num_bytes) if num_bytes >= 0 else "failed"))
                # PRIORITY_DEFAULT, not PRIORITY_DEFAULT_IDLE: a busy Nautilus
                # main loop will starve idle-priority callbacks indefinitely.
                GLib.idle_add(self._on_result, path, mtime_ns, num_bytes,
                              priority=GLib.PRIORITY_DEFAULT)
            except Exception as exc:                  # never let a worker die
                _log("worker recovered from %r" % (exc,))

    def _on_result(self, path, mtime_ns, num_bytes):
        """Main thread: cache the answer, then get Nautilus to re-read it."""
        self._cache[path] = (mtime_ns, num_bytes)
        self._cache.move_to_end(path)
        while len(self._cache) > CACHE_LIMIT:
            self._cache.popitem(last=False)
        self._schedule_save()
        self._watch(path)

        text = format_size(num_bytes) if num_bytes >= 0 else ""
        self._queued_at.pop(path, None)
        file_infos = self._jobs.pop(path, [])
        for file_info in file_infos:
            file_info.add_string_attribute(ATTRIBUTE, text)

        if file_infos:
            self._awaiting_reread.add(path)
            self._nudge(path, file_infos, 1)

        return GLib.SOURCE_REMOVE

    # -- persistence ---------------------------------------------------------

    def _schedule_save(self):
        """Write the cache after things go quiet, not on every result.

        Measuring one directory can produce dozens of results in a second;
        writing the whole file each time would be pointless churn.
        """
        self._dirty = True
        if CACHE_PATH and self._save_id is None:
            self._save_id = GLib.timeout_add_seconds(SAVE_DELAY_S, self._save)

    def _save(self):
        self._save_id = None
        if not self._dirty:
            return GLib.SOURCE_REMOVE
        self._dirty = False
        # Copy on the main thread, write off it: serialising 20k entries is
        # not something to do in the middle of the file manager's event loop.
        snapshot = OrderedDict(self._cache)
        threading.Thread(target=save_cache, args=(snapshot,),
                         name="total-size-save", daemon=True).start()
        return GLib.SOURCE_REMOVE

    # -- filesystem monitoring -----------------------------------------------

    def _watch(self, path):
        """Watch `path` for changes, bounded and least-recently-used."""
        if path in self._monitors:
            self._monitors.move_to_end(path)
            return
        try:
            monitor = Gio.File.new_for_path(path).monitor_directory(
                Gio.FileMonitorFlags.WATCH_MOVES, None)
        except GLib.Error as error:
            _log("cannot watch %s: %s" % (path, error.message))
            return

        monitor.connect("changed", self._on_fs_change)
        self._monitors[path] = monitor

        while len(self._monitors) > MONITOR_LIMIT:
            old_path, old_monitor = self._monitors.popitem(last=False)
            old_monitor.cancel()
            _log("stopped watching %s (limit reached)" % old_path)

    def _on_fs_change(self, _monitor, changed_file, _other, event_type):
        """Something changed under a watched directory: drop stale totals.

        A watch only sees direct children, so the change is attributed to the
        containing directory and then walked up: a file written three levels
        down changes the total of every ancestor, and dropping only the
        immediate one would leave the folder you are actually looking at
        showing a stale number.
        """
        if event_type == Gio.FileMonitorEvent.CHANGES_DONE_HINT:
            return                       # already handled by the CHANGED event

        path = changed_file.get_path()
        if not path:
            return

        directory = os.path.dirname(path) if not os.path.isdir(path) else path
        dropped = 0
        while True:
            if self._cache.pop(directory, None) is not None:
                dropped += 1
            parent = os.path.dirname(directory)
            if parent == directory:
                break
            directory = parent

        if dropped:
            self._schedule_save()
            _log("%s changed; dropped %d cached total(s)" % (path, dropped))

    def _nudge(self, path, file_infos, attempt):
        """Ask Nautilus to re-read the value, retrying a bounded few times.

        invalidate_extension_info() makes Nautilus call us again, and that
        call hits the cache and renders the real size.  A single invalidate
        proved unreliable in earlier versions, so retry -- but stop the moment
        Nautilus actually asks (see _resolve, which discards the key), and
        give up after REFRESH_ATTEMPTS regardless.  Both exits are needed:
        the first keeps this quiet in the normal case, the second stops a
        folder scrolled out of view from retrying forever.
        """
        if path not in self._awaiting_reread:
            return GLib.SOURCE_REMOVE           # Nautilus already came back

        for file_info in file_infos:
            try:
                file_info.invalidate_extension_info()
            except Exception as exc:
                _log("invalidate for %s failed: %r" % (path, exc))

        if attempt >= REFRESH_ATTEMPTS:
            self._awaiting_reread.discard(path)
            _log("gave up nudging %s after %d attempts" % (path, attempt))
            return GLib.SOURCE_REMOVE

        GLib.timeout_add(REFRESH_INTERVAL_MS,
                         self._nudge, path, file_infos, attempt + 1)
        return GLib.SOURCE_REMOVE


# --- self test --------------------------------------------------------------
#
# Running this file directly measures a folder the same way the extension
# does, and reports how long it took.  Use it to tell apart "measuring this
# folder is genuinely slow" from "measuring is fast but Nautilus never shows
# the result":
#
#     python3 total_size_column.py /path/to/big/folder
#
# If this prints a size in a couple of seconds but the column still says
# "Calculating...", the bug is in delivery, not in measurement.

if __name__ == "__main__":
    targets = sys.argv[1:] or [os.path.expanduser("~")]
    for target in targets:
        print("measuring %s ..." % target, flush=True)

        begin = time.monotonic()
        gio_error = None
        try:
            gio_bytes = _measure_with_gio(target, None)
        except GLib.Error as err:
            gio_bytes, gio_error = None, err.message
        gio_seconds = time.monotonic() - begin

        if gio_bytes is None:
            print("  GIO          : FAILED (%s)" % gio_error)
        else:
            print("  GIO          : %-12s in %6.2fs   (%d bytes)"
                  % (format_size(gio_bytes), gio_seconds, gio_bytes))

        begin = time.monotonic()
        walk_bytes = _measure_with_walk(target)
        walk_seconds = time.monotonic() - begin
        print("  os.walk      : %-12s in %6.2fs   (%d bytes)"
              % (format_size(walk_bytes), walk_seconds, walk_bytes))
        print("  column shows : %s" % format_size(gio_bytes or walk_bytes))
