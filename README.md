# nautilus-total-size

A **"Total Size"** column for GNOME Files (Nautilus) that shows the *recursive*
size of a folder's contents — like `du -sh` — instead of Nautilus' built-in
"12 items" count.

Sizes are computed on background threads and cached in memory, so browsing
never blocks. While a folder is being measured the column reads
`Calculating...`.

> **Status: early / v0.1.0.** This works, but there is a significant known bug
> where many folders stay stuck on `Calculating...`. See
> [Known issues](#known-issues) before installing. Fix in progress.

---

## Requirements

| | |
|---|---|
| Nautilus | 46 (libnautilus-extension **4.0**) |
| Package | `nautilus-python` — `python3-nautilus` on Debian/Ubuntu, `nautilus-python` on Fedora/Arch |
| Python | 3.8+, stdlib only |
| Dependencies | none beyond PyGObject, which nautilus-python already pulls in |

Newer GNOME releases (47+) are **not yet verified** — see
[GNOME version support](#gnome-version-support).

## Install

```bash
mkdir -p ~/.local/share/nautilus-python/extensions
curl -o ~/.local/share/nautilus-python/extensions/total_size_column.py \
  https://raw.githubusercontent.com/doggylover314/nautilus-total-size/main/total_size_column.py
nautilus -q   # closes open windows; next launch loads the extension
```

Then switch to **List View**, open the view-options menu → **Visible
Columns…** (or right-click the column header row) and tick **Total Size**.

Full instructions, distro package names and troubleshooting:
**[INSTALL.md](INSTALL.md)**.

## How it works

- `Nautilus.ColumnProvider` registers the column; `Nautilus.InfoProvider`
  fills in a value per file.
- Directory totals come from `os.walk()` + `os.stat(follow_symlinks=False)`,
  summing regular files only.
- Walks run on a small fixed thread pool (4 workers), never on the GTK main
  thread. Results cross back via `GLib.idle_add()`.
- Results are cached in memory keyed by `(path, directory mtime)`, so
  re-entering an unchanged folder is instant.

### Correctness details

- **Symlinks are never followed.** `os.walk(followlinks=False)` means
  symlinked directories aren't descended into, so there are no link loops and
  no tree is counted twice. Symlinks to files are skipped.
- **Hard links are counted once**, tracked by `(st_dev, st_ino)`.
- **Apparent size, not allocated blocks** — totals differ slightly from `du`
  on sparse files. Directory inodes are not counted.
- Unreadable files are skipped rather than aborting the whole total.

## Is it safe? (read-only guarantee)

As of **v0.1.0** this extension only ever *reads* the filesystem. The complete
list of filesystem calls in the entire file is `os.walk`, `os.stat` and
`os.lstat`. There is:

- **no** `open()`, write, delete, rename, mkdir or chmod — nothing is created
  on disk, not even a cache file (the cache is in RAM and dies with nautilus)
- **no** network use of any kind — no sockets, no HTTP, no DNS
- **no** subprocesses — no `subprocess`, `os.system`, `popen`, `exec*`, `fork`
- imports limited to stdlib (`os`, `stat`, `queue`, `threading`,
  `collections`, `sys`) plus PyGObject

It's a single ~300-line file with a header block stating the same thing, so
you can audit it at a glance before trusting it with your filesystem.

> **This will change in v0.2.0.** Persistent (on-disk) caching is planned,
> which means the extension *will* start writing one cache file under
> `~/.cache/`. The audit notes will be rewritten to say so honestly rather
> than quietly dropping the claim. If the strict no-writes property matters to
> you, pin v0.1.0.

## Known issues

- **Many folders stay on `Calculating...` indefinitely.** Some resolve, most
  don't. The extension returns immediately and calls
  `FileInfo.invalidate_extension_info()` when the background walk finishes, to
  make Nautilus re-ask; that refresh appears not to fire reliably. Confirmed
  *not* caused by slow I/O or cache-key churn. The fix under investigation is
  to switch to the proper async `InfoProvider` protocol
  (`OperationResult.IN_PROGRESS` + `info_provider_update_complete_invoke()` +
  `cancel_update()`).
- **Sorting is alphabetical, not numeric.** Clicking the header puts `9.9 KB`
  before `1.2 GB`. The extension API exposes no sort-key hook, so this can't be
  fixed from inside an extension.
- **Deep changes don't invalidate the cache.** The key uses the folder's own
  mtime, which only changes when its *direct* children change. Edit a file
  three levels down and the total stays stale until `Ctrl+R` or a restart.
  Filesystem monitoring is planned for v0.2.0.
- **`os.walk` crosses mount points**, so a folder containing a mounted volume
  includes that volume's contents.
- Only local `file://` paths are measured; other URI schemes get a blank cell
  instead of a very slow recursive walk over the network.

## GNOME version support

| GNOME | Nautilus | Extension API | Status |
|---|---|---|---|
| 46 | 46.x | 4.0 | **Tested** — developed against 46.4 |
| 47+ | 47.x+ | not yet confirmed | **Unverified** — untested, see below |

Support for newer GNOME releases is planned but not yet done. Nothing here has
been tested past Nautilus 46.4, and the required
`gi.require_version("Nautilus", "4.0")` may need to change if a later release
bumps the extension ABI. Reports from newer desktops are welcome — please
include your `nautilus --version` and any stderr output.

## Debugging

Run Nautilus from a terminal with tracing on:

```bash
nautilus -q
NAUTILUS_TOTAL_SIZE_DEBUG=1 nautilus
```

Each queued folder and each completed walk logs to stderr, as does any Python
import error.

## Roadmap

- [ ] Fix folders stuck on `Calculating...` (async `InfoProvider` protocol)
- [ ] Persistent on-disk cache surviving restarts
- [ ] Filesystem monitoring (`GFileMonitor`) to invalidate on deep changes
- [ ] Optional startup indexing of selected drives
- [ ] Verified GNOME 47+ support

## License

MIT — see [LICENSE](LICENSE).
