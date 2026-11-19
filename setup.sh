#!/bin/sh
# Goal: one public entry point for a fresh install of private RickTV software.
# This bootstrap contains no application code, accounts, settings or backups.
# Prompts use /dev/tty because stdin may contain this script (curl | sh).
set -eu

die() { printf '\nRickTV setup: %s\n' "$*" >&2; exit 1; }
say() { printf '%s\n' "$*"; }
terminal() {
    if ! { exec 3<>/dev/tty; } 2>/dev/null; then
        die 'An interactive terminal is required. Run this from your SSH terminal.'
    fi
}
ask() {
    terminal
    printf '%s' "$1" >&3
    IFS= read -r answer <&3 || die 'Input cancelled.'
}
usage() {
    cat <<'HELP'
RickTV fresh-install bootstrap
  sh setup.sh [--mode native|docker] [--server-ip IPv4] [--plan]
  sh setup.sh --help

Without options, prompts for installation type and this server's LAN address.
Native Linux is the default. Docker mode requires Engine and Compose 2.30+.
Sign in with a GitHub account that can read the private RickTV repository.
--plan downloads private source and previews settings without installing RickTV.
Existing servers are not upgraded or restored by this bootstrap.
HELP
}

main() {
    mode=''; server_ip=''; plan=0
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --help|-h) usage; return 0 ;;
            --mode) [ "$#" -ge 2 ] || die '--mode needs a value.'; mode=$2; shift 2 ;;
            --server-ip) [ "$#" -ge 2 ] || die '--server-ip needs a value.'; server_ip=$2; shift 2 ;;
            --plan) plan=1; shift ;;
            *) die "Unknown option: $1" ;;
        esac
    done
    case "$mode" in ''|native|docker) ;; *) die 'Choose native or docker.' ;; esac
    [ "$(uname -s)" = Linux ] || die 'Run this on the new Linux server, not Windows.'
    case "$(uname -m)" in x86_64|amd64|aarch64|arm64) ;; *) die '64-bit x86 or ARM Linux is required.' ;; esac
    [ "$(id -u)" != 0 ] || die 'Run as your normal Linux user, without sudo. Setup requests sudo when needed.'
    command -v sudo >/dev/null 2>&1 || die 'Install sudo and give your user sudo access first.'
    [ ! -e /opt/ricktv ] && [ ! -L /opt/ricktv ] || die '/opt/ricktv already exists. Use the private recovery/resume instructions; nothing was overwritten.'

    say 'RickTV setup: public installer, private application.'
    say 'Goal: a fresh server with empty settings. Existing backups are not imported.'
    missing=0
    for tool in git gh python3; do command -v "$tool" >/dev/null 2>&1 || missing=1; done
    if [ "$missing" = 1 ]; then
        [ "$plan" = 0 ] || die 'Preview requires git, gh and Python 3.12+ already installed.'
        command -v apt-get >/dev/null 2>&1 || die 'Install git, gh, Python 3.12+ and CA certificates first.'
        terminal
        say 'Installing Git, GitHub CLI, Python and CA certificates using apt.'
        sudo apt-get update <&3
        sudo apt-get install -y git gh python3 ca-certificates <&3
    fi
    python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)' || die 'Python 3.12+ is required. Use Debian 13, Ubuntu 24.04 or Raspberry Pi OS Lite 64-bit Trixie.'

    if [ -z "$mode" ]; then
        ask 'Install type: 1 = Linux without Docker, 2 = Docker [1]: '
        case "$answer" in ''|1) mode=native ;; 2) mode=docker ;; *) die 'Choose 1 or 2.' ;; esac
    fi
    if [ "$mode" = docker ]; then
        command -v docker >/dev/null 2>&1 || die 'Install Docker Engine and Compose 2.30+ first: https://docs.docker.com/engine/install/'
        compose_version=$(docker compose version --short) || die 'Docker Compose is unavailable.'
        python3 -c 'import sys; v=sys.argv[1].lstrip("v").split("."); sys.exit(0 if tuple(map(int,v[:2])) >= (2,30) else 1)' "$compose_version" || die 'Docker Compose 2.30+ is required.'
    else
        command -v apt-get >/dev/null 2>&1 || die 'Native installation requires an apt-based Linux distribution.'
        [ -d /run/systemd/system ] || die 'Native installation requires systemd running on this server.'
    fi
    if [ -z "$server_ip" ]; then
        detected_ip=$(hostname -I 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i ~ /^[0-9]+\./) {print $i; exit}}')
        ask "This server's LAN IPv4 address [$detected_ip]: "
        server_ip=${answer:-$detected_ip}
    fi
    # Validate the literal and local ownership before downloading private software.
    python3 -c 'import ipaddress,socket,sys
try:
 a=ipaddress.IPv4Address(sys.argv[1])
 assert not (a.is_loopback or a.is_unspecified or a.is_multicast or a.is_reserved)
 with socket.socket() as s: s.bind((str(a),0))
except (ValueError,AssertionError,OSError): sys.exit(1)' "$server_ip" || die 'That must be an IPv4 address assigned to this new server.'

    if ! gh auth status --hostname github.com >/dev/null 2>&1; then
        terminal
        say 'Sign in to GitHub in your browser when prompted. Never paste a password or token into this script.'
        gh auth login --hostname github.com --git-protocol https --web <&3 || die 'GitHub sign-in did not finish.'
    fi
    private=$(gh api repos/ricksauto08/RickTv --jq .private) || die 'Your GitHub account needs access to the private ricksauto08/RickTv repository.'
    [ "$private" = true ] || die 'Expected a private RickTV repository; stopping for review.'

    umask 077
    # Unique user-owned directory: never overwrite a checkout or copy credentials.
    download_dir=$(mktemp -d "$HOME/ricktv-setup.XXXXXXXX")
    say "Downloading private RickTV into $download_dir/source"
    if ! GIT_TERMINAL_PROMPT=0 git -c credential.helper= -c 'credential.helper=!gh auth git-credential' clone --depth 1 --branch main -- https://github.com/ricksauto08/RickTv.git "$download_dir/source"; then
        die "Download failed. No RickTV services were installed. Temporary directory: $download_dir"
    fi
    source_dir=$download_dir/source
    case "$mode" in native) entry=install-linux.sh ;; docker) entry=install-docker.sh ;; esac
    [ -f "$source_dir/$entry" ] && [ -f "$source_dir/install/install.py" ] || die 'The private repository is missing its installer.'
    revision=$(git -C "$source_dir" rev-parse HEAD)
    say "RickTV source revision: $revision"
    say "Installation: $mode; server: $server_ip; destination: /opt/ricktv"
    # Save a small local handoff, never credentials. The private installer produces
    # SETUP.txt and READY.json after it finishes checking the installed services.
    printf 'RickTV fresh setup\nMode: %s\nServer: %s\nSource revision: %s\nSource: %s\n' "$mode" "$server_ip" "$revision" "$source_dir" > "$download_dir/SETUP-SUMMARY.txt"
    if [ "$plan" = 1 ]; then
        bash "$source_dir/$entry" --server-ip "$server_ip" --plan
        say 'Preview only: no RickTV services installed. GitHub login and downloaded source stay on this box.'
        return 0
    fi
    terminal
    say 'Starting the private installer. It checks ports, disk space and existing services before installing.'
    if ! sudo bash "$source_dir/$entry" --server-ip "$server_ip" <&3; then
        say "Installation did not finish. Source and summary are retained in $download_dir"
        die 'Do not erase the install directory or repeat as a fresh install. See the private install/README.md for exact-configuration resume instructions.'
    fi
    say "RickTV installation finished. Open http://$server_ip:8099/"
    say 'Installation summary: /opt/ricktv/SETUP.txt'
}

# Keep invocation last so pipe input is parsed before any interactive command.
main "$@"
