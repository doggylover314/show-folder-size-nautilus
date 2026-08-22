# Installation guide

## The short version

Download the `.deb` and **double-click it**. GNOME Software opens, you press
Install, and afterwards you run `nautilus -q`. The Total Size column turns
itself on the first time the extension loads — there is nothing to tick.

Everything below is for installing without the `.deb`, or for changing what
the defaults gave you.

## 0. Install from the `.deb`

```bash
sudo apt install ./show-folder-size-nautilus_1.0.0_all.deb
nautilus -q
```

Installing in a terminal like this asks where to keep the size cache. A
double-click install does **not** ask: GNOME Software drives dpkg through
PackageKit with a non-interactive debconf frontend, where every question is
answered with its default and nothing is shown. That is a property of every
`.deb` installed that way, not something this package can opt out of.

So the same settings — plus indexing your drives — live in a window instead:

```bash
show-folder-size-setup
```

or open **Folder Size Setup** from the applications menu. Use it to move the
cache, switch on-disk caching off entirely, turn the column on or off,
pre-index whole drives with a progress bar, and choose whether folder sizes
are re-indexed at login.

The package also installs `show-folder-size-index` for the same indexing on
the command line.

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
[Version compatibility](#8-version-compatibility)).

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

## 4. The column (usually automatic)

Since v0.6.0 the column enables itself the first time the extension loads, so
normally there is nothing to do here beyond switching to **List View** — the
column only exists in list view, since grid view has no columns.

Folders briefly show `Calculating...` while the background measurement runs,
then switch to a size.

To turn it on or off yourself:

1. Open any folder in Files, in **List View**.
2. Open the **view options menu** and choose **Visible Columns…**, or
   right-click directly on the column header row.
3. Tick or untick **Total Size**.

**Unticking it sticks.** The automatic enable happens exactly once and records
the fact in `~/.config/show-folder-size-nautilus-column-added`; it will not
reappear on the next restart. Delete that file to have it enabled
automatically once more.

If it never appeared in the first place, that file is the thing to check
first — followed by the tracing in [Troubleshooting](#troubleshooting).

## 5. Choose where the cache lives (optional)

Since v0.3.0 measured sizes are cached on disk so they survive a restart. The
default is `~/.cache/show-folder-size-nautilus/`.

The easiest way to change it is **Folder Size Setup**
(`show-folder-size-setup`), which writes the file below for you. By hand:

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
measured as you browse. Either open **Folder Size Setup**, tick the drives and
press *Index selected drives now*, or use the command line:

```bash
show-folder-size-index          # asks which drives to index
nautilus -q                     # pick up the new cache
```

From a clone it's `./show-folder-size-index`. `--help` lists the rest.

Indexing only ever reads. It can be stopped at any point — drives already
finished are kept rather than discarded.

## 7. Indexing at login (on by default from the `.deb`)

The package installs a system-wide autostart entry, so every account on the
machine keeps its folder sizes ready without doing anything:

```
/etc/xdg/autostart/io.github.doggylover314.ShowFolderSizeIndex.desktop
```

It runs `show-folder-size-index --autostart`, which waits 30 seconds after
login, drops to `nice 10`, indexes **your home directory** in full the first
time and then only re-measures what changed, and exits. It is not a service
and nothing stays resident. Only one copy runs at a time.

To index something other than your home directory, tick the drives in
**Folder Size Setup** and press *Use the drives ticked above*, or write it
yourself:

```ini
# ~/.config/show-folder-size-nautilus.conf
# colon-separated, like PATH
autostart_dirs=/home/you:/mnt/data
```

To turn it off for your account, use the switch in **Folder Size Setup**, or
by hand:

```bash
mkdir -p ~/.config/autostart
printf '[Desktop Entry]\nType=Application\nName=Folder Size Indexing\nHidden=true\n' \
  > ~/.config/autostart/io.github.doggylover314.ShowFolderSizeIndex.desktop
```

A user file of the same name replaces the system one, and `Hidden=true` means
"do not start this". Deleting that file puts the system entry back in charge.
Do not edit or delete the file in `/etc/xdg/autostart` itself: a package
upgrade restores it, and it applies to every user rather than just you.

Installing from a clone rather than the `.deb` gives you no system entry, so
nothing runs at login until you switch it on in **Folder Size Setup**, which
then writes a complete entry into `~/.config/autostart` instead.

Watch what it did:

```bash
journalctl --user -b | grep show-folder-size-index
```

## 8. Version compatibility

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

Since v0.3.0 there is also a cache to remove if you want it gone, since v0.6.0
a marker recording that the column was auto-enabled, and since v1.0.0 an
autostart override if you ever changed the login setting:

```bash
rm -rf ~/.cache/show-folder-size-nautilus
rm -f  ~/.config/show-folder-size-nautilus.conf
rm -f  ~/.config/show-folder-size-nautilus-column-added
rm -f  ~/.config/autostart/io.github.doggylover314.ShowFolderSizeIndex.desktop
```

The cache directory holds the `index.lock` file too; removing the directory
takes it with it.

Removing the package leaves the column ticked in your own settings, because
that is a dconf value belonging to you rather than to the package. Untick
**Total Size** in Visible Columns, or:

```bash
gsettings reset org.gnome.nautilus.list-view default-visible-columns
```

If you installed the `.deb`, `sudo apt purge show-folder-size-nautilus` also removes
`/etc/show-folder-size-nautilus.conf`; a plain `remove` leaves it in place.
