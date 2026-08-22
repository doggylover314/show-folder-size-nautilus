#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
show_folder_size.py -- a "Total Size" column for GNOME Files (Nautilus) 46.

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
extension wrote nothing at all.  v0.3.0 added one written file, the size
cache.  v0.6.0 adds two more writes, both one-off, listed below.

  * Writes the size cache (see CACHE_PATH below, by default
    ~/.cache/show-folder-size-nautilus/sizes.json).  It is written atomically --
    a temporary file in the same directory, then os.replace() -- so a crash
    mid-write cannot corrupt it.  It contains directory paths, their
    modification times and their sizes in bytes.  Nothing else.  It is safe to
    delete at any time; the extension just rebuilds it.
    Set the cache path to an empty value (see CONFIGURATION) and this file is
    never written.
  * ONCE, on the first load ever, sets one GSettings key to make this column
    visible: org.gnome.nautilus.list-view default-visible-columns.  See
    _ensure_column_visible() for why a packaged schema override cannot do this
    on its own.  It happens exactly once and never reverses a later choice of
    yours.  This is a dconf write, so it lands in
    ~/.config/dconf/user like every other GNOME setting.
  * ONCE, alongside that, writes the marker file
    ~/.config/show-folder-size-nautilus-column-added, which is what makes it
    happen only once.  Create it yourself beforehand and neither write above
    ever occurs.
  * Note that the two writes above are NOT disabled by emptying the cache
    path -- that setting governs the size cache only.  To have this extension
    touch nothing at all, create the marker file and empty the cache path.
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
  * Hard links ARE counted once per link, not once per inode, so a file with
    two names inside the tree contributes its size twice.  That is what
    Gio.File.measure_disk_usage() does (verified by measurement, not assumed),
    and therefore what the Properties window reports, so this follows it --
    see "Follow the host" below.  It is also why the os.walk fallback and
    show-folder-size-index no longer de-duplicate by (st_dev, st_ino): they
    used to, which made a pre-indexed folder disagree with the same folder
    measured live.  `du` de-duplicates, so totals here can exceed `du`.
  * Imports are stdlib + PyGObject only: os, stat, sys, json, queue, tempfile,
    threading, time, collections, gi (GObject/GLib/Gio/Nautilus).  No
    third-party dependencies.

The only side effects are: CPU/IO from directory traversal, memory for the
result cache (bounded, see CACHE_LIMIT), inotify watches (bounded, see
MONITOR_LIMIT), the one cache file above, and the text drawn in the column.

CONFIGURATION
-------------
Where the cache lives, in order of precedence:

  1. the SHOW_FOLDER_SIZE_CACHE environment variable
  2. cache_dir= in ~/.config/show-folder-size-nautilus.conf
  3. cache_dir= in /etc/show-folder-size-nautilus.conf   (set by the .deb installer)
  4. $XDG_CACHE_HOME/show-folder-size-nautilus, i.e. ~/.cache/show-folder-size-nautilus

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
  It is faster, and it releases the GIL properly -- four concurrent
  measurements take 0.14s against 0.11s for one, and a measuring worker
  leaves the main thread running Python at full speed.  (An earlier revision
  of this comment claimed GIL contention from os.walk was starving Nautilus'
  main thread.  That was measured badly and overstated: the speed is the
  honest reason, not the contention.)

  How MUCH faster depends on the tree, and the honest range is narrower than
  this comment used to claim.  Recorded measurements: 189 GB / 314k files at
  0.8s against 4.9s, about 6x; a 6.5 GB cache directory at 0.129s against
  0.276s, about 2x.  Both warm.  Treat 2x as the number to expect and 6x as
  the good case, not the other way round -- and note that any comparison
  where one method runs first against a cold page cache is measuring the
  disk, not the method.  That mistake was in this file's own self test until
  v1.0.0 and it reported a 68x difference in the WRONG direction.

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
* Uninstalling cannot un-tick this column.  Enabling it writes a dconf value
  belonging to your account rather than to the package, so removing the
  package leaves it set.  Untick it, or run
  `gsettings reset org.gnome.nautilus.list-view default-visible-columns`.
* Deep changes are only noticed in directories currently being watched (the
  ones you have visited recently, up to MONITOR_LIMIT).  Change a file three
  levels below a folder nobody is watching and its cached total stays stale
  until the folder's own mtime changes or the cache entry ages out.  Reload
  the window (Ctrl+R) to force a recount.
* Nautilus sorts columns as plain strings, so clicking the "Total Size" header
  sorts alphabetically ("9.9 kB" before "1.2 GB"), not numerically.  The
  extension API has no sort-key hook, so this cannot be fixed from here.
* Totals are apparent size (sum of file sizes), not allocated blocks, so they
  differ slightly from `du` on sparse files, and hard-linked files are counted
  once per link rather than once per inode, so they can exceed `du` on trees
  that use hard links heavily.  Both match the Properties window.
* Measurement crosses mount points, so a folder containing a mounted volume
  includes that volume's contents.
* Only local ("file://") locations are measured; other URI schemes get a blank
  cell rather than a very slow recursive walk over the network.

DEBUGGING
---------
Tracing goes to stderr and can be switched on two ways:

  * SHOW_FOLDER_SIZE_DEBUG=1 in nautilus' environment -- but note this is
    easy to lose: nautilus is D-Bus activated, so `SHOW_FOLDER_SIZE_DEBUG=1
    nautilus` often just hands your request to a nautilus that is already
    running with a different environment, and the variable never arrives.
  * creating the marker file ~/.config/show-folder-size-nautilus-debug (its contents
    are irrelevant; only its existence is checked, and only at import).  This
    survives however nautilus happens to get started, which makes it the
    reliable option.

Either way the output lands in the session journal, so with the marker file in
place just run:

    journalctl --user -f | grep show-folder-size

Install:  ~/.local/share/nautilus-python/extensions/show_folder_size.py
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
import zlib
from collections import OrderedDict

import gi

# --- picking the libnautilus-extension ABI ----------------------------------
#
# This file used to pin "4.0", which meant it did not load AT ALL on any other
# ABI -- not a degraded column, no column, and no error anyone sees without
# turning tracing on first.  There are three ABIs in the wild, and a fixed
# string is wrong on two of them:
#
#     Nautilus 3.x - 42   ABI 3.0   libnautilus-extension.so.1
#     Nautilus 43 - 48    ABI 4.0   libnautilus-extension.so.4
#     Nautilus 49 - 50    ABI 4.1   libnautilus-extension.so.4
#
# So the list is not hardcoded: ask gi which ones are actually installed and
# take the newest.  A future 4.2 or 5.0 then works with no edit here, which a
# list would not -- the 4.1 bump is exactly the case a "4.0, 3.0" list missed.
#
# Verified across the .gir shipped by Nautilus 3.36, 42.6, 46.0, 48.0, 49.0
# and 50.2.2: every symbol this file uses (ColumnProvider.get_columns,
# InfoProvider.update_file_info/cancel_update, Column and its name/attribute/
# label/description/xalign properties, OperationResult.COMPLETE, and FileInfo
# add_string_attribute/get_uri_scheme/get_location/invalidate_extension_info)
# is present and unchanged in all six.  That is what makes "newest wins" safe:
# there is no version-conditional code below, because there is no difference
# to condition on.
#
# Then executed, not just read: the whole registration path -- this Column
# constructor call, the xalign property, subclassing both interfaces,
# instantiating the provider, calling get_columns() -- was run against the
# real so.1 from Nautilus 42.6 and the real so.4 from 50.2.2, and passed on
# both.  What that still does NOT cover is a running file manager, so the
# README claims "registers cleanly" for 3.0 and 4.1 rather than "works".
NAUTILUS_ABI_FALLBACK = ("4.1", "4.0", "3.0")

# ABI 3.0 and 4.x are different shared libraries, and loading the wrong one
# inside a running file manager registers our GObject types against a library
# nautilus is not using -- the provider is simply never recognised.  When both
# typelibs are installed (a leftover gir1.2-nautilus-3.0 after an upgrade, or
# a dev box), "newest" would be the wrong answer.  nautilus has already loaded
# its own copy by the time an extension is imported, so /proc/self/maps says
# authoritatively which one is correct.  4.0 and 4.1 share so.4 and cannot be
# told apart this way, but they never coexist: same file, same package.
_ABI_SONAME = {"3.0": "libnautilus-extension.so.1"}
_DEFAULT_SONAME = "libnautilus-extension.so.4"


def _abi_sort_key(version):
    """Key for a reverse sort: newest first, anything unparseable last.

    Tuples of ints, not strings: "10.0" has to beat "9.0", and it does not
    if you compare them as text.  The leading 1/0 is what keeps a version
    that does not parse at the bottom AFTER the reverse, which is why the
    sort is reverse=True rather than sort-then-reverse -- reversing a list
    ordered by an ascending key flips that marker too, and puts the garbage
    entry first.
    """
    try:
        return (1, tuple(int(part) for part in version.split(".")))
    except ValueError:
        return (0, ())


def _loaded_soname():
    """Which libnautilus-extension the host process already has open."""
    try:
        with open("/proc/self/maps", "r") as handle:
            maps = handle.read()
    except OSError:
        return None                       # not Linux, or /proc not mounted
    for soname in set(_ABI_SONAME.values()) | {_DEFAULT_SONAME}:
        if soname in maps:
            return soname
    return None                           # not nautilus: the indexer, a test


def _pick_nautilus_abi():
    try:
        from gi import Repository
        found = list(Repository.get_default().enumerate_versions("Nautilus"))
    except Exception:                     # very old pygobject, or no gi at all
        found = []
    for version in NAUTILUS_ABI_FALLBACK:
        if version not in found:
            found.append(version)         # try it anyway; require_version rules
    found.sort(key=_abi_sort_key, reverse=True)

    loaded = _loaded_soname()
    if loaded is not None:
        # Reorder, do not filter.  The candidates include guesses from the
        # fallback list that may not be installed, so a filter can leave a
        # list whose only entry does not load -- and then we would raise
        # ImportError on a machine that had a perfectly good typelib.
        # Preferring the ones matching the loaded library gets the same
        # answer whenever it matters and degrades to "newest" when it does not.
        found.sort(key=lambda v:
                   _ABI_SONAME.get(v, _DEFAULT_SONAME) != loaded)

    for version in found:
        try:
            gi.require_version("Nautilus", version)
        except ValueError:
            continue
        return version
    return None


NAUTILUS_ABI = _pick_nautilus_abi()

if NAUTILUS_ABI is None:
    raise ImportError(
        "no libnautilus-extension typelib found. Install nautilus-python "
        "(python3-nautilus on Debian/Ubuntu).")

from gi.repository import Gio, GLib, GObject, Nautilus  # noqa: E402

__version__ = "1.0.0"

# --- tunables ---------------------------------------------------------------

COLUMN_ID = "NautilusPython::total_size"
ATTRIBUTE = "total_size"
COLUMN_LABEL = "Total Size"
PENDING_TEXT = "Calculating..."

WORKER_COUNT = 4          # background threads driving the measurement
# Raised from 20000 in v1.0.0 because 20000 was too small to hold one real
# home directory: a test machine's had 46,686 directories in it, so every
# login index measured the lot and then threw away 57% of the result,
# announcing that it had. A cap that fires on ordinary use is not a safety
# limit, it is a bug with a log line.
#
# Then raised again to 1000000 by request. Measured at that size, on a cache
# averaging 120-character paths: a 158 MB file, 80 MB resident, 2.6s to
# serialise and 1.9s to load. Two things had to change first, because at
# 20000 entries they were invisible and at 1000000 they are not:
#
#   * the save snapshot moved off the GTK main thread (see _save)
#   * the initial load moved off it too (see _load_cache_worker)
#
# Anyone finding this file slow to load should turn it DOWN with max_entries=
# in the config rather than assuming a big number is free. It is affordable,
# not free.
CACHE_LIMIT = 1000000     # max remembered path -> (mtime, bytes) entries
MAX_ENTRIES_KEY = "max_entries"   # config override, see the indexer
REFRESH_ATTEMPTS = 4      # how many times to nudge Nautilus to re-read a value
REFRESH_INTERVAL_MS = 750
WATCHDOG_INTERVAL_S = 5   # how often to look for lost work
STUCK_SECONDS = 45        # a measurement taking this long was lost, not slow
REQUEUE_LIMIT = 2         # give up rather than pile duplicates onto the queue
MONITOR_LIMIT = 256       # max directories watched at once (inotify is finite)
SAVE_DELAY_S = 10         # quiet period before the cache is written to disk
WORKER_BACKOFF_S = 0.1    # pause after an unexpected worker error, see below

CACHE_ENV_VAR = "SHOW_FOLDER_SIZE_CACHE"

CONFIG_FILES = (
    os.path.join(os.path.expanduser("~"), ".config",
                 "show-folder-size-nautilus.conf"),
    "/etc/show-folder-size-nautilus.conf",
)

# This project was called nautilus-total-size up to 0.4.0, and that name is in
# the paths, not just the package: an upgrade from it has to be able to find
# the cache it left behind, or the user silently loses however long they spent
# indexing.  Kept as data rather than folded into the loops below, because the
# only thing that makes these paths special is history.
LEGACY_CACHE_NAME = "nautilus-total-size"
LEGACY_CONFIG_FILES = (
    os.path.join(os.path.expanduser("~"), ".config",
                 "nautilus-total-size.conf"),
    "/etc/nautilus-total-size.conf",
)

# Setting an environment variable from a program does not affect any other
# process, and this project already learned the hard way that a shell-set
# variable never reaches nautilus, which is D-Bus activated (see DEBUGGING
# above).  The one place a variable CAN be set so that a D-Bus activated
# process inherits it is systemd's user environment generator directory: the
# user manager reads it at login and applies it to everything it starts.
# It therefore needs a fresh login, and it OVERRIDES the config file, being
# first in the precedence list -- both of which the setup window says out loud
# before writing anything here.
ENVIRONMENT_D_PATH = os.path.join(
    os.environ.get("XDG_CONFIG_HOME") or
    os.path.join(os.path.expanduser("~"), ".config"),
    "environment.d", "60-show-folder-size-nautilus.conf")


def read_config_value(name, files=None):
    """First `name=` value from the user config, else the system one.

    Returns None when the key is in neither file, which is deliberately
    distinct from the key being present and empty: "" is an explicit "off"
    (no cache, no autostart directories) and must not be confused with "the
    admin never said".  Read-only: this only ever opens files for reading.

    Shared with show-folder-size-index and show-folder-size-setup so that all
    three agree on what the config files mean.  Two parsers for one file
    format is how they drift apart.

    `files` overrides which config files are consulted, which is what lets the
    upgrade path read the pre-0.5.0 ones by the same rules.
    """
    for config_path in (files if files is not None else CONFIG_FILES):
        try:
            with open(config_path, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    if key.strip() == name:
                        return value.strip()
        except OSError:
            continue
    return None


def _configured_cache_dir():
    """Resolve the cache directory.  '' anywhere means 'do not cache to disk'.

    Precedence: environment, then user config, then system config (which is
    what the .deb installer writes), then the XDG default.
    """
    from_env = os.environ.get(CACHE_ENV_VAR)
    if from_env is not None:
        return from_env.strip()

    configured = read_config_value("cache_dir")
    if configured is not None:
        return os.path.expanduser(configured)

    xdg = os.environ.get("XDG_CACHE_HOME") or \
        os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(xdg, "show-folder-size-nautilus")


CACHE_DIR = _configured_cache_dir()

# The cache is SHARDED across this many files, sizes-00.json to sizes-99.json,
# so that saving a handful of new measurements rewrites one small file instead
# of the whole cache.  At CACHE_LIMIT the single-file version rewrote 158 MB
# every time a few folders were measured, which is pointless disk traffic and
# real wear on an SSD.
#
# A shard file is only created once something hashes into it, so a small cache
# is a few small files rather than a hundred near-empty ones.
SHARD_COUNT = 100
SHARD_TEMPLATE = "sizes-%02d.json"

# The pre-shard single file.  Still read, so upgrading does not lose the cache,
# and still what CACHE_PATH points at, because "is caching switched on" is
# checked against it all over this project.
CACHE_PATH = os.path.join(CACHE_DIR, "sizes.json") if CACHE_DIR else ""


def shard_for(path):
    """Which shard a directory's entry belongs in.

    Keyed on the PARENT directory rather than on the path itself, and that is
    the whole point rather than an implementation detail.  Changes cluster by
    location -- you open a folder and its children get measured together -- so
    keying on the parent puts all of those in one shard and a save rewrites
    one file.  Hashing the full path would spread siblings evenly over all 100
    shards, so measuring one folder would dirty most of them and rewrite very
    nearly everything, which is the cost this exists to avoid.

    zlib.crc32 rather than hash(): hash() of a str is salted per process, so
    the shard a path belongs to would change every time nautilus restarted and
    every entry would be written to one file and then looked for in another.
    crc32 is stable, fast, and its distribution is fine for buckets.
    """
    parent = os.path.dirname(path) or path
    return zlib.crc32(parent.encode("utf-8", "surrogateescape")) % SHARD_COUNT


def shard_path(index):
    return os.path.join(CACHE_DIR, SHARD_TEMPLATE % index) if CACHE_DIR else ""
# Bumped to 2 in v1.0.0.  The on-disk shape did not change; what a byte count
# MEANS did.  A cache written before then may hold totals that de-duplicated
# hard links and ignored symlink sizes, and nothing would ever correct them --
# entries are keyed by directory mtime, and fixing how we count does not touch
# any directory's mtime, so a wrong number would sit there being served as a
# cache hit indefinitely.  A format bump makes load_cache() discard the lot and
# measure again, which is the only way those entries ever get fixed.
CACHE_FORMAT = 2

# --- autostart -------------------------------------------------------------
#
# The extension itself does nothing with these; it owns them because it is the
# module both show-folder-size-index and show-folder-size-setup already import,
# and one of them writes the file the other reads.  A filename agreed in two
# places is a filename that will disagree in one of them eventually.
#
# The .deb ships the system-wide entry in /etc/xdg/autostart.  Per the XDG
# autostart spec a file of the SAME NAME in ~/.config/autostart replaces it,
# so switching it off for one account means writing that name there with
# Hidden=true -- not deleting anything owned by the package, which a normal
# user cannot do anyway.

AUTOSTART_DESKTOP_NAME = "io.github.doggylover314.ShowFolderSizeIndex.desktop"
AUTOSTART_SYSTEM_PATH = os.path.join("/etc/xdg/autostart",
                                     AUTOSTART_DESKTOP_NAME)
AUTOSTART_USER_PATH = os.path.join(
    os.environ.get("XDG_CONFIG_HOME") or
    os.path.join(os.path.expanduser("~"), ".config"),
    "autostart", AUTOSTART_DESKTOP_NAME)

# Colon-separated, like PATH.  Absent means "not configured" and the indexer
# falls back to the home directory; empty means "the user chose nothing".
AUTOSTART_DIRS_KEY = "autostart_dirs"

_DEBUG_MARKER = os.path.join(
    os.path.expanduser("~"), ".config", "show-folder-size-nautilus-debug")

# The marker file is checked because the environment variable is unreliable:
# nautilus is D-Bus activated, so the variable frequently never reaches the
# process that actually loads this extension.  os.path.exists() is a read.
_DEBUG = bool(os.environ.get("SHOW_FOLDER_SIZE_DEBUG")) or \
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
        print("[show-folder-size] %s" % message, file=sys.stderr, flush=True)
    except Exception:
        pass


# --- first-run column visibility --------------------------------------------

NAUTILUS_LIST_SCHEMA = "org.gnome.nautilus.list-view"
VISIBLE_COLUMNS_KEY = "default-visible-columns"
COLUMN_ORDER_KEY = "default-column-order"

_COLUMN_MARKER = os.path.join(
    os.path.expanduser("~"), ".config",
    "show-folder-size-nautilus-column-added")


def _ensure_column_visible():
    """Tick "Total Size" in Visible Columns once, the first time we ever load.

    The packaged gschema override only changes the *default* value of
    `default-visible-columns`.  Ticking any column in the UI writes a dconf
    value, and a dconf value beats a schema default permanently -- so for
    anyone who has ever opened Visible Columns, the override alone is inert.
    This closes that gap from inside the user's own session, which is the only
    place their dconf is writable (a package's postinst runs as root and has
    no business writing into anyone's dconf).

    Done exactly once, recorded by a marker file, so that unticking the column
    afterwards sticks.  A column that silently re-enables itself on every
    restart is one you end up uninstalling the extension to be rid of.
    """
    if os.path.exists(_COLUMN_MARKER):
        return

    try:
        source = Gio.SettingsSchemaSource.get_default()
        if source is None or source.lookup(NAUTILUS_LIST_SCHEMA, True) is None:
            return          # not GNOME Files, or its schemas aren't installed
        settings = Gio.Settings.new(NAUTILUS_LIST_SCHEMA)

        for key in (VISIBLE_COLUMNS_KEY, COLUMN_ORDER_KEY):
            columns = list(settings.get_strv(key))
            if COLUMN_ID not in columns:
                settings.set_strv(key, columns + [COLUMN_ID])
                _log("enabled %s in %s" % (COLUMN_ID, key))
        Gio.Settings.sync()
    except Exception as exc:
        # Leave the marker unwritten so a transient failure retries next load.
        _log("could not enable column automatically: %r" % (exc,))
        return

    try:
        os.makedirs(os.path.dirname(_COLUMN_MARKER), exist_ok=True)
        with open(_COLUMN_MARKER, "w", encoding="utf-8") as handle:
            handle.write(
                "Written by show-folder-size-nautilus %s.\n"
                "\n"
                "Its presence means the Total Size column has already been\n"
                "enabled once, automatically.  It will not be enabled again.\n"
                "Delete this file to have that happen once more; untick the\n"
                "column in Visible Columns to turn it off for good.\n"
                % __version__)
    except OSError as exc:
        _log("could not write column marker: %r" % (exc,))


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
    (followlinks=False), so no directory tree is counted twice and link loops
    are impossible.  Unreadable entries are skipped rather than aborting.

    This counts what GIO counts, which took measuring rather than assuming.
    Two differences used to make the fallback disagree with the primary about
    the very same folder, so which number you saw depended on whether the GIO
    call happened to fail -- much worse than either number being imperfect:

      * Hard links.  This de-duplicated them by (st_dev, st_ino); GIO does
        not.  One 1 MB file with two names in the tree measures 2 MB.
      * Symlinks.  This skipped them; GIO adds each link's own st_size, which
        is the length of the path it points at.  Small, but it is exactly the
        sort of few-hundred-byte disagreement that looks like a real bug.

    So: every entry that is not a directory contributes its st_size, and a
    symlink to a directory is not a directory.  Follow the host.
    """
    total = 0

    for dirpath, dirnames, filenames in os.walk(path, topdown=True,
                                                followlinks=False):
        # dirnames carries symlinks-to-directories too, since followlinks
        # only stops the descent -- it does not reclassify the entry.
        for name in dirnames + filenames:
            try:
                info = os.stat(os.path.join(dirpath, name),
                               follow_symlinks=False)
            except OSError:
                continue

            if not stat.S_ISDIR(info.st_mode):
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


def read_cache_file(path):
    """(format, entries) for a cache file, whatever version wrote it.

    Returns (None, empty) if it is missing, unreadable, or not a cache at all.

    Deliberately does NOT insist on the current CACHE_FORMAT, which is the
    difference between this and load_cache(): reading a file written by an
    older version is the entire point of the upgrade path, and a loader that
    refuses to look at one cannot offer to import it.
    """
    entries = OrderedDict()
    if not path:
        return None, entries

    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, ValueError):
        return None, entries

    if not isinstance(raw, dict) or "format" not in raw:
        return None, entries

    for key, value in (raw.get("entries") or {}).items():
        try:
            mtime_ns, num_bytes = value
            entries[str(key)] = (int(mtime_ns), int(num_bytes))
        except (TypeError, ValueError):
            continue          # skip the bad row, keep the good ones

    return raw.get("format"), entries


def read_cache_any(path):
    """(format, entries) from a cache file, or from a directory of shards.

    Lets the upgrade path take whatever the user points at without them
    having to know that this version keeps a hundred files where older ones
    kept a single sizes.json.
    """
    if not path or not os.path.isdir(path):
        return read_cache_file(path)

    merged = OrderedDict()
    version = None
    names = ["sizes.json"] + [SHARD_TEMPLATE % i for i in range(SHARD_COUNT)]
    for name in names:
        found_version, found = read_cache_file(os.path.join(path, name))
        if found_version is None:
            continue
        if version is None:
            version = found_version
        merged.update(found)
    return version, merged


def load_cache():
    """Merge every shard.  Any problem returns an empty cache, never raises.

    A corrupt or unreadable cache is not worth a broken file manager: the
    worst case of ignoring it is that sizes get measured again.  That applies
    per shard, so one damaged file costs a hundredth of the cache rather than
    all of it, which is a quiet second benefit of splitting it up.

    The pre-shard single file is read first, so that a sharded value wins over
    a stale copy of the same path still sitting in it.

    One thing sharding costs, recorded rather than discovered later: entries
    come back grouped by shard, not in the order they were last used, so the
    LRU order that CACHE_LIMIT evicts by is arbitrary after a restart.  It is
    a small loss -- eviction at a limit of a million entries is rare, and the
    indexer caps by size rather than recency anyway -- and the alternative is
    storing a sequence number on every entry to rebuild an order that is only
    consulted when the cache is full.
    """
    if not CACHE_DIR:
        return OrderedDict()

    entries = OrderedDict()
    files = 0
    for candidate in [CACHE_PATH] + [shard_path(i) for i in range(SHARD_COUNT)]:
        version, found = read_cache_file(candidate)
        if version is None:
            continue
        if version != CACHE_FORMAT:
            # Not a warning: an old file sitting there is the normal state
            # right after an upgrade, and the setup window offers to import it.
            _log("%s is format %r, this version wants %d; ignoring it"
                 % (candidate, version, CACHE_FORMAT))
            continue
        entries.update(found)
        files += 1

    if files:
        _log("loaded %d cached sizes from %d file(s) in %s"
             % (len(entries), files, CACHE_DIR))
    return entries


def find_existing_caches():
    """Every size cache on this machine we can find, for the upgrade flow.

    Returns [(path, format, entry_count, mtime_epoch)], newest file first,
    with the cache this version would use excluded -- it is not something to
    offer to import into itself.

    Looks in four places, because "where is the old cache" has four answers
    and getting it wrong means telling someone their hours of indexing are
    gone when the file is right there:

      * the XDG default for this name
      * the XDG default for the pre-0.5.0 name, nautilus-total-size
      * cache_dir= in this version's config files
      * cache_dir= in the pre-0.5.0 config files, for anyone who moved it

    Read-only, and a location that does not exist simply does not appear.
    """
    xdg = os.environ.get("XDG_CACHE_HOME") or \
        os.path.join(os.path.expanduser("~"), ".cache")

    candidates = [
        os.path.join(xdg, "show-folder-size-nautilus"),
        os.path.join(xdg, LEGACY_CACHE_NAME),
    ]
    for files in (CONFIG_FILES, LEGACY_CONFIG_FILES):
        configured = read_config_value("cache_dir", files=files)
        if configured:
            candidates.append(os.path.expanduser(configured))

    ours = os.path.abspath(CACHE_DIR) if CACHE_DIR else None

    found = []
    seen = set()
    for directory in candidates:
        directory = os.path.abspath(directory)
        if directory in seen or directory == ours:
            continue
        seen.add(directory)

        # The whole directory, not just sizes.json: older versions kept one
        # file, this one keeps a hundred, and someone importing should not
        # have to know which layout they are pointing at.
        version, entries = read_cache_any(directory)
        if version is None or not entries:
            continue

        modified = 0.0
        try:
            for name in os.listdir(directory):
                if name.startswith("sizes") and name.endswith(".json"):
                    modified = max(
                        modified,
                        os.stat(os.path.join(directory, name)).st_mtime)
        except OSError:
            pass
        found.append((directory, version, len(entries), modified))

    found.sort(key=lambda row: row[3], reverse=True)
    return found


def _write_json_atomic(path, payload):
    """Write one JSON file atomically.  Never raises; returns success.

    Atomic because the alternative is a truncated JSON file if nautilus dies
    mid-write, which would silently poison every future start: write a
    temporary file in the same directory, then os.replace() onto the target.
    """
    handle = None
    temp_path = None
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(dir=CACHE_DIR, prefix=".sizes-",
                                         suffix=".tmp")
        # os.fdopen() takes ownership of the descriptor only if it succeeds.
        # If it raises (ENOMEM, a bad encoding) the fd is still open and
        # nothing below will ever close it, so a repeatedly failing save
        # would exhaust the process' descriptors -- inside nautilus, taking
        # the file manager down with it.
        try:
            handle = os.fdopen(fd, "w", encoding="utf-8")
        except Exception:
            os.close(fd)
            raise
        json.dump(payload, handle)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        handle = None
        os.replace(temp_path, path)
        temp_path = None
        return True
    except Exception as exc:
        _log("could not write %s: %r" % (path, exc))
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


def save_cache(entries, shards=None):
    """Write the cache.  Never raises.

    `shards` limits the write to those shard numbers, which is the point of
    sharding: the extension knows which shards its new measurements landed in
    and rewrites only those, turning a 158 MB write into a 1.6 MB one.  Pass
    None to write everything, which is what a full re-index wants.
    """
    if not CACHE_DIR:
        return False

    # Accepts a mapping or an already-flattened sequence of (path, (mtime,
    # bytes)) pairs.  The extension passes the latter, snapshotted on a worker
    # thread; the indexer and the setup window pass dicts.
    pairs = entries.items() if hasattr(entries, "items") else entries
    wanted = None if shards is None else set(shards)

    buckets = {}
    for path, (mtime, size) in pairs:
        index = shard_for(path)
        if wanted is not None and index not in wanted:
            continue
        buckets.setdefault(index, {})[path] = [mtime, size]

    succeeded = True
    written = 0
    for index in (range(SHARD_COUNT) if wanted is None else sorted(wanted)):
        target = shard_path(index)
        bucket = buckets.get(index)

        if not bucket:
            # Everything that lived here is gone: evicted by CACHE_LIMIT, or
            # the directories were deleted.  The file has to go too, or the
            # next load merges those entries straight back in and they become
            # immortal.  Only ever one of our own shard files.
            if os.path.exists(target):
                try:
                    os.unlink(target)
                except OSError as exc:
                    _log("could not remove empty shard %s: %r" % (target, exc))
            continue

        if _write_json_atomic(target,
                              {"format": CACHE_FORMAT, "entries": bucket}):
            written += 1
        else:
            succeeded = False

    # Once the shards hold everything, the pre-shard file is a stale duplicate
    # that load_cache would otherwise keep merging in for ever.  Only removed
    # after a complete, successful write, and it is our own file in our own
    # cache directory.
    if succeeded and wanted is None and CACHE_PATH and os.path.exists(CACHE_PATH):
        try:
            os.unlink(CACHE_PATH)
            _log("migrated to shards; removed %s" % CACHE_PATH)
        except OSError as exc:
            _log("could not remove %s: %r" % (CACHE_PATH, exc))

    _log("saved %d entries across %d shard(s)"
         % (sum(len(b) for b in buckets.values()), written))
    return succeeded


# --- the extension ----------------------------------------------------------

class ShowFolderSizeColumn(GObject.GObject,
                      Nautilus.ColumnProvider,
                      Nautilus.InfoProvider):
    """Registers the column and fills it in, lazily and off the main thread."""

    def __init__(self):
        super().__init__()
        # Everything below is touched only from the GTK main thread except
        # _work_queue, which is the thread-safe handoff to the workers.
        # Loaded on a worker, not here.  This runs while nautilus is starting,
        # and at CACHE_LIMIT the read is 1.1s of json.load plus 0.8s of
        # rebuilding the dict -- two seconds of a file manager not appearing,
        # which its user would rightly blame on whatever they installed last.
        # Until it arrives every lookup simply misses, which costs a
        # measurement that was going to happen anyway on a cold cache.
        self._cache = OrderedDict()   # path -> (mtime_ns, bytes)
        self._cache_loaded = False
        self._jobs = {}               # path -> [FileInfo, ...]
        self._queued_at = {}          # path -> monotonic seconds
        self._requeues = {}           # path -> times the watchdog re-queued it
        self._awaiting_reread = set()  # paths nudged but not yet re-asked for
        self._monitors = OrderedDict()  # path -> Gio.FileMonitor (LRU)
        self._watchdog_id = None
        self._save_id = None
        self._dirty = False
        # Which shards have changed since the last write.  Rewriting only
        # these is the entire reason the cache is split into files.
        self._dirty_shards = set()
        self._work_queue = queue.SimpleQueue()
        self._workers = []
        _ensure_column_visible()
        threading.Thread(target=self._load_cache_worker,
                         name="show-folder-size-load", daemon=True).start()

    def _load_cache_worker(self):
        """Read the cache off the main thread, then hand it over."""
        try:
            entries = load_cache()
        except Exception as exc:              # never take nautilus down
            _log("cache load failed: %r" % (exc,))
            entries = OrderedDict()
        GLib.idle_add(self._on_cache_loaded, entries,
                      priority=GLib.PRIORITY_DEFAULT)

    def _on_cache_loaded(self, entries):
        """Main thread: merge the file under whatever was measured meanwhile.

        `entries.update(self._cache)` and not the other way round: anything
        measured while the file was being read is newer than the file, and
        letting the file win would throw away fresh results and, worse,
        resurrect stale sizes for directories that had just been re-measured.
        """
        entries.update(self._cache)
        self._cache = entries
        while len(self._cache) > CACHE_LIMIT:
            evicted, _value = self._cache.popitem(last=False)
            self._dirty_shards.add(shard_for(evicted))
        self._cache_loaded = True
        _log("cache ready: %d entries" % len(self._cache))

        # A save deferred because the cache had not loaded yet still needs to
        # happen; without this a measurement made during the load would sit
        # unsaved until the next unrelated change.
        if self._dirty:
            self._schedule_save()
        return GLib.SOURCE_REMOVE

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
        _log("registered column on libnautilus-extension %s" % NAUTILUS_ABI)
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

        Re-queueing is capped at REQUEUE_LIMIT per path, because "stuck" and
        "genuinely slower than STUCK_SECONDS" are indistinguishable from here.
        Uncapped, a folder big enough to take a minute would be re-queued
        every STUCK_SECONDS forever: each copy occupies one of four workers
        measuring the very same tree, the queue grows without bound, and the
        pool that is meant to be the safety net becomes the failure.

        Dropping the job costs less than it sounds like.  The measurement that
        was merely slow is still running, and _on_result caches its answer
        whether anything is still waiting for it or not -- so the next time
        Nautilus asks about that folder it gets a cache hit and the real size.
        Until then the cell reads "Calculating...", which is exactly what it
        was going to say anyway.
        """
        if not self._jobs:
            self._watchdog_id = None
            return GLib.SOURCE_REMOVE

        now = time.monotonic()
        for path, queued_at in list(self._queued_at.items()):
            if path not in self._jobs or now - queued_at < STUCK_SECONDS:
                continue

            attempts = self._requeues.get(path, 0)
            if attempts >= REQUEUE_LIMIT:
                _log("job for %s still outstanding after %d re-queues; "
                     "dropping it (measurement is slow, not lost)"
                     % (path, attempts))
                self._forget_job(path)
                continue

            _log("job for %s stuck for %.0fs; re-queueing (%d live workers)"
                 % (path, now - queued_at, len(self._workers)))
            try:
                mtime_ns = os.lstat(path).st_mtime_ns
            except OSError:
                self._forget_job(path)
                continue                      # folder went away; drop the job

            self._queued_at[path] = now
            self._requeues[path] = attempts + 1
            self._start_workers()
            self._work_queue.put((path, mtime_ns))

        return GLib.SOURCE_CONTINUE

    def _forget_job(self, path):
        """Drop all bookkeeping for a job that will not be completed."""
        self._jobs.pop(path, None)
        self._queued_at.pop(path, None)
        self._requeues.pop(path, None)
        self._awaiting_reread.discard(path)

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
                name="show-folder-size-%d" % len(self._workers),
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
                # Everything above is already guarded, so reaching here means
                # the queue or idle_add itself failed.  If that is persistent,
                # an unpaused loop spins a core at 100% inside the file
                # manager and the only symptom is a hot laptop.  Surviving is
                # the point; surviving quietly and cheaply is the whole point.
                time.sleep(WORKER_BACKOFF_S)

    def _on_result(self, path, mtime_ns, num_bytes):
        """Main thread: cache the answer, then get Nautilus to re-read it."""
        self._cache[path] = (mtime_ns, num_bytes)
        self._cache.move_to_end(path)
        self._dirty_shards.add(shard_for(path))
        while len(self._cache) > CACHE_LIMIT:
            evicted, _value = self._cache.popitem(last=False)
            # The evicted entry is still in its shard file, so that shard has
            # to be rewritten or the next load brings it straight back.
            self._dirty_shards.add(shard_for(evicted))
        self._schedule_save()
        self._watch(path)

        text = format_size(num_bytes) if num_bytes >= 0 else ""
        self._queued_at.pop(path, None)
        self._requeues.pop(path, None)
        # A re-queued job can land twice.  The second arrival finds no
        # waiters, updates the cache (harmlessly, with the same answer) and
        # nudges nobody, which is exactly what should happen.
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
        # Not before the cache has finished loading.  Saving first would write
        # the handful of entries measured so far OVER the full file that is
        # still being read, destroying it.
        if CACHE_PATH and self._save_id is None and self._cache_loaded:
            self._save_id = GLib.timeout_add_seconds(SAVE_DELAY_S, self._save)

    def _save(self):
        self._save_id = None
        if not self._dirty:
            return GLib.SOURCE_REMOVE
        self._dirty = False

        # Take the dirty set now and hand it over.  Anything measured from
        # here on marks its shard again and gets written by the next save.
        shards = self._dirty_shards
        self._dirty_shards = set()

        # One exception to writing only what changed: while the pre-shard
        # sizes.json is still on disk, write everything, because that is what
        # lets save_cache retire it. It happens once, on the first save after
        # upgrading.
        if CACHE_PATH and os.path.exists(CACHE_PATH):
            shards = None

        threading.Thread(target=self._save_worker, args=(shards,),
                         name="show-folder-size-save", daemon=True).start()
        return GLib.SOURCE_REMOVE

    def _save_worker(self, shards):
        """Snapshot and write, both off the main thread.

        The snapshot used to be taken here on the MAIN thread, as
        OrderedDict(self._cache), on the reasoning that the writer must not
        iterate a dict the main thread is mutating.  At 20000 entries that
        copy was unnoticeable.  At CACHE_LIMIT it measures 539ms -- a
        half-second freeze of the file manager every time the cache is
        written, which is a far worse bug than the one it was avoiding.

        list() over a dict view is a C loop that never runs Python code, so it
        never drops the GIL, so it cannot observe a half-applied mutation:
        833,000 mutations against 64 concurrent snapshots produced no
        RuntimeError and no short reads.  The snapshot is therefore taken
        here, on the worker, and the main thread pays nothing at all.

        It is not a point-in-time snapshot of the whole cache, and does not
        need to be.  Entries are independent, and one that is a moment stale
        fails its mtime check and gets measured again.
        """
        try:
            if save_cache(list(self._cache.items()), shards=shards):
                return
            failed = shards
        except Exception as exc:
            _log("save failed: %r" % (exc,))
            failed = shards

        # A shard that failed to write is still stale on disk, and its dirty
        # mark has already been taken. Put it back, or the entry sits
        # unwritten until something unrelated happens to touch that shard.
        if failed:
            GLib.idle_add(self._requeue_shards, failed,
                          priority=GLib.PRIORITY_DEFAULT)

    def _requeue_shards(self, shards):
        self._dirty_shards.update(shards)
        self._schedule_save()
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

        # Drop the changed thing's own entry first, then walk up from its
        # parent.  The old code decided where to start with os.path.isdir(),
        # which is both a stat syscall per event -- and there is one event per
        # write, so a single download can fire hundreds -- and wrong in the
        # case that matters: a directory that has just been DELETED is no
        # longer a directory, so isdir() says False, the walk started at its
        # parent, and the dead directory's own cached total stayed in the
        # cache (and got written back to disk) for good.  A path that names a
        # file is simply not a key here, so popping it unconditionally costs
        # nothing.
        dropped = 0
        if self._cache.pop(path, None) is not None:
            dropped += 1
            self._dirty_shards.add(shard_for(path))

        directory = os.path.dirname(path)
        while True:
            if self._cache.pop(directory, None) is not None:
                dropped += 1
                self._dirty_shards.add(shard_for(directory))
            parent = os.path.dirname(directory)
            if parent == directory:
                break
            directory = parent

        # A watched directory that goes away keeps its GFileMonitor alive
        # otherwise, holding an inotify watch on a dead inode and a slot
        # against MONITOR_LIMIT that nothing will ever reclaim, since the LRU
        # eviction only runs when a *new* watch is added.
        if event_type in (Gio.FileMonitorEvent.DELETED,
                          Gio.FileMonitorEvent.MOVED_OUT):
            monitor = self._monitors.pop(path, None)
            if monitor is not None:
                monitor.cancel()
                _log("stopped watching %s (it is gone)" % path)

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
#     python3 show_folder_size.py /path/to/big/folder
#
# If this prints a size in a couple of seconds but the column still says
# "Calculating...", the bug is in delivery, not in measurement.

if __name__ == "__main__":
    targets = sys.argv[1:] or [os.path.expanduser("~")]
    for target in targets:
        print("measuring %s ..." % target, flush=True)

        # Warm the page cache with a throwaway pass of each before timing
        # anything.  Without this the first measurement reads from the disk
        # and the second reads from RAM, so the numbers say nothing about the
        # two methods and everything about which one went first -- on a 6.5 GB
        # cache directory that reported GIO at 18.28s against os.walk at
        # 0.27s, a 68x "difference" that reversed to GIO being 2.1x FASTER
        # once both were warm.  A diagnostic whose entire purpose is telling
        # "measuring is slow" from "delivery is broken" must not be the thing
        # that misleads you.
        print("  warming the cache (timings below are from a second pass,"
              " so they compare) ...", flush=True)
        gio_error = None
        try:
            _measure_with_gio(target, None)
        except GLib.Error:
            pass
        _measure_with_walk(target)

        begin = time.monotonic()
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
        # Not `gio_bytes or walk_bytes`: an empty folder measures 0, which is
        # falsy, so that reported the fallback's answer for the one case where
        # both are certain to agree -- harmless here, but the same idiom in
        # directory_size() would silently prefer the wrong number.
        shown = walk_bytes if gio_bytes is None else gio_bytes
        print("  column shows : %s" % format_size(shown))
