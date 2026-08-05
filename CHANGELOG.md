# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning is [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.1] - 2026-08-05

### Fixed
- **Folders stuck on `Calculating...` forever.** The async `InfoProvider`
  protocol (`IN_PROGRESS` + `info_provider_update_complete_invoke()`) never
  delivered its completion here: a 100 GB folder measured in well under a
  second and the cell still never updated. Worse, an `IN_PROGRESS` that never
  completes is unrecoverable — Nautilus waits on a promise nothing will keep,
  with no timeout.

  Every update now returns `COMPLETE` immediately, with the real size if
  known and the placeholder otherwise, and the finished measurement calls
  `invalidate_extension_info()` to make Nautilus re-read it. Returning
  `COMPLETE` cannot wedge anything; the worst case is a stale cell that the
  next refresh fixes.

### Added
- The re-read nudge is retried up to 4 times at 750 ms. It stops the instant
  Nautilus asks again, and gives up regardless after the cap — a single
  invalidate proved unreliable in 0.1.x, but a folder that silently never
  updates is worse than one redundant refresh.
- Debug tracing can be enabled with the marker file
  `~/.config/nautilus-total-size-debug`. `NAUTILUS_TOTAL_SIZE_DEBUG=1` is
  unreliable because nautilus is D-Bus activated, so the variable often never
  reaches the process that loads the extension. Output goes to the journal:
  `journalctl --user -f | grep total-size`.

### Removed
- Operation-handle tracking, `cancel_update()` bookkeeping and the
  measurement `Cancellable`. With nothing ever reporting `IN_PROGRESS` there
  is no operation for Nautilus to cancel, so all of it was dead weight.

## [0.2.2] - 2026-08-05

### Fixed
- **The worker pool could die silently, after which nothing was ever
  measured again.** Reported as folders inside a directory queueing and never
  producing a result — the log showed `queued` lines with no matching
  `measured` lines. Three separate hardening changes:
  - `_log()` can no longer raise. It is called from worker threads and writes
    to a stderr pipe that feeds the journal; a burst of logging can fill that
    pipe, and a non-blocking write then raises `BlockingIOError`, killing the
    worker permanently. Losing a debug line is fine; losing a worker is not.
    (This is also why the failure was invisible: the dying thread's traceback
    doesn't contain "total-size", so `journalctl | grep total-size` hid it.)
  - The worker loop body is now fully guarded, so nothing can escape and end
    a thread.
  - The pool heals itself: `_start_workers()` runs on every enqueue, prunes
    dead threads and tops back up to `WORKER_COUNT`.

### Added
- A watchdog re-queues any job outstanding longer than `STUCK_SECONDS` (45s,
  orders of magnitude clear of the ~1s a real measurement takes) and logs it.
  It stops when the queue drains and leaves no state behind.
- Debug logging now records when a worker picks up a job (`start <path>`), so
  "queued but never measured" is distinguishable from "measuring slowly".

### Changed
- Corrected an overstated claim in the v0.2.0 notes. GIL contention was *not*
  starving Nautilus' main thread: measured properly, `measure_disk_usage`
  releases the GIL (four concurrent measurements take 0.14s against 0.11s for
  one, and the main thread runs Python at full speed throughout). Switching to
  GIO was justified by speed alone.

## [0.3.0] - 2026-08-05

### Added
- **Persistent on-disk cache.** Sizes now survive a Nautilus restart. Written
  atomically (temp file + `os.replace`) so a crash mid-write cannot corrupt
  it; a corrupt or unreadable cache is ignored rather than raised. Location is
  configurable — env var, user config, system config, then the XDG default
  `~/.cache/nautilus-total-size/`. **Setting it empty disables writing
  entirely.**
- **Filesystem monitoring.** Visited directories are watched with
  `GFileMonitor`; a change drops the cached total for that directory *and
  every ancestor*, since a file written three levels down changes all of their
  totals. Linux has no recursive watch and one per subdirectory would exhaust
  the inotify limit, so watches are bounded (`MONITOR_LIMIT`, 256) and evicted
  LRU. Deep changes are therefore caught in recently-visited directories.
- **`.deb` now asks where to store the cache**, via debconf, defaulting to
  `~/.cache/nautilus-total-size`. debconf rather than a bare `read` because
  package installs are often non-interactive (unattended-upgrades, images, CI)
  and a stdin prompt would hang them. The answer is written to
  `/etc/nautilus-total-size.conf` as the system default; users override it in
  `~/.config/nautilus-total-size.conf`. Removed on purge, not on remove.

### Changed
- **The no-writes guarantee no longer holds** — this is the first version that
  writes anything. The audit notes say so explicitly at the top rather than
  quietly dropping the old claim. Pin v0.2.2, or set an empty cache dir, if
  you need the write path never reached.
- The cache stores byte counts rather than formatted strings, so a cache
  written under one locale doesn't force stale text on another.
- Cache is keyed by path with the mtime stored alongside, rather than by a
  `(path, mtime)` tuple — invalidating a whole ancestor chain needs
  path-keyed lookup.
- Raised `CACHE_LIMIT` from 4096 to 20000 now that entries persist.

## [0.4.0] - 2026-08-05

### Added
- **`total-size-index`**, a standalone command that pre-computes folder sizes
  for whole drives and writes them into the cache the extension reads, so
  browsing is instant from the first look instead of measuring on demand.
  Run bare it lists mounted local filesystems and asks which to index;
  `--all`, explicit paths, `--list` and `--dry-run` are also available.
  - Walks **bottom-up in one pass**: each directory's total is its own files
    plus its children's already-known totals, so every directory in a tree
    gets a size for the cost of reading the tree once. Measuring each
    directory independently would be quadratic.
  - Does not cross mount points by default, so indexing `/` will not wander
    onto an external drive (`--cross-mounts` allows it).
  - Ctrl-C saves what was already measured rather than discarding it.
  - Caps the cache at `--max-entries` (default 20000), keeping the largest
    directories; small ones are near-instant to measure anyway.
  - Imports the extension's own cache format and atomic write rather than
    reimplementing them — two implementations of one file format is how they
    drift apart.
  - Verified to agree with `Gio.measure_disk_usage()` at every level of the
    tree, not just at the roots.
- The `.deb` installs it to `/usr/bin/total-size-index`.

## [Unreleased]

### Planned
- Verified support for GNOME 47 and newer.
- C rewrite of the per-file callback is **not** planned on current evidence:
  measured at 3.4us per row, 68% of it the `os.lstat` a C module would also
  pay. Real saving is ~1.1us/row — 55ms on a 50,000-row folder. It would cost
  the single-auditable-file property and architecture-independent packaging.

## [0.2.0] - 2026-08-05

Fixes reported against 0.1.x: wrong units next to the built-in Size column,
duplicated file sizes, and measurements that never finished.

### Changed
- **Sizes now use `GLib.format_size()`**, the same formatter Nautilus uses.
  This means base-10 units (1 GiB reads as `1.1 GB`) and correct localisation.
  0.1.x hardcoded base-1024 with `KB` labels, so every value disagreed with
  the built-in Size column.
- **Measurement uses `Gio.File.measure_disk_usage()`**, the call behind
  Properties, instead of a Python walk. Measured 6.2x faster (189 GB /
  314k files: 0.8s vs 4.9s), and because it is a single C call it releases
  the GIL — Python worker threads running `os.walk` were throttling the main
  thread that has to render their results. `os.walk` remains as a fallback.
- **Results post at `PRIORITY_DEFAULT` instead of `PRIORITY_DEFAULT_IDLE`.**
  A busy Nautilus main loop can starve idle-priority callbacks indefinitely;
  this is the likeliest reason folders sat on `Calculating...` with their
  measurement long since finished.
- **Regular files are left blank.** Nautilus' Size column already shows them,
  and a second copy alongside it only invited a mismatch.

### Added
- Measurements are cancellable: abandoning a folder aborts the work instead of
  tying up a worker (verified aborting a 189 GB measurement in 0.15s).
- Debug tracing now reports how long each measurement took.

### Fixed
- Folders stuck indefinitely on `Calculating...` (see the priority and GIL
  changes above).

### Known issues
- Nautilus' built-in Size column cannot be hidden from an extension; untick it
  manually if you want only this one.

## [0.1.0] - 2026-08-05

Initial release. Tested against GNOME Nautilus 46.4 with python3-nautilus 4.0
on Ubuntu (ext4).

### Added
- `Total Size` column for Nautilus list view showing recursive folder sizes.
- Background computation on a 4-thread worker pool; results returned to the
  GTK main thread via `GLib.idle_add()`.
- In-memory cache keyed by `(path, directory mtime)`, bounded to 4096 entries
  with LRU eviction.
- `Calculating...` placeholder while a walk is pending.
- Human-readable base-1024 formatting (B/KB/MB/GB/TB/PB).
- Symlinks never followed (no loops, no double-counting); hard links counted
  once via `(st_dev, st_ino)`.
- Debug tracing via `NAUTILUS_TOTAL_SIZE_DEBUG=1`.
- Read-only by construction: only `os.walk`, `os.stat`, `os.lstat` — no
  writes, no network, no subprocesses.
- Install guide, `install.sh` helper, MIT license.

### Known issues
- Many folders remain on `Calculating...` indefinitely; the
  `invalidate_extension_info()` refresh does not fire reliably. Ruled out:
  slow I/O and cache-key churn.
- Column sorts as text, not numerically — no sort-key hook exists in the
  extension API.
- Cached totals go stale on changes deeper than the folder's direct children.

[Unreleased]: https://github.com/doggylover314/nautilus-total-size/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/doggylover314/nautilus-total-size/releases/tag/v0.4.0
[0.3.0]: https://github.com/doggylover314/nautilus-total-size/releases/tag/v0.3.0
[0.2.2]: https://github.com/doggylover314/nautilus-total-size/releases/tag/v0.2.2
[0.2.1]: https://github.com/doggylover314/nautilus-total-size/releases/tag/v0.2.1
[0.2.0]: https://github.com/doggylover314/nautilus-total-size/releases/tag/v0.2.0
[0.1.0]: https://github.com/doggylover314/nautilus-total-size/releases/tag/v0.1.0
