#!/bin/sh
# iSH realfs bind mounts can report 0644 regardless of host chmod.
# Copy into guest fakefs, verify permissions there, then publish atomically.
# Never print the private key or disable OpenSSH's security checks.
set -eu
umask 077
source_dir=${1:-/opt/minis-desktop}
private_dir=${2:-/tmp/minis-desktop-ssh}
test ! -L "$private_dir" || { echo 'SSH private directory is a symlink' >&2; exit 1; }
mkdir -p "$private_dir"
chmod 700 "$private_dir"
test "$(stat -c %a "$private_dir")" = 700
test "$(stat -c %u "$private_dir")" = "$(id -u)"
temp_key=$(mktemp "$private_dir/.identity.XXXXXX")
trap 'rm -f "$temp_key"' EXIT HUP INT TERM
cat "$source_dir/identity" > "$temp_key"
chmod 600 "$temp_key"
test -s "$temp_key"
test "$(stat -c %a "$temp_key")" = 600
test "$(stat -c %u "$temp_key")" = "$(id -u)"
mv -f "$temp_key" "$private_dir/identity"
temp_hosts=$(mktemp "$private_dir/.hosts.XXXXXX")
trap 'rm -f "$temp_key" "$temp_hosts"' EXIT HUP INT TERM
cat "$source_dir/known_hosts" > "$temp_hosts"
chmod 600 "$temp_hosts"
mv -f "$temp_hosts" "$private_dir/known_hosts"
test "$(stat -c %a "$private_dir/identity")" = 600
echo 'SSH guest identity prepared: directory=0700 key=0600'
