# Spec for show-folder-size-nautilus.
#
# Build it with ./build-rpm.sh, which makes the tarball this expects, fills in
# the version from __version__ in show_folder_size.py, and puts the result in
# dist/.  Building by hand works too:
#
#     rpmbuild -ba fedora/show-folder-size-nautilus.spec
#
# once show-folder-size-nautilus-<version>.tar.gz is in ~/rpmbuild/SOURCES.
#
# WHAT IS DIFFERENT FROM THE .deb, AND WHY
# ----------------------------------------
# The payload is the same, file for file, and everything that is not
# packaging-format-specific comes from data/ so the two builds cannot drift.
# Three things genuinely differ:
#
#  * No debconf.  The .deb asks where the size cache should live, because
#    debconf is the one way to ask a question during a package install that
#    does not hang an unattended one.  RPM has no equivalent, and a %post
#    that prompts on stdin would break every automated install, so the
#    default is shipped as a %config(noreplace) file instead.  Editing it
#    survives upgrades, which is what dpkg-reconfigure was for.
#
#  * No Conflicts on nautilus-total-size.  That is the name this project used
#    up to 0.4.0 on Debian only; it was never packaged as an RPM, so there is
#    nothing on a Fedora machine to conflict with.
#
#  * Scriptlets are belt and braces.  Fedora's glib2, gtk-update-icon-cache
#    and desktop-file-utils all install file triggers that rebuild these
#    caches when a package drops a file in the matching directory, so %post
#    here is usually redundant.  It is kept because "usually" is doing work in
#    that sentence on rebuilds for anything older, and running
#    glib-compile-schemas twice costs nothing.  The schema recompile on
#    UNINSTALL is not redundant anywhere: the compiled cache keeps serving the
#    override's values after the override file is gone, which would leave
#    "Total Size" in every account's default column list on a machine that no
#    longer has the extension.

%global appid          io.github.doggylover314.ShowFolderSizeSetup
%global autostart_id   io.github.doggylover314.ShowFolderSizeIndex
%global extdir         %{_datadir}/nautilus-python/extensions

# The version has exactly one source of truth, __version__ in
# show_folder_size.py, and build-rpm.sh passes it in with --define _version.
# The literal below is the fallback for `rpmbuild -ba` run by hand -- and
# build-rpm.sh REFUSES TO BUILD if the two disagree, the same way it refuses
# on a stale version in the AppStream metainfo.  A version that is only
# checked when somebody looks at it is a version that will be wrong.
%global upstream_version 1.1.0

Name:           show-folder-size-nautilus
Version:        %{?_version}%{!?_version:%{upstream_version}}
Release:        1%{?dist}
Summary:        Total Size column for GNOME Files showing recursive folder sizes

License:        MIT
URL:            https://github.com/doggylover314/show-folder-size-nautilus
Source0:        %{name}-%{version}.tar.gz

BuildArch:      noarch

BuildRequires:  desktop-file-utils
BuildRequires:  libappstream-glib

# nautilus-python is the whole reason this loads at all, and it pulls in
# python3-gobject-base and nautilus-extensions itself.  Naming nautilus as
# well is deliberate: the extension is useless without a file manager to run
# inside, and show-folder-size-setup reads Nautilus' own GSettings schema.
Requires:       nautilus
Requires:       nautilus-python
Requires:       python3 >= 3.8
Requires:       python3-gobject-base

# Only the setup window needs GTK 4 and libadwaita.  The column itself and the
# indexer do not, so these are not hard requirements -- a machine without them
# still gets a working column, and the window exits with a message naming
# what to install rather than a typelib traceback.
Recommends:     gtk4
Recommends:     libadwaita

%description
Adds an optional "Total Size" column to the GNOME Files (Nautilus) list view
showing the recursive size of a folder's contents -- the same number the
Properties window reports -- instead of the built-in item count. Clicking the
column header sorts by size.

Sizes are measured in the background with Gio.File.measure_disk_usage and
cached on disk, so browsing never blocks and a folder measured once stays
instant across restarts. There is no network access and no subprocess use.
Writes are limited to the size cache, one marker file recording that the
column was enabled, and that column setting itself.

The column is enabled automatically the first time the extension loads, so
after installing you only need to run "nautilus -q".

Folder sizes are indexed at each login, in full the first time and then only
where something changed, after a short delay and at low priority. Each user
can switch that off or choose which folders it covers.

"Folder Size Setup" (show-folder-size-setup) is a small window for choosing
where sizes are cached, what the login indexing covers, and for pre-indexing
whole drives on the spot. The same indexing is available on the command line
as show-folder-size-index.

%prep
%autosetup

%build
# Nothing to compile: one Python module and two Python scripts.

%install
install -Dpm 0644 show_folder_size.py \
    %{buildroot}%{extdir}/show_folder_size.py
install -Dpm 0755 show-folder-size-index \
    %{buildroot}%{_bindir}/show-folder-size-index
install -Dpm 0755 show-folder-size-setup \
    %{buildroot}%{_bindir}/show-folder-size-setup

install -Dpm 0644 data/%{appid}.desktop \
    %{buildroot}%{_datadir}/applications/%{appid}.desktop
install -Dpm 0644 data/%{appid}.metainfo.xml \
    %{buildroot}%{_datadir}/metainfo/%{appid}.metainfo.xml
install -Dpm 0644 data/%{appid}.svg \
    %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/%{appid}.svg

# Makes Total Size a visible column by default.  An override file does
# nothing until the schema cache is recompiled -- see %post.
install -Dpm 0644 data/90_%{name}.gschema.override \
    %{buildroot}%{_datadir}/glib-2.0/schemas/90_%{name}.gschema.override

# The login indexer, for every account on the machine.  /etc/xdg/autostart
# because the XDG autostart spec looks in $XDG_CONFIG_DIRS, and a per-user
# file of the same name in ~/.config/autostart replaces it -- which is how
# "Folder Size Setup" switches it off for one account without root.
install -Dpm 0644 data/%{autostart_id}.desktop \
    %{buildroot}%{_sysconfdir}/xdg/autostart/%{autostart_id}.desktop

# The system-wide default the extension reads.  Shipped rather than generated
# in %post so that rpm treats an admin's edits as edits: %config(noreplace)
# leaves a changed file alone on upgrade and drops the new one beside it as
# .rpmnew.  A %post that rewrote this would silently revert those edits on
# every upgrade, which is exactly the bug the .deb's debconf seeding fixes.
install -d %{buildroot}%{_sysconfdir}
cat > %{buildroot}%{_sysconfdir}/%{name}.conf <<'EOF'
# System-wide defaults for show-folder-size-nautilus.
# Per-user override: ~/.config/show-folder-size-nautilus.conf
#
# cache_dir      : where measured folder sizes are kept. A leading ~/ is
#                  expanded per user, so the default gives every account its
#                  own cache. An EMPTY value disables on-disk caching
#                  entirely and nothing is written.
# autostart_dirs : what the login indexing run walks, colon-separated like
#                  PATH. Absent means each user's home directory.
# numeric_sort   : 0 makes the Total Size column sort alphabetically again,
#                  without the invisible sort key. On by default.
cache_dir=~/.cache/show-folder-size-nautilus
EOF
chmod 0644 %{buildroot}%{_sysconfdir}/%{name}.conf

%check
# Both validators are BuildRequires, so on Fedora these always run.  The
# guards are for building this spec on a machine that is not Fedora, where
# skipping a check beats failing to build at all.
if command -v desktop-file-validate >/dev/null 2>&1; then
    desktop-file-validate %{buildroot}%{_datadir}/applications/%{appid}.desktop
    desktop-file-validate \
        %{buildroot}%{_sysconfdir}/xdg/autostart/%{autostart_id}.desktop
else
    echo "skipping desktop-file-validate: not installed"
fi
if command -v appstream-util >/dev/null 2>&1; then
    appstream-util validate-relax --nonet \
        %{buildroot}%{_datadir}/metainfo/%{appid}.metainfo.xml
else
    echo "skipping appstream-util: not installed"
fi
# The extension and both commands must at least parse.
python3 -m py_compile show_folder_size.py show-folder-size-index \
    show-folder-size-setup
rm -rf __pycache__

%post
glib-compile-schemas %{_datadir}/glib-2.0/schemas &>/dev/null || :

%postun
# $1 is 0 on the last uninstall and 1 on an upgrade.  Only the uninstall needs
# this: on an upgrade the override file is still there.
if [ $1 -eq 0 ]; then
    glib-compile-schemas %{_datadir}/glib-2.0/schemas &>/dev/null || :
fi

%files
%license LICENSE
%doc README.md INSTALL.md CHANGELOG.md
%config(noreplace) %{_sysconfdir}/%{name}.conf
%dir %{_sysconfdir}/xdg/autostart
%{_sysconfdir}/xdg/autostart/%{autostart_id}.desktop
%{_bindir}/show-folder-size-index
%{_bindir}/show-folder-size-setup
%{extdir}/show_folder_size.py
%{_datadir}/applications/%{appid}.desktop
%{_datadir}/metainfo/%{appid}.metainfo.xml
%{_datadir}/icons/hicolor/scalable/apps/%{appid}.svg
%{_datadir}/glib-2.0/schemas/90_%{name}.gschema.override

%changelog
* Thu Sep 10 2026 doggylover314 <doggylover314@users.noreply.github.com> - 1.1.0-1
- Clicking the Total Size header sorts by size instead of by text.
- First RPM build; Fedora Workstation installs the same payload as the .deb.

* Sat Aug 22 2026 doggylover314 <doggylover314@users.noreply.github.com> - 1.0.0-1
- First stable release. See CHANGELOG.md for the full history.
