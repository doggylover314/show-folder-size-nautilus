#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
total_size_column.py -- a "Total Size" column for GNOME Files (Nautilus) 46.

WHAT IT DOES
------------
Nautilus' built-in "Size" column shows an item count for folders ("12 items").
This extension adds a second, optional column called "Total Size" that shows
the recursive on-disk size of a folder's contents (like `du -sh`), and the
plain size for regular files.

Sizes are computed on background worker threads and cached in memory, keyed by
(path, directory mtime), so scrolling a folder list never blocks the UI and
re-entering an unchanged folder is instant.  While a folder's size is being
computed the column shows "Calculating...".

SAFETY / AUDIT NOTES  (this is the whole story -- grep the file to confirm)
--------------------------------------------------------------------------
This extension is READ-ONLY with respect to your system:

  * Filesystem reads only.  The only filesystem calls used anywhere in this
    file are os.walk(), os.stat() and os.lstat().  There is no open(), no
    write(), no unlink/rename/mkdir/chmod, and nothing is created on disk --
    not even a cache file.  The cache lives in RAM and dies with nautilus.
  * No network.  There is no socket, urllib, requests, http, or DNS use.
  * No subprocesses.  There is no os.system, subprocess, popen, exec*, or
    fork.  Nothing external is invoked.
  * No symlink following.  os.walk(followlinks=False) means symlinked
    directories are never descended into, so there are no link loops and no
    directory tree is counted twice.  Symlinks to files are stat'ed with
    follow_symlinks=False and skipped, so link targets are not double-counted.
  * Imports are stdlib + PyGObject only: os, stat, queue, threading,
    collections, gi (GObject/GLib/Nautilus).  No third-party dependencies.

The only side effects are: CPU/IO from directory traversal, memory for the
result cache (bounded, see CACHE_LIMIT), and the text drawn in the column.

IMPLEMENTATION NOTES
--------------------
* Nautilus.InfoProvider has an async protocol (return OperationResult
  .IN_PROGRESS, then call info_provider_update_complete_invoke() with the
  handle you were given).  This extension deliberately does NOT use it: that
  protocol requires tracking opaque operation handles across threads and
  correctly honouring cancel_update(), and invoking a completion on a handle
  Nautilus has already freed can crash the file manager.  Instead every
  update_file_info() call returns immediately (COMPLETE) with either the
  cached size or "Calculating...", and when a background walk finishes we call
  FileInfo.invalidate_extension_info() on the main thread, which makes
  Nautilus re-ask us -- and that second ask hits the cache.  Same user-visible
  behaviour, no handle lifetime hazards.
* Results are handed back to the GTK main thread with GLib.idle_add(); the
  worker threads never touch a Nautilus object.
* Work is served by a small fixed thread pool rather than one thread per
  folder, so opening a directory containing hundreds of subfolders doesn't
  spawn hundreds of threads.  Requests are still fully concurrent with the UI.

KNOWN LIMITATIONS (by design, called out so they don't surprise you)
--------------------------------------------------------------------
* Cache invalidation keys on the folder's own mtime, which only changes when
  its *direct* children change.  A file modified three levels down will not
  invalidate the cached total until the top folder itself is touched.  Reload
  the window (Ctrl+R) after such a change, or restart nautilus, to force a
  recount.
* Nautilus sorts columns as plain strings, so clicking the "Total Size" header
  sorts alphabetically ("9.9 KB" before "1.2 GB"), not numerically.  The
  extension API has no sort-key hook, so this cannot be fixed from here.
* Sizes are the sum of file sizes (apparent size), not allocated blocks, so
  totals differ slightly from `du` on sparse or heavily fragmented files.
  Directory inodes themselves are not counted.  Hard links are counted once.
* os.walk crosses mount points, so a folder containing a mounted volume
  includes that volume's contents.
* Only local ("file://") locations are handled; network mounts and other URI
  schemes get a blank column rather than a very slow recursive walk.

Set NAUTILUS_TOTAL_SIZE_DEBUG=1 in nautilus' environment for stderr tracing.

Install:  ~/.local/share/nautilus-python/extensions/total_size_column.py
Requires: nautilus-python (python3-nautilus) for libnautilus-extension 4.0.
"""

import os
import queue
import stat
import sys
import threading
from collections import OrderedDict

import gi

gi.require_version("Nautilus", "4.0")
from gi.repository import GLib, GObject, Nautilus  # noqa: E402

# --- tunables ---------------------------------------------------------------

__version__ = "0.1.0"

COLUMN_ID = "NautilusPython::total_size"
ATTRIBUTE = "total_size"
COLUMN_LABEL = "Total Size"
PENDING_TEXT = "Calculating..."

WORKER_COUNT = 4       # background threads doing os.walk
CACHE_LIMIT = 4096     # max remembered (path, mtime) -> text entries

_DEBUG = bool(os.environ.get("NAUTILUS_TOTAL_SIZE_DEBUG"))


def _log(message):
    if _DEBUG:
        print("[total-size] %s" % message, file=sys.stderr, flush=True)


# --- pure helpers -----------------------------------------------------------

_UNITS = ("B", "KB", "MB", "GB", "TB", "PB")


def format_size(num_bytes):
    """Human-readable size, base 1024 (1536 -> '1.5 KB')."""
    if num_bytes < 1024:
        return "%d B" % num_bytes
    value = float(num_bytes)
    index = 0
    while value >= 1024.0 and index < len(_UNITS) - 1:
        value /= 1024.0
        index += 1
    return "%.1f %s" % (value, _UNITS[index])


def directory_size(path):
    """Sum the sizes of every regular file under `path`, recursively.

    Read-only: os.walk + os.stat(follow_symlinks=False) and nothing else.
    Symlinked directories are not descended into (followlinks=False) and
    symlinks to files are skipped, so nothing is counted twice and link loops
    are impossible.  Hard-linked files are counted once.  Unreadable entries
    are silently skipped rather than aborting the whole total.
    """
    total = 0
    seen_hardlinks = set()

    for dirpath, _dirnames, filenames in os.walk(path, topdown=True,
                                                 followlinks=False):
        for name in filenames:
            full_path = os.path.join(dirpath, name)
            try:
                info = os.stat(full_path, follow_symlinks=False)
            except OSError:
                continue

            mode = info.st_mode
            if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
                # Symlinks point at bytes counted elsewhere (or outside the
                # tree); sockets/fifos/devices have no meaningful size.
                continue

            if info.st_nlink > 1:
                identity = (info.st_dev, info.st_ino)
                if identity in seen_hardlinks:
                    continue
                seen_hardlinks.add(identity)

            total += info.st_size

    return total


# --- the extension ----------------------------------------------------------

class TotalSizeColumn(GObject.GObject,
                      Nautilus.ColumnProvider,
                      Nautilus.InfoProvider):
    """Registers the column and fills it in, lazily and off the main thread."""

    def __init__(self):
        super().__init__()
        # Everything below is touched only from the GTK main thread except
        # _work_queue, which is the thread-safe handoff to the workers.
        self._cache = OrderedDict()   # (path, mtime_ns) -> formatted string
        self._pending = {}            # (path, mtime_ns) -> [FileInfo, ...]
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
    #
    # Both spellings are implemented so the extension works regardless of
    # which one this nautilus-python build calls.  Neither ever returns
    # IN_PROGRESS -- see IMPLEMENTATION NOTES at the top of the file.

    def update_file_info(self, file_info):
        self._fill_in(file_info)

    def update_file_info_full(self, provider, handle, closure, file_info):
        self._fill_in(file_info)
        return Nautilus.OperationResult.COMPLETE

    def _fill_in(self, file_info):
        try:
            text = self._text_for(file_info)
        except Exception as exc:                      # never break the view
            _log("update failed: %r" % (exc,))
            text = ""
        file_info.add_string_attribute(ATTRIBUTE, text)

    def _text_for(self, file_info):
        if file_info.get_uri_scheme() != "file":
            return ""

        location = file_info.get_location()
        path = location.get_path() if location is not None else None
        if not path:
            return ""

        try:
            info = os.lstat(path)
        except OSError:
            return ""

        mode = info.st_mode
        if stat.S_ISLNK(mode):
            return ""                                  # don't follow links
        if stat.S_ISREG(mode):
            return format_size(info.st_size)           # plain file: own size
        if not stat.S_ISDIR(mode):
            return ""                                  # device, fifo, socket

        key = (path, info.st_mtime_ns)

        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached

        self._enqueue(key, file_info)
        return PENDING_TEXT

    # -- background work -----------------------------------------------------

    def _enqueue(self, key, file_info):
        """Queue a walk for `key`, or attach to one already in flight."""
        waiters = self._pending.get(key)
        if waiters is not None:
            # Same folder already being measured (e.g. a second view of it).
            if file_info not in waiters:
                waiters.append(file_info)
            return

        self._pending[key] = [file_info]
        self._start_workers()
        self._work_queue.put(key)
        _log("queued %s" % (key[0],))

    def _start_workers(self):
        if self._workers:
            return
        for index in range(WORKER_COUNT):
            thread = threading.Thread(
                target=self._worker_loop,
                name="total-size-%d" % index,
                daemon=True,
            )
            thread.start()
            self._workers.append(thread)

    def _worker_loop(self):
        """Worker thread: walk, then hand the result to the main thread.

        Touches no GTK/Nautilus object -- the only crossing point back is
        GLib.idle_add(), which is documented as thread-safe.
        """
        while True:
            key = self._work_queue.get()
            path = key[0]
            try:
                text = format_size(directory_size(path))
            except Exception as exc:
                _log("walk of %s failed: %r" % (path, exc))
                text = ""
            GLib.idle_add(self._on_result, key, text,
                          priority=GLib.PRIORITY_DEFAULT_IDLE)

    def _on_result(self, key, text):
        """Main thread: cache the answer and ask Nautilus to re-read it."""
        self._cache[key] = text
        self._cache.move_to_end(key)
        while len(self._cache) > CACHE_LIMIT:
            self._cache.popitem(last=False)

        for file_info in self._pending.pop(key, ()):
            # Makes Nautilus call update_file_info() again for this file; that
            # call hits the cache above and returns the real size immediately.
            file_info.invalidate_extension_info()

        _log("%s -> %s" % (key[0], text))
        return GLib.SOURCE_REMOVE
