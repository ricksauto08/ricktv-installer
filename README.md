# RickTV public installer

This repository contains only the bootstrap installer and its tests. **RickTV
application code, accounts, settings and backups remain private.** You need a
GitHub account with access to `ricksauto08/RickTv` to complete installation.

## Install on a fresh Linux server

Run this in your new server's terminal as your normal user (not with sudo):

```sh
curl -fsSL https://raw.githubusercontent.com/ricksauto08/ricktv-installer/main/setup.sh | sh
```

Setup prompts for:

1. **Linux without Docker** (default) or **Docker**.
2. The new server's LAN IPv4 address. Check the suggested address before accepting.
3. GitHub sign-in, if needed. Open the displayed GitHub device-login page on any
   computer and enter the temporary code. Use the account allowed to read RickTV.
4. Your Linux sudo password when needed. Password entry does not show characters.

Native mode installs RickTV directly as Linux services. Docker mode requires
Docker Engine and Compose 2.30+ already installed; see the official
[Docker installation instructions](https://docs.docker.com/engine/install/).
The bootstrap does not install Docker automatically.

## Requirements

- A dedicated fresh Debian 13, Ubuntu 24.04, or Raspberry Pi OS Lite 64-bit Trixie
  server, with sudo access and internet access.
- 64-bit Intel/AMD or ARM64; Python 3.12 or newer.
- At least 20 GiB available storage before installation, plus recording space.
- Git and GitHub CLI; missing prerequisites are installed through apt during a
  normal installation. Install `curl` first if your OS does not include it.
- Native mode needs systemd. Raspberry Pi 4B with 4 GB RAM is a test target;
  physical ARM installation/playback validation is still pending. Camera
  multiview and software video conversion may exceed a Pi's practical capacity.

This creates an empty installation in `/opt/ricktv`. It does not restore saved
accounts, channel choices or recordings. Existing destinations are refused.
It does not format disks. Use a dedicated recording disk for ongoing use; a
32 GB SD card is intended for initial testing, not a recording library.

## Preview or inspect first

```sh
curl -fsSL https://raw.githubusercontent.com/ricksauto08/ricktv-installer/main/setup.sh -o ricktv-setup.sh
less ricktv-setup.sh
sh ricktv-setup.sh --plan
```

Preview requires prerequisites already installed. It authenticates and downloads
private source but does not install RickTV services. Options `--mode native` or
`--mode docker` and `--server-ip YOUR_SERVER_IP` can supply the answers directly.

GitHub authentication stays under your Linux user. Tokens are never included in
the command or clone URL. Source is downloaded over HTTPS into a new private
`~/ricktv-setup.*` directory. The installer prints the downloaded revision and
saves a local `SETUP-SUMMARY.txt`. On success, open the new server's port **8099**;
the full installation summary is `/opt/ricktv/SETUP.txt`.

If installation fails, keep the downloaded source and partial installation for
diagnosis. The private `install/README.md` explains resuming with the exact same
settings. This bootstrap intentionally cannot update or overwrite an existing
server. Authorized users can still use the private install commands for custom
storage and recovery options.

## Change notes

Initial bootstrap: separate public entry point, private GitHub authentication,
native/Docker choice, local IP validation, pipe-safe terminal prompts, fresh
destination protection, and a local setup summary. No application code or
personal settings are published here. Tests use fake commands and never install
services or access private source.

Validation: shell syntax and 13 isolated bootstrap regression tests passed,
including piped input with terminal sign-in, both install modes, failed login,
failed download, failed installation, IP validation and existing-server guards.
These checks validate the bootstrap; a complete installation on the Pi is the
next hardware test.

### DNS-permission repair

The initial bootstrap could pass its private-download file defaults to the
system installer. This is corrected: downloads and summaries stay private,
while system installation gets normal file defaults. The private installer also
refreshes DNS permissions when resuming. If an initial install stopped with DNS
errors, update the retained private checkout and use its exact-configuration
`--resume` instructions; do not erase the partial installation. All 13 bootstrap
regression tests pass, including the permission handoff.
