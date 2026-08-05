# Installation guide

## 1. Install `nautilus-python`

The extension is written in Python, so Nautilus needs its Python binding. This
is a separate package from Nautilus itself.

| Distro | Command |
|---|---|
| Debian / Ubuntu / Pop!_OS / Mint | `sudo apt install python3-nautilus` |
| Fedora | `sudo dnf install nautilus-python` |
| Arch / Manjaro | `sudo pacman -S python-nautilus` |
| openSUSE | `sudo zypper install python3-nautilus` |

Verify it's present — this file must exist:

```bash
ls /usr/lib/*/nautilus/extensions-4/libnautilus-python.so
```

If that path doesn't exist but the package is installed, your Nautilus is
older than 4.0 and this extension will not load (see
[Version compatibility](#7-version-compatibility)).

## 2. Install the extension

Extensions live in `~/.local/share/nautilus-python/extensions/`. That
directory usually doesn't exist yet.

**Option A — download the released file:**

```bash
mkdir -p ~/.local/share/nautilus-python/extensions
curl -o ~/.local/share/nautilus-python/extensions/show_folder_size.py \
  https://raw.githubusercontent.com/doggylover314/show-folder-size-nautilus/main/show_folder_size.py
```

**Option B — from a clone:**

```bash
git clone https://github.com/doggylover314/show-folder-size-nautilus.git
cd show-folder-size-nautilus
./install.sh
```

`install.sh` just creates the directory and copies one file — read it first,
it's a dozen lines.

**Option C — system-wide, for all users:**

```bash
sudo mkdir -p /usr/share/nautilus-python/extensions
sudo cp show_folder_size.py /usr/share/nautilus-python/extensions/
```

## 3. Restart Nautilus

Extensions are loaded once at startup, so a running Nautilus won't see the new
file:

```bash
nautilus -q
```

This quits the background process **and closes any open file manager
windows** — save anything in progress first. The next time you open Files, the
extension loads.

## 4. Enable the column

The column is registered but hidden until you turn it on:

1. Open any folder in Files.
2. Switch to **List View** (the column only exists in list view — grid/icon
   view has no columns).
3. Open the **view options menu** and choose **Visible Columns…**, or
   right-click directly on the column header row.
4. Tick **Total Size**.

Folders will briefly show `Calculating...` while the background walk runs,
then switch to a size.

## 5. Choose where the cache lives (optional)

Since v0.3.0 measured sizes are cached on disk so they survive a restart. The
default is `~/.cache/show-folder-size-nautilus/`. To change it, or to turn writing
off entirely:

```ini
# ~/.config/show-folder-size-nautilus.conf
cache_dir=/some/other/path
# or, to disable on-disk caching completely:
cache_dir=
```

The `.deb` asks this at install time and records the system-wide default in
`/etc/show-folder-size-nautilus.conf`; the per-user file above overrides it.

## 6. Pre-index your drives (optional)

Fills the cache up front so sizes appear immediately rather than being
measured as you browse:

```bash
show-folder-size-index          # asks which drives to index
nautilus -q               # pick up the new cache
```

From a clone it's `./show-folder-size-index`. `--help` lists the rest.

## 7. Version compatibility

This extension targets **libnautilus-extension 4.0**, which is what GNOME 46
ships. Check yours:

```bash
nautilus --version
```

- **Nautilus 46.x** — tested and supported.
- **Nautilus 43–45** — also 4.0 API; likely works but untested.
- **Nautilus 47+** — untested. If it fails to load, the API version in
  `gi.require_version("Nautilus", "4.0")` may need bumping.
- **Nautilus 42 or older** — uses the 3.0 API and the older
  `~/.local/share/nautilus-python/extensions` loader semantics. Not supported.

## Troubleshooting

### The column doesn't appear in the Visible Columns list

The extension didn't load. Turn on tracing and watch the journal:

```bash
touch ~/.config/show-folder-size-nautilus-debug
nautilus -q
journalctl --user -f
```

Python syntax errors, a missing `nautilus-python`, or a wrong
`gi.require_version` all surface there as a traceback. Don't pipe through
`grep show-folder-size` — tracebacks don't contain that string, so it hides exactly
what you're looking for. Delete the marker file when you're done.

Also confirm the file is in the right place and readable:

```bash
ls -l ~/.local/share/nautilus-python/extensions/show_folder_size.py
```

### Everything says `Calculating...` and never finishes

Fixed in v0.2.2 — upgrade if you're on anything older. If you see it on a
current version, turn on tracing as above: a completed measurement logs a
`measured <path> in <n>s` line, so you can tell "still working" from "the
result never arrived", and that distinction is what to report in an issue.

### Sizes look wrong compared to `du`

Expected, within a small margin. This extension sums *apparent* file sizes and
ignores directory inodes, while `du` reports allocated blocks by default.
Compare against `du -sb --apparent-size` for a closer match.

### Uninstall

```bash
rm ~/.local/share/nautilus-python/extensions/show_folder_size.py
nautilus -q
```

Since v0.3.0 there is also a cache to remove if you want it gone:

```bash
rm -rf ~/.cache/show-folder-size-nautilus
```

If you installed the `.deb`, `sudo apt purge show-folder-size-nautilus` also removes
`/etc/show-folder-size-nautilus.conf`; a plain `remove` leaves it in place.
