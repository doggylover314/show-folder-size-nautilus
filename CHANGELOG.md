# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning is [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned
- Fix folders stuck on `Calculating...` by moving to the async `InfoProvider`
  protocol (`OperationResult.IN_PROGRESS` + `info_provider_update_complete_invoke()`).
- Persistent on-disk cache surviving Nautilus restarts. **This will end the
  current no-writes guarantee**; audit notes will be updated to match.
- Filesystem monitoring via `GFileMonitor` so deep changes invalidate cached totals.
- Optional startup indexing of user-selected drives.
- Verified support for GNOME 47 and newer.

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

[Unreleased]: https://github.com/doggylover314/nautilus-total-size/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/doggylover314/nautilus-total-size/releases/tag/v0.1.0
