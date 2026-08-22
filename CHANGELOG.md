# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning is [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-08-22

First stable release. Sizes now keep themselves up to date, and the three
different ways this project measures a folder finally agree on the answer.

### Added
- **Indexing at login.** The `.deb` installs
  `/etc/xdg/autostart/io.github.doggylover314.ShowFolderSizeIndex.desktop`,
  which runs `show-folder-size-index --autostart`: a full index of the
  configured directories the first time, and afterwards only a re-measure of
  what changed. It waits 30 seconds, runs at `nice 10`, indexes, and exits.
  No daemon, no timer, nothing resident.

  The default is **your home directory**, not every local drive. The entry is
  system-wide, so a default of "every disk" would mean every account on a
  shared machine walking every disk at its first login. Set `autostart_dirs=`
  (colon-separated, like `PATH`) to widen it.
- **An off switch that a normal user can actually reach.** The setup window's
  *Index at every login* toggle writes `~/.config/autostart/` +
  the same filename with `Hidden=true`. Per the XDG autostart spec a user file
  replaces the system one of that name, which is the only way to override a
  file in `/etc` without root. Switching it back on **deletes** the override
  rather than writing an enabled copy, so a later package update to the entry
  still reaches that account.
- **`--refresh`** on `show-folder-size-index`: re-measure only directories
  whose mtime moved. On a barely-changed drive this skips nearly all of the
  work, because one `lstat` per file is what the work actually is. It is
  opt-in for manual runs and automatic from the second login onwards. The
  limitation is stated rather than buried: directory mtime does not move when
  an existing file is written to in place, so a file growing inside an
  untouched folder is invisible to a refresh. That is the same assumption the
  extension's cache key already makes.
- **A lock file** (`index.lock` in the cache directory, `flock`), so two
  indexers cannot walk the same drives and race to write the same cache.
  `flock` rather than a pid file because the kernel releases it however the
  process dies, so there is no stale lock to detect and mis-handle.
- `build-deb.sh` now refuses to build when `__version__` and the newest
  `<release>` in the AppStream metainfo disagree. They had already drifted:
  the metainfo said 0.6.0 regardless, so GNOME Software showed the wrong
  version and nothing caught it.

- **The cache is sharded across up to 100 files.** Measuring a few folders
  used to rewrite the entire cache: at a 1,000,000-entry limit that is 158 MB
  of disk traffic, and real SSD wear, to record a handful of numbers. Now only
  the shards that changed are rewritten, measured at 1.1% of the bytes for a
  one-entry change. A shard is created only once something belongs in it, so a
  small cache stays a few small files.

  Shards are keyed on a directory's **parent**, not on its own path. That is
  the part that makes it work: changes cluster by location, because you open a
  folder and its children get measured together, so keying on the parent puts
  all of them in one file. Hashing the full path would spread siblings evenly
  over all 100 shards and rewrite nearly everything anyway. The hash is
  `zlib.crc32` rather than `hash()`, which is salted per process and would put
  an entry in a different shard on every restart.

  One cost, recorded rather than left to be discovered: entries load grouped by
  shard, so the LRU order that eviction uses is arbitrary after a restart.
  Eviction at a million entries is rare and the indexer caps by size anyway.
- **A signed apt repository**, built by `build-apt-repo.sh`. This is the
  update mechanism, and it is deliberately not an updater inside the project:
  one of those would have needed network access from our own code and a
  privileged helper to install with, costing two of the properties the audit
  notes are built on, to reimplement badly what `apt` already does well.
  Adding the repository means `unattended-upgrades` and GNOME Software handle
  this package with no further setup. The repository is signed; `[trusted=yes]`
  is not offered, because teaching people to disable signature checking lasts
  longer than the inconvenience it saves.
- **Importing a cache from an older version**, in the setup window. It
  auto-detects caches on the machine, including under the pre-0.5.0
  `~/.cache/nautilus-total-size/` path and anywhere an older config file
  pointed, or takes a path you type. Importing merges rather than replaces,
  and says plainly when the entries came from a version whose totals read low.
- **The cache location is written down** the first time the setup window
  runs, so nothing has to re-derive it from the precedence rules. It records
  only a location that was previously implicit; one set in `/etc` or the
  environment is left where it is rather than pinned into the user's file.
- **An optional `SHOW_FOLDER_SIZE_CACHE` export** to
  `~/.config/environment.d/`. This is the one place a variable can be set so
  that a D-Bus activated nautilus inherits it, which a shell cannot do. Off by
  default and it says so before writing, because it outranks the location set
  in the window.

### Fixed
- **Installing over the old package name left both installed.** The 0.5.0
  rename also renamed every file shipped, so dpkg saw two unrelated packages
  with no overlapping paths, installed both, and nautilus loaded two
  extensions and drew **two Total Size columns**. Added the
  `Conflicts`/`Replaces`/`Provides` triple on `nautilus-total-size`. Verified
  by resolving the install against a real apt index, not by reading policy.
- **The indexer walked filesystems it was told to skip.** Pruning a walk means
  editing `dirnames` in place, which is documented to do nothing when
  `topdown=False` — and bottom-up is the mode the whole single-pass design
  needs. So `--cross-mounts` being off filtered the *results* while the walk
  still read everything: indexing `/` meant reading every mounted external
  drive, plus `/proc` and `/sys`, in order to throw all of it away. Replaced
  `os.walk` with an explicit stack that prunes before it descends and still
  holds only one frame per level of depth.
- **Drives with non-ASCII names vanished from the list.** `/proc/self/mounts`
  escapes four characters in octal, and the old decoder was
  `field.encode().decode("unicode_escape")`, which round-trips through
  latin-1: `/media/you/Musiqué` came back as `/media/you/MusiquÃ©`,
  `os.path.isdir()` said no, and the drive was silently dropped. Now only
  those four escapes are decoded and every other character is left alone.
- **The three measurement paths disagreed about the same folder.** GIO counts
  hard-linked files once per link and counts each symlink's own size; the
  `os.walk` fallback and the indexer de-duplicated hard links by
  `(st_dev, st_ino)` and skipped symlinks entirely. Which number you saw
  depended on whether the GIO call happened to fail. All three now do what
  GIO does, which is what the Properties window shows. Verified by
  measurement rather than by reading the documentation: totals can now exceed
  `du`, and that is the intended answer.
- **The watchdog could pile duplicate work onto the queue forever.** A job
  outstanding longer than `STUCK_SECONDS` was re-queued unconditionally, but
  "lost" and "genuinely slower than 45 seconds" look identical from there, so
  a big enough folder was re-queued every 45 seconds indefinitely: each copy
  occupying one of four workers measuring the same tree while the queue grew
  without bound. Re-queueing is now capped, after which the job is dropped.
- **Saving one setting in the setup window deleted the other.** The config
  file was rewritten from scratch with only `cache_dir` in it, so saving a
  cache location would have wiped `autostart_dirs` and vice versa. It is now
  read-modify-write.
- **A hand-edited `/etc/show-folder-size-nautilus.conf` reverted on upgrade.**
  `postinst` regenerated the file from the debconf database, which still held
  the answer from the original install. The `config` script now seeds debconf
  from the live file first, and `postinst` carries over any keys it does not
  generate.
- **Deleted directories leaked.** A watched directory that was removed kept
  its cached total (which was then written back to disk) and kept its
  `GFileMonitor` alive on a dead inode, holding an inotify watch and a slot
  against `MONITOR_LIMIT` that only ran its eviction when a *new* watch was
  added. The change handler also called `os.path.isdir()` on every event, once
  per write, purely to decide where to start.
- A file descriptor leaked from `save_cache()` whenever `os.fdopen()` itself
  failed; repeated failures would have exhausted nautilus' descriptors.
- A worker that hit an unexpected error spun without pause; it now backs off.
- The self-test printed the fallback's answer for an empty folder, because
  `gio_bytes or walk_bytes` treats a legitimate 0 as absent.

- **The self test's timings were not comparable, and misled its own authors.**
  It measured GIO and then `os.walk`, so the first read from disk and the
  second read from RAM: on a 6.5 GB directory that reported GIO at 18.28s
  against `os.walk` at 0.27s. Warming both first reverses it to 0.13s against
  0.28s, GIO being about 2x faster. A diagnostic that exists to separate
  "measuring is slow" from "delivery is broken" must not be the thing that
  misleads you. The header's "~6x faster" claim, which rested on the same
  method, is now given as a range with both measurements and their conditions.
- **The cache limit was too small to hold one real home directory.** A test
  machine's had 46,686 directories against a cap of 20,000, so every login
  index measured all of them and then discarded 57% of the result, saying so
  each time. A cap that fires on ordinary use is a bug with a log line, not a
  safety limit. Raised to 100,000, sized by measuring that cache at 147 bytes
  per entry on disk and 122 in memory: about 15 MB and 12 MB at the very top
  end. It is also now settable as `max_entries=` in the config file, because
  the run that hits it is the login one, started from a `.desktop` file in
  `/etc` that users are told not to edit, so "raise `--max-entries`" was
  advice they had no way to take.

- **Closing the setup window mid-index threw the index away.** The indexing
  worker is a daemon thread and the save happens at the end of it, so closing
  the window quit the application, killed the thread where it stood, and
  several minutes of disk reading vanished with nothing said. Closing now
  stops it the way the Stop button does, keeping everything already measured,
  and waits for the write.
- **Nothing in the setup window said you were finished.** Every button said
  Save or Index, so having done the setup there was no obvious end to it.
  Added a Done button.
- **Exporting the cache location to the environment ignored an unsaved one.**
  Typing a custom path and flipping the export switch without pressing Save
  wrote the new path into the environment and left the old one in the config,
  two files disagreeing with the environment silently winning. The switch now
  writes both, since setting a custom location during first setup is what it
  is for.

### Changed
- The setup window checks for Stop every 200 directories instead of every
  2000. A Stop button that takes a minute to respond reads as a hang.
- `README.md` no longer claims the extension writes exactly one file, or that
  hard links are counted once. Both stopped being true in earlier releases.
  Every write is now listed in a table with how to prevent each one. The
  stale "this will change in v0.3.0" note, still sitting inside the section
  describing v0.3.0 as already done, is gone.
- The `.deb` description no longer says "no writes".
- **The cache format version is bumped to 2, discarding existing caches once.**
  The file's shape is unchanged; what a byte count means is not. Entries are
  keyed by directory mtime, and correcting how sizes are counted does not
  touch any directory's mtime, so pre-1.0.0 totals would have been served as
  cache hits forever. They are measured again instead.

## [0.6.0] - 2026-08-05

Installing by double-clicking the `.deb` now produces a working, configured
setup without touching a terminal.

### Added
- **The Total Size column is enabled automatically.** Two mechanisms, because
  one is not enough:
  - A gschema override (`90_show-folder-size-nautilus.gschema.override`) adds
    the column to the *default* value of
    `org.gnome.nautilus.list-view default-visible-columns`. `postinst` runs
    `glib-compile-schemas`, without which an override file has no effect at
    all.
  - The extension also enables it once, on first load, from inside the user's
    own session. This is required: ticking any column writes a dconf value,
    and **a dconf value beats a schema default permanently**, so the override
    alone is inert for anyone who has ever opened Visible Columns. A package's
    `postinst` runs as root and has no business writing into anyone's dconf,
    so the extension is the only correct place for it.

  Done exactly once, recorded by `~/.config/show-folder-size-nautilus-column-added`,
  so unticking the column afterwards sticks. A column that re-enables itself
  every restart is one you uninstall the extension to be rid of.
- **`show-folder-size-setup`**, a GTK window for the configuration that has to
  happen as *you*, in *your* session: cache location, column on/off, and
  pre-indexing drives with a progress bar and a working Stop button. Installed
  with a desktop entry ("Folder Size Setup"), so it is reachable from the
  applications menu rather than only the command line.

  This exists because **debconf cannot serve a GUI install.** GNOME Software
  drives dpkg through PackageKit with a non-interactive debconf frontend:
  every question is silently answered with its default and the user is shown
  nothing. Worse, `postinst` runs as root while the cache lives under each
  user's home, so "index my drives during install" could only ever have
  filled root's cache with sizes nobody reads.
- **AppStream metainfo and an icon**, so double-clicking the `.deb` renders a
  proper application entry in GNOME Software instead of a bare package name
  with no icon or description.

### Fixed
- **The cache-location question never appeared.** `debian/config` asked it at
  `db_input medium`, but the default debconf priority *is* high, so a medium
  question is skipped on any stock system. It has been asked at `high` since
  the day it was written and never fired once. Terminal installs now show it.
- `postrm` recompiles the schema cache on `remove`, not just `purge`. dpkg
  deletes the override file, but the compiled cache keeps serving its values
  until rebuilt, which would have left Total Size in everyone's default column
  list after the package was gone.

### Changed
- Depends on `gir1.2-gtk-4.0` and `gir1.2-adw-1` for the setup window.
- The setup window is built from `Adw.ActionRow` plus plain GTK widgets rather
  than `Adw.SwitchRow`/`EntryRow`/`ToolbarView`. Those arrived in libadwaita
  1.4, and this package declares `nautilus (>= 43)`, which on GNOME 43 means
  libadwaita 1.2.

### Not changed
- **A C rewrite is still not planned, now with better evidence.** The hot path
  has been `Gio.measure_disk_usage()` — already C — since v0.2.0. Measured on
  one 16,508-file tree: GIO 0.05s against 0.10s for the Python `os.walk`
  fallback, and 53% of that fallback is `os.lstat`, which a C module pays
  identically. Rewriting it in C means rewriting the *fallback* to roughly
  match the C path already being called.

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
  `~/.config/show-folder-size-nautilus-debug`. `SHOW_FOLDER_SIZE_DEBUG=1` is
  unreliable because nautilus is D-Bus activated, so the variable often never
  reaches the process that loads the extension. Output goes to the journal:
  `journalctl --user -f | grep show-folder-size`.

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
    doesn't contain "total-size", so `journalctl | grep show-folder-size` hid it.)
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
  `~/.cache/show-folder-size-nautilus/`. **Setting it empty disables writing
  entirely.**
- **Filesystem monitoring.** Visited directories are watched with
  `GFileMonitor`; a change drops the cached total for that directory *and
  every ancestor*, since a file written three levels down changes all of their
  totals. Linux has no recursive watch and one per subdirectory would exhaust
  the inotify limit, so watches are bounded (`MONITOR_LIMIT`, 256) and evicted
  LRU. Deep changes are therefore caught in recently-visited directories.
- **`.deb` now asks where to store the cache**, via debconf, defaulting to
  `~/.cache/show-folder-size-nautilus`. debconf rather than a bare `read` because
  package installs are often non-interactive (unattended-upgrades, images, CI)
  and a stdin prompt would hang them. The answer is written to
  `/etc/show-folder-size-nautilus.conf` as the system default; users override it in
  `~/.config/show-folder-size-nautilus.conf`. Removed on purge, not on remove.

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
- **`show-folder-size-index`**, a standalone command that pre-computes folder sizes
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
- The `.deb` installs it to `/usr/bin/show-folder-size-index`.

## [0.5.0] - 2026-08-05

Project renamed from `nautilus-total-size` to **`show-folder-size-nautilus`**.
Nothing about the behaviour changed; every name did.

### Changed
- Repository is now `github.com/doggylover314/show-folder-size-nautilus`.
  GitHub redirects the old URL, but update your remotes and bookmarks.
- Package: `nautilus-total-size` -> `show-folder-size-nautilus`
- Extension file: `total_size_column.py` -> `show_folder_size.py`
- Command: `total-size-index` -> `show-folder-size-index`
- Class: `TotalSizeColumn` -> `ShowFolderSizeColumn`
- Cache: `~/.cache/nautilus-total-size/` -> `~/.cache/show-folder-size-nautilus/`
- Config: `~/.config/nautilus-total-size.conf` and
  `/etc/nautilus-total-size.conf` -> `~/.config/show-folder-size-nautilus.conf`
  and `/etc/show-folder-size-nautilus.conf`
- Debug marker: `~/.config/nautilus-total-size-debug` ->
  `~/.config/show-folder-size-nautilus-debug`
- Environment: `NAUTILUS_TOTAL_SIZE_CACHE` -> `SHOW_FOLDER_SIZE_CACHE`,
  `NAUTILUS_TOTAL_SIZE_DEBUG` -> `SHOW_FOLDER_SIZE_DEBUG`
- Log prefix: `[total-size]` -> `[show-folder-size]`
- debconf namespace: `nautilus-total-size/cache-dir` ->
  `show-folder-size-nautilus/cache-dir`

### Not changed
- **The column is still labelled "Total Size"**, and its identifier is still
  `NautilusPython::total_size`. That is what the column *means* in the file
  manager, which is a different thing from what the project is called, and
  changing the identifier would silently un-tick the column for anyone who
  had already enabled it.

### Upgrading from 0.4.x
The cache and config live at new paths, so the old ones are ignored rather
than migrated. Remove them if you want them gone:

```bash
rm -rf ~/.cache/nautilus-total-size ~/.config/nautilus-total-size.conf
sudo apt purge nautilus-total-size      # if you installed the old package
```

## [Unreleased]

### Planned
- Verified support for GNOME 47 and newer.
- Sections of this file are out of chronological order (0.2.1 leads, and this
  block sits between 0.5.0 and 0.2.0). Cosmetic, but worth a tidy pass.

### Not planned
- **A C rewrite.** See the v0.6.0 notes for the measurements: the hot path is
  already C, and rewriting the Python fallback would buy back less than the
  C path it falls back from already delivers. It would also cost the
  single-auditable-file property and architecture-independent packaging.

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
- Debug tracing via `SHOW_FOLDER_SIZE_DEBUG=1`.
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

[Unreleased]: https://github.com/doggylover314/show-folder-size-nautilus/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/doggylover314/show-folder-size-nautilus/releases/tag/v1.0.0
[0.6.0]: https://github.com/doggylover314/show-folder-size-nautilus/releases/tag/v0.6.0
[0.5.0]: https://github.com/doggylover314/show-folder-size-nautilus/releases/tag/v0.5.0
[0.4.0]: https://github.com/doggylover314/show-folder-size-nautilus/releases/tag/v0.4.0
[0.3.0]: https://github.com/doggylover314/show-folder-size-nautilus/releases/tag/v0.3.0
[0.2.2]: https://github.com/doggylover314/show-folder-size-nautilus/releases/tag/v0.2.2
[0.2.1]: https://github.com/doggylover314/show-folder-size-nautilus/releases/tag/v0.2.1
[0.2.0]: https://github.com/doggylover314/show-folder-size-nautilus/releases/tag/v0.2.0
[0.1.0]: https://github.com/doggylover314/show-folder-size-nautilus/releases/tag/v0.1.0
