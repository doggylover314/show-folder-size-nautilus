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
  * Imports are stdlib + PyGObject only: os, stat, sys, queue, threading,
    collections, gi (GObject/GLib/Nautilus).  No third-party dependencies.

The only side effects are: CPU/IO from directory traversal, memory for the
result cache (bounded, see CACHE_LIMIT), and the text drawn in the column.

HOW THE ASYNC UPDATE WORKS
--------------------------
Nautilus.InfoProvider has a proper asynchronous protocol for exactly this
situation -- a value that isn't ready yet:

  1. update_file_info_full() writes the "Calculating..." placeholder, stashes
     the (provider, handle, closure) triple it was handed, and returns
     OperationResult.IN_PROGRESS.
  2. A worker thread walks the tree.  It touches no GTK or Nautilus object.
  3. The worker hands the total back to the main thread with GLib.idle_add().
     On the main thread we write the real attribute and then call
     Nautilus.info_provider_update_complete_invoke(closure, provider, handle,
     COMPLETE), which tells Nautilus the value it was waiting on has landed.
  4. cancel_update() drops the handle if Nautilus loses interest first.  This
     matters: completing a handle Nautilus has already freed is a
     use-after-free, so a handle is only ever completed once and only while
     it is still registered in self._waiters.

v0.1.0 instead returned COMPLETE immediately and called
FileInfo.invalidate_extension_info() when the walk finished, hoping Nautilus
would re-ask and hit the cache.  That refresh did not fire reliably -- most
folders sat on "Calculating..." forever -- which is why this version uses the
real protocol.  The invalidate path survives only as a fallback for
nautilus-python builds that call the old one-argument update_file_info().

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

__version__ = "0.1.1"

# --- tunables ---------------------------------------------------------------

COLUMN_ID = "NautilusPython::total_size"
ATTRIBUTE = "total_size"
COLUMN_LABEL = "Total Size"
PENDING_TEXT = "Calculating..."

WORKER_COUNT = 4       # background threads doing os.walk
CACHE_LIMIT = 4096     # max remembered (path, mtime) -> text entries

_DEBUG = bool(os.environ.get("NAUTILUS_TOTAL_SIZE_DEBUG"))

# Present on libnautilus-extension 4.0; guarded so a build without it falls
# back to the invalidate-and-hope path rather than failing to load at all.
_HAS_ASYNC = hasattr(Nautilus, "info_provider_update_complete_invoke")


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

class _Waiter(object):
    """One outstanding request for a folder's size.

    `handle`/`closure`/`provider` are set for async requests and completed
    exactly once.  Legacy (non-async) requests carry only `file_info` and are
    refreshed with invalidate_extension_info() instead.
    """

    __slots__ = ("file_info", "provider", "handle", "closure", "is_async")

    def __init__(self, file_info, provider=None, handle=None, closure=None):
        self.file_info = file_info
        self.provider = provider
        self.handle = handle
        self.closure = closure
        self.is_async = handle is not None


class TotalSizeColumn(GObject.GObject,
                      Nautilus.ColumnProvider,
                      Nautilus.InfoProvider):
    """Registers the column and fills it in, lazily and off the main thread."""

    def __init__(self):
        super().__init__()
        # Everything below is touched only from the GTK main thread except
        # _work_queue, which is the thread-safe handoff to the workers.
        self._cache = OrderedDict()   # (path, mtime_ns) -> formatted string
        self._waiters = {}            # (path, mtime_ns) -> [_Waiter, ...]
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
        """Async entry point used by libnautilus-extension 4.0."""
        try:
            text, key = self._resolve(file_info)
        except Exception as exc:                      # never break the view
            _log("update failed: %r" % (exc,))
            file_info.add_string_attribute(ATTRIBUTE, "")
            return Nautilus.OperationResult.COMPLETE

        file_info.add_string_attribute(ATTRIBUTE, text)

        if key is None:                               # answer already known
            return Nautilus.OperationResult.COMPLETE

        if not _HAS_ASYNC:                            # very old binding
            self._add_waiter(key, _Waiter(file_info))
            return Nautilus.OperationResult.COMPLETE

        self._add_waiter(key, _Waiter(file_info, provider, handle, closure))
        return Nautilus.OperationResult.IN_PROGRESS

    def update_file_info(self, file_info):
        """Legacy entry point: no handle, so refresh via invalidation."""
        try:
            text, key = self._resolve(file_info)
        except Exception as exc:
            _log("update failed: %r" % (exc,))
            file_info.add_string_attribute(ATTRIBUTE, "")
            return

        file_info.add_string_attribute(ATTRIBUTE, text)
        if key is not None:
            self._add_waiter(key, _Waiter(file_info))

    def cancel_update(self, provider, handle):
        """Nautilus no longer wants this value; drop the handle unused.

        After this returns, `handle` may be freed by Nautilus, so it must
        never be passed to update_complete_invoke().  Dropping the waiter here
        is what makes that guarantee.
        """
        for key, waiters in list(self._waiters.items()):
            remaining = [w for w in waiters if not self._same_handle(w, handle)]
            if len(remaining) == len(waiters):
                continue
            if remaining:
                self._waiters[key] = remaining
            else:
                # Nobody is waiting any more.  The walk itself is left to
                # finish -- its result still populates the cache, which makes
                # the next visit to this folder instant.
                del self._waiters[key]
            _log("cancelled a waiter for %s" % (key[0],))
            return

    @staticmethod
    def _same_handle(waiter, handle):
        if not waiter.is_async:
            return False
        try:
            return waiter.handle == handle
        except Exception:
            return waiter.handle is handle

    # -- value resolution ----------------------------------------------------

    def _resolve(self, file_info):
        """Return (text, key).

        `key` is None when the text is final; otherwise it identifies the
        pending job the caller should attach a waiter to.
        """
        if file_info.get_uri_scheme() != "file":
            return "", None

        location = file_info.get_location()
        path = location.get_path() if location is not None else None
        if not path:
            return "", None

        try:
            info = os.lstat(path)
        except OSError:
            return "", None

        mode = info.st_mode
        if stat.S_ISLNK(mode):
            return "", None                            # don't follow links
        if stat.S_ISREG(mode):
            return format_size(info.st_size), None     # plain file: own size
        if not stat.S_ISDIR(mode):
            return "", None                            # device, fifo, socket

        key = (path, info.st_mtime_ns)

        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached, None

        return PENDING_TEXT, key

    # -- background work -----------------------------------------------------

    def _add_waiter(self, key, waiter):
        """Attach `waiter` to the job for `key`, starting it if needed."""
        existing = self._waiters.get(key)
        if existing is not None:
            existing.append(waiter)          # already being measured
            return

        self._waiters[key] = [waiter]
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
        """Main thread: cache the answer and release everyone waiting on it."""
        self._cache[key] = text
        self._cache.move_to_end(key)
        while len(self._cache) > CACHE_LIMIT:
            self._cache.popitem(last=False)

        for waiter in self._waiters.pop(key, ()):
            try:
                waiter.file_info.add_string_attribute(ATTRIBUTE, text)
                if waiter.is_async:
                    Nautilus.info_provider_update_complete_invoke(
                        waiter.closure,
                        waiter.provider,
                        waiter.handle,
                        Nautilus.OperationResult.COMPLETE,
                    )
                else:
                    waiter.file_info.invalidate_extension_info()
            except Exception as exc:
                _log("completing %s failed: %r" % (key[0], exc))

        _log("%s -> %s" % (key[0], text))
        return GLib.SOURCE_REMOVE
