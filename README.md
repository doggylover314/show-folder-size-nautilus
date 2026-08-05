# nautilus-total-size

A **"Total Size"** column for GNOME Files (Nautilus) that shows the *recursive*
size of a folder's contents — like `du -sh` — instead of Nautilus' built-in
"12 items" count.

Sizes are computed on background threads and cached in memory, so browsing
never blocks. While a folder is being measured the column reads
`Calculating...`.

> **Status: early / v0.2.2.** Measurement now uses the same GIO call as
> Nautilus' Properties window, and sizes are formatted exactly like the
> built-in Size column. See [Known issues](#known-issues) before installing.

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
- Directory totals come from `Gio.File.measure_disk_usage()` — the same GIO
  call Nautilus' own Properties window uses — with `os.walk()` +
  `os.stat(follow_symlinks=False)` as a fallback.
- Measurements run on a small fixed thread pool (4 workers), never on the GTK
  main thread. Results cross back via `GLib.idle_add()` at `PRIORITY_DEFAULT`.
- Updates always return `COMPLETE`, never `IN_PROGRESS`; the finished
  measurement calls `invalidate_extension_info()` to make Nautilus re-read the
  cached value. See the header comment for why the async handle protocol isn't
  used.
- Sizes are formatted with `GLib.format_size()`, so they match the built-in
  Size column and follow your locale (base-10: 1 GiB reads as `1.1 GB`).
- Regular files are left blank — Nautilus' Size column already covers them.
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

As of **v0.2.2** this extension only ever *reads* the filesystem. Sizes come
from `Gio.File.measure_disk_usage()` (the same call Nautilus' Properties
window uses), falling back to `os.walk` / `os.stat` / `os.lstat`. There is:

- **no** `open()`, write, delete, rename, mkdir or chmod — this code creates
  nothing on disk, not even a cache file (the size cache is in RAM and dies
  with nautilus)
- **no** network use of any kind — no sockets, no HTTP, no DNS
- **no** subprocesses — no `subprocess`, `os.system`, `popen`, `exec*`, `fork`
- imports limited to stdlib (`os`, `stat`, `queue`, `threading`,
  `collections`, `sys`, `time`) plus PyGObject

It's a single ~300-line file with a header block stating the same thing, so
you can audit it at a glance before trusting it with your filesystem.

One honest caveat: CPython writes a `__pycache__/` bytecode directory next to
the extension when Nautilus imports it, exactly as it does for every Python
module. That's the interpreter, not this code, and it's safe to delete.

> **This will change in v0.3.0.** Persistent (on-disk) caching is planned,
> which means the extension *will* start writing one cache file under
> `~/.cache/`. The audit notes will be rewritten to say so honestly rather
> than quietly dropping the claim. If the strict no-writes property matters to
> you, pin v0.2.0.

## Known issues

- **Nautilus' built-in "Size" column can't be hidden by an extension.** If
  you'd rather see only this column, untick **Size** yourself in Visible
  Columns.
- **Sorting is alphabetical, not numeric.** Clicking the header puts `9.9 KB`
  before `1.2 GB`. The extension API exposes no sort-key hook, so this can't be
  fixed from inside an extension.
- **Deep changes don't invalidate the cache.** The key uses the folder's own
  mtime, which only changes when its *direct* children change. Edit a file
  three levels down and the total stays stale until `Ctrl+R` or a restart.
  Filesystem monitoring is planned for v0.3.0.
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

Create the marker file and watch the journal:

```bash
touch ~/.config/nautilus-total-size-debug
nautilus -q
journalctl --user -f | grep total-size
```

Note that `grep total-size` also hides Python tracebacks, which don't contain
that string. If something stops working entirely, drop the grep.

Each queued folder, each completed measurement (with timing) and any Python
import error is logged.

The `NAUTILUS_TOTAL_SIZE_DEBUG=1` environment variable also works, but it's
unreliable in practice: nautilus is D-Bus activated, so
`NAUTILUS_TOTAL_SIZE_DEBUG=1 nautilus` usually just hands your request to a
nautilus that is already running with a different environment, and the
variable never arrives. The marker file survives however nautilus is started.
Delete it when you're done.

## Roadmap

- [x] Fix folders stuck on `Calculating...`
- [x] Match the desktop's own size formatting
- [ ] Persistent on-disk cache surviving restarts
- [ ] Filesystem monitoring (`GFileMonitor`) to invalidate on deep changes
- [ ] Optional startup indexing of selected drives
- [ ] Verified GNOME 47+ support

## License

MIT — see [LICENSE](LICENSE).
