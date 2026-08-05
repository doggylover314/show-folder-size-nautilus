# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning is [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned
- Persistent on-disk cache surviving Nautilus restarts. **This will end the
  current no-writes guarantee**; audit notes will be updated to match.
- Filesystem monitoring via `GFileMonitor` so deep changes invalidate cached totals.
- Optional startup indexing of user-selected drives.
- Verified support for GNOME 47 and newer.

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

[Unreleased]: https://github.com/doggylover314/nautilus-total-size/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/doggylover314/nautilus-total-size/releases/tag/v0.2.0
[0.1.0]: https://github.com/doggylover314/nautilus-total-size/releases/tag/v0.1.0
