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
[Version compatibility](#4-version-compatibility)).

## 2. Install the extension

Extensions live in `~/.local/share/nautilus-python/extensions/`. That
directory usually doesn't exist yet.

**Option A — download the released file:**

```bash
mkdir -p ~/.local/share/nautilus-python/extensions
curl -o ~/.local/share/nautilus-python/extensions/total_size_column.py \
  https://raw.githubusercontent.com/doggylover314/nautilus-total-size/main/total_size_column.py
```

**Option B — from a clone:**

```bash
git clone https://github.com/doggylover314/nautilus-total-size.git
cd nautilus-total-size
./install.sh
```

`install.sh` just creates the directory and copies one file — read it first,
it's a dozen lines.

**Option C — system-wide, for all users:**

```bash
sudo mkdir -p /usr/share/nautilus-python/extensions
sudo cp total_size_column.py /usr/share/nautilus-python/extensions/
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

## 5. Version compatibility

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

The extension didn't load. Run Nautilus from a terminal to see why:

```bash
nautilus -q
NAUTILUS_TOTAL_SIZE_DEBUG=1 nautilus
```

Python syntax errors, a missing `nautilus-python`, or a wrong
`gi.require_version` all surface here as a traceback.

Also confirm the file is in the right place and readable:

```bash
ls -l ~/.local/share/nautilus-python/extensions/total_size_column.py
```

### Everything says `Calculating...` and never finishes

This is a known bug in v0.1.0 — see
[Known issues](README.md#known-issues) in the README. It is being worked on.

Genuinely large trees do legitimately take a while on first view; the debug
output above will tell you which case you're in (a completed walk logs a
result line).

### Sizes look wrong compared to `du`

Expected, within a small margin. This extension sums *apparent* file sizes and
ignores directory inodes, while `du` reports allocated blocks by default.
Compare against `du -sb --apparent-size` for a closer match.

### Uninstall

```bash
rm ~/.local/share/nautilus-python/extensions/total_size_column.py
nautilus -q
```

Since v0.3.0 there is also a cache to remove if you want it gone:

```bash
rm -rf ~/.cache/nautilus-total-size
```

If you installed the `.deb`, `sudo apt purge nautilus-total-size` also removes
`/etc/nautilus-total-size.conf`; a plain `remove` leaves it in place.
