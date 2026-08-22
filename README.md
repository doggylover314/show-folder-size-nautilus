# show-folder-size-nautilus

A **"Total Size"** column for GNOME Files (Nautilus) that shows the *recursive*
size of a folder's contents — like `du -sh` — instead of Nautilus' built-in
"12 items" count.

Sizes are computed on background threads and cached on disk, so browsing never
blocks and a folder measured once stays instant across restarts. While a
folder is being measured the column reads `Calculating...`.

> **Status: v1.0.0.** Install the `.deb` by double-clicking it, run
> `nautilus -q`, and the column is there — it enables itself on first load.
> Measurement uses the same GIO call as Nautilus' Properties window, and
> sizes are formatted exactly like the built-in Size column. Folder sizes are
> re-indexed at each login so they stay ready; see
> [Indexing at login](#indexing-at-login).
> See [Known issues](#known-issues) before installing.

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

**Double-click the `.deb`.** GNOME Software opens, you press Install, then:

```bash
nautilus -q   # closes open windows; next launch loads the extension
```

Switch to **List View** and the column is already there. It enables itself the
first time the extension loads, once — untick it in **Visible Columns** and it
stays unticked.

### Or from the apt repository (recommended, and it keeps itself updated)

> **Not published yet.** The repository goes live with the 1.0.0 release;
> until then these commands will fail on the signing key, and the
> [releases page](https://github.com/doggylover314/show-folder-size-nautilus/releases)
> is the way in. Building it yourself from a clone works today:
> `./build-apt-repo.sh --key <YOURKEY>`.

Add it once and this upgrades with the rest of your system:

```bash
sudo install -d -m 0755 /etc/apt/keyrings
```

```bash
sudo curl -fsSL -o /etc/apt/keyrings/show-folder-size-nautilus.gpg https://doggylover314.github.io/show-folder-size-nautilus/show-folder-size-nautilus.gpg
```

```bash
echo "deb [signed-by=/etc/apt/keyrings/show-folder-size-nautilus.gpg] https://doggylover314.github.io/show-folder-size-nautilus stable main" | sudo tee /etc/apt/sources.list.d/show-folder-size-nautilus.list
```

```bash
sudo apt update && sudo apt install show-folder-size-nautilus
```

**This is the update mechanism.** There is deliberately no updater inside this
project: nothing here checks the network, and adding something that did would
have cost the "no network access" property that the audit notes are built
around, plus a privileged helper to do the installing. Your machine already
has a well-tested, signed, unattended-capable update system, so this uses it.
`unattended-upgrades` and GNOME Software pick it up with no further setup.

Or without the package:

```bash
mkdir -p ~/.local/share/nautilus-python/extensions
curl -o ~/.local/share/nautilus-python/extensions/show_folder_size.py \
  https://raw.githubusercontent.com/doggylover314/show-folder-size-nautilus/main/show_folder_size.py
nautilus -q
```

Full instructions, distro package names and troubleshooting:
**[INSTALL.md](INSTALL.md)**.

## Folder Size Setup

The `.deb` installs a small window — **Folder Size Setup**, or
`show-folder-size-setup` — for the things that have to be configured as you,
in your session:

- where sizes are cached, or switching on-disk caching off entirely
- turning the Total Size column on and off
- pre-indexing whole drives, with progress and a Stop button that keeps what
  it already measured
- whether folder sizes are re-indexed at login, and which folders that covers

It exists because a `.deb` installed by double-clicking **cannot ask you
anything**: GNOME Software drives dpkg through PackageKit with a
non-interactive debconf frontend, so every question is silently answered with
its default. And `postinst` runs as root, while the cache lives in your home
directory — so indexing at install time could only ever have filled root's
cache with sizes nobody reads.

Installing in a terminal (`sudo apt install ./…deb`) does still ask where to
put the cache, and records the answer as the system-wide default in
`/etc/show-folder-size-nautilus.conf`.

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
- Results are cached on disk keyed by `(path, directory mtime)`, so
  re-entering an unchanged folder is instant, including after a restart.

### Correctness details

Everything here is what `Gio.File.measure_disk_usage()` does, because that is
what the Properties window shows, and a column that disagrees with Properties
about the same folder is worse than one that is merely approximate. The
`os.walk` fallback and `show-folder-size-index` were each brought into line
with it in v1.0.0 by measuring, not by assuming.

- **Symlinks are never descended into**, so there are no link loops and no
  tree is counted twice. Each link does contribute its own size, which is the
  length of the path it points at — typically tens of bytes.
- **Hard links are counted once per link**, not once per inode. A file with
  two names inside the tree contributes its size twice. `du` de-duplicates, so
  totals here can exceed it on trees that use hard links heavily. Before
  v1.0.0 the fallback and the indexer de-duplicated and GIO did not, so the
  same folder measured two different sizes depending on which path ran.
- **Apparent size, not allocated blocks** — totals differ slightly from `du`
  on sparse files. Directory inodes are not counted.
- Unreadable files are skipped rather than aborting the whole total.

## Is it safe? (what it writes)

Up to v0.2.2 this extension wrote nothing at all, and that claim was the
headline of this section. It is no longer true, and it is listed here in full
rather than quietly dropped. **Your folders are still only ever read.** What
gets written is configuration and cache, all of it inside your home directory,
all of it safe to delete:

| Written | When | Prevent it by |
|---|---|---|
| `~/.cache/show-folder-size-nautilus/sizes-NN.json` | after each measurement, batched | setting the cache directory empty |
| `~/.cache/show-folder-size-nautilus/index.lock` | while indexing (zero bytes) | not indexing, or no cache directory |
| `~/.config/show-folder-size-nautilus-column-added` | once, ever | creating the file yourself first |
| the dconf key `org.gnome.nautilus.list-view default-visible-columns` | once, ever, alongside the marker above | the same marker file |
| `~/.config/show-folder-size-nautilus.conf` | only when you press Save in the setup window | not pressing it |
| `~/.config/autostart/…ShowFolderSizeIndex.desktop` | only when you change the login setting | not changing it |
| `~/.config/environment.d/60-show-folder-size-nautilus.conf` | only if you switch on the session-environment option | leaving it off, which is the default |

The cache is split across up to 100 shard files, each written atomically (temp
file + `os.replace`) so a crash cannot corrupt one, and each holding directory
paths, mtimes and byte counts, nothing else. Shards exist so that measuring a
few folders rewrites one small file rather than the whole cache, which at the
1,000,000-entry default would be 158 MB of pointless disk traffic, and real
SSD wear, every time.
A folder's contents are keyed to one shard, so browsing one directory dirties
one file. A shard is only created once something belongs in it. Note that emptying the cache directory disables the **cache** only; the
one-off column write is governed by its marker file, not by that setting. Do
both and the extension touches nothing.

Beyond that:

- **no** deletes, renames, chmod, or mkdir outside the cache directory
- **no** network use of any kind — no sockets, no HTTP, no DNS
- **no** subprocesses — no `subprocess`, `os.system`, `popen`, `exec*`, `fork`
- **no** daemon or background service. The login indexing is one process that
  runs, indexes and exits.
- imports limited to the standard library (`os`, `stat`, `sys`, `json`,
  `queue`, `tempfile`, `threading`, `time`, `collections`; `fcntl` and
  `argparse` in the indexer) plus PyGObject

Every one of these is restated in the header comment of
[`show_folder_size.py`](show_folder_size.py), so you can check the claim
against the code in one file before trusting it with your filesystem.

One honest caveat: CPython writes a `__pycache__/` bytecode directory next to
the extension when Nautilus imports it, exactly as it does for every Python
module. That's the interpreter, not this code, and it's safe to delete.

## Pre-indexing whole drives

Browsing measures folders on demand, which is fast but still shows
`Calculating...` the first time. `show-folder-size-index` walks drives up front and
fills the cache, so sizes are there from the first look:

```bash
show-folder-size-index                # lists your drives, asks which to index
show-folder-size-index --all          # every local drive, no prompt
show-folder-size-index ~/Videos       # just these paths
show-folder-size-index --list         # show what it would offer, do nothing
show-folder-size-index --all --dry-run   # measure and report, write nothing
show-folder-size-index --all --refresh   # only re-measure what changed
```

Then `nautilus -q` to pick up the new cache.

It walks each tree **bottom-up in a single pass**, so every directory in it
gets a size for the cost of reading the tree once. Measuring each directory
independently would be quadratic — a tree ten deep read ten times.

By default it does **not cross mount points**: indexing `/` stops at the edge
of the root filesystem and never descends into an external drive, `/proc`,
`/sys` or `/run`. Pass `--cross-mounts` to allow it. (Before v1.0.0 it walked
into all of them and then discarded the results, which cost the full reading
time and saved nothing.) Note that btrfs subvolumes and bind mounts report a
different device too, so the same boundary applies to them.

`--refresh` re-measures only directories whose mtime changed since the last
run, which on a barely-changed drive skips almost all of the work. The catch,
stated plainly: directory mtime does not move when an existing file is written
to in place, so a download growing inside an otherwise untouched folder is
invisible to a refresh. That is the same assumption the extension's own cache
key makes, which is why it also watches directories, but it is why a plain run
without the flag still measures everything.

Ctrl-C saves what it has already measured rather than discarding the work. The
cache is capped (`--max-entries`, or `max_entries=` in the config file,
default 1000000) keeping the **largest**
directories, since those are the ones worth not measuring again. Only one
indexer runs at a time, enforced with a lock file.

If you installed from the `.deb` it's on your `PATH`; from a clone, run
`./show-folder-size-index`.

## Indexing at login

The `.deb` installs `/etc/xdg/autostart/…ShowFolderSizeIndex.desktop`, so
every account on the machine indexes its folders shortly after logging in:
**in full the first time, and afterwards only where something changed.** It
waits 30 seconds first and runs at `nice 10`, so it isn't competing with the
rest of your session starting up, and it exits when it's done. There is no
daemon.

By default it indexes **your home directory only**, not every drive. That is
deliberate: the entry is system-wide, and a default of "every local disk"
would have every account on a shared machine walking every disk at its first
login.

Open **Folder Size Setup** to change either half of that:

- the **Index at every login** switch turns it off, or back on, for your
  account only
- **Use the drives ticked above** records the drives you've ticked as what the
  login run should cover

Switching it off writes `~/.config/autostart/…ShowFolderSizeIndex.desktop`
with `Hidden=true`. Per the XDG autostart spec a user file replaces the
system one of the same name, and `Hidden=true` means "don't start this" — it
is the only way a normal user can override a file in `/etc` they cannot write.
Switching it back on deletes that override rather than writing an enabled
copy, so a later package update to the entry still reaches you.

To do the same by hand:

```bash
show-folder-size-index --autostart      # exactly what the login entry runs
```

and in `~/.config/show-folder-size-nautilus.conf`:

```ini
# colon-separated, like PATH; absent means your home directory
autostart_dirs=/home/you:/mnt/data
```

## Upgrading, and keeping the cache you already built

Upgrading is `apt upgrade` if you added the repository above, or installing a
newer `.deb` over the old one. Either way:

- Installing over **`nautilus-total-size`**, the name this project used up to
  0.4.0, removes it. Before v1.0.0 it did not: every file had been renamed in
  the 0.5.0 rename, so dpkg saw two unrelated packages, installed both, and
  Nautilus drew **two** Total Size columns.
- v1.0.0 changed what a cached byte count means, so it does not silently reuse
  a cache written by an older version. It is not thrown away either. Open
  **Folder Size Setup** and use **Import an older cache**:
  - it auto-detects caches on this machine, including ones left under the old
    `~/.cache/nautilus-total-size/` path and ones moved somewhere else by an
    older config file
  - or point it at any `sizes.json` yourself
  - importing merges the entries in and tells you if they came from a version
    whose totals read slightly low

Where the cache lives is recorded in your config the first time you open the
setup window, so an upgrade never has to guess. If you want that location
visible to everything in your session, including terminals, switch on **Also
set `SHOW_FOLDER_SIZE_CACHE` in the session** and log in again. Note that it
then takes precedence over the location in the window, which is why it is off
by default.

## Telling other people about it

- **Point them at the apt repository lines above**, not at a `.deb` download.
  A `.deb` is a one-off that never updates; the repository means they get
  fixes without doing anything.
- The `.deb` renders properly in GNOME Software (icon, description, screenshot
  metadata), so "download it and double-click" works for people who would
  rather not touch a terminal.
- Places this kind of thing belongs: r/gnome and r/linux, the GNOME Discourse
  "Extensions" area, Lobsters and Hacker News if you want a spike of traffic,
  and the Nautilus issue tracker threads where people ask for recursive folder
  sizes, which is where anyone searching will actually land.
- Add the GitHub topics `nautilus`, `gnome`, `nautilus-extension`,
  `file-manager` so the repository shows up in topic searches.
- Longer term, the two places that get it in front of people without them
  finding you first are a Launchpad PPA and Debian proper (`mentors.debian.net`
  and an ITP bug). Both are more work than a Pages repository; neither is
  worth doing until this has survived contact with a few strangers.

## Configuration

Where the cache lives, highest precedence first:

1. `SHOW_FOLDER_SIZE_CACHE` environment variable
2. `cache_dir=` in `~/.config/show-folder-size-nautilus.conf`
3. `cache_dir=` in `/etc/show-folder-size-nautilus.conf` (written by the `.deb`)
4. `$XDG_CACHE_HOME/show-folder-size-nautilus` — i.e. `~/.cache/show-folder-size-nautilus`

Setting any of them to an **empty value disables on-disk caching entirely**:

```ini
# ~/.config/show-folder-size-nautilus.conf
cache_dir=
```

The same two files also hold `autostart_dirs=`, which is what the login run
indexes — see [Indexing at login](#indexing-at-login). Both files are plain
`key=value`; `#` starts a comment, the user file wins over `/etc`, and a key
that is absent is not the same as a key that is present and empty (absent
means "nobody chose", empty means "chose nothing").

## Filesystem monitoring

Directories you visit are watched with `GFileMonitor`. When one changes, the
cached total for it **and every ancestor** is dropped — a file written three
levels down changes all of their totals, so invalidating only the immediate
directory would leave the folder you're looking at showing a stale number.

Linux has no recursive watch, and putting one on every subdirectory would
exhaust the inotify limit on any real disk. So watches are bounded
(`MONITOR_LIMIT`, 256) and evicted least-recently-used. The practical
consequence: **deep changes are noticed in directories you've visited
recently**. Change something far below a folder nobody is watching and its
total stays cached until its own mtime changes. `Ctrl+R` forces a recount.

## Known issues

- **Nautilus' built-in "Size" column can't be hidden by an extension.** If
  you'd rather see only this column, untick **Size** yourself in Visible
  Columns.
- **Uninstalling leaves the column ticked.** Enabling it writes a dconf value
  that belongs to your account, not to the package, so `apt purge` cannot take
  it back. Untick it, or run
  `gsettings reset org.gnome.nautilus.list-view default-visible-columns`.
- **Sorting is alphabetical, not numeric.** Clicking the header puts `9.9 KB`
  before `1.2 GB`. The extension API exposes no sort-key hook, so this can't be
  fixed from inside an extension.
- **Deep changes are only caught in watched directories** — see
  [Filesystem monitoring](#filesystem-monitoring) for the bound and why.
- **Live measurement crosses mount points**, so a folder containing a mounted
  volume includes that volume's contents. This is the column, not the indexer:
  `show-folder-size-index` stops at mount boundaries unless told otherwise, so
  the two can disagree about a folder with a mount inside it.
- **Hard-linked files count once per link**, so totals can exceed `du` — see
  [Correctness details](#correctness-details) for why that is deliberate.
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
touch ~/.config/show-folder-size-nautilus-debug
nautilus -q
journalctl --user -f | grep show-folder-size
```

Note that `grep show-folder-size` also hides Python tracebacks, which don't contain
that string. If something stops working entirely, drop the grep.

Each queued folder, each completed measurement (with timing) and any Python
import error is logged.

The `SHOW_FOLDER_SIZE_DEBUG=1` environment variable also works, but it's
unreliable in practice: nautilus is D-Bus activated, so
`SHOW_FOLDER_SIZE_DEBUG=1 nautilus` usually just hands your request to a
nautilus that is already running with a different environment, and the
variable never arrives. The marker file survives however nautilus is started.
Delete it when you're done.

## Roadmap

- [x] Fix folders stuck on `Calculating...`
- [x] Match the desktop's own size formatting
- [x] Persistent on-disk cache surviving restarts
- [x] Filesystem monitoring (`GFileMonitor`) to invalidate on deep changes
- [x] Optional pre-indexing of selected drives
- [x] Working double-click install, with an icon and description
- [x] Column enabled automatically on first run
- [x] Setup window for cache location and drive indexing
- [x] Indexing at login, full once and incremental after, off-switch per user
- [ ] Verified GNOME 47+ support

## License

MIT — see [LICENSE](LICENSE).
