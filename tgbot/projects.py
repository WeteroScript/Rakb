"""Known mobile-CRMP projects and what their servers expect from a client.

A vanilla SA-MP 0.3.7 client and a mobile-CRMP launcher do not speak the same join
sequence, and a project that only accepts its own launcher answers nothing at all
to a stock open-connection request. That looks exactly like a wrong port or an IP
block, so the bot needs to be able to name the project instead of guessing.

Data here is from public sources, recorded with their URLs so it can be re-checked:

* libertycity.net/servers/black-russia/ - server list, addresses, "played through
  the project's own launcher" (Google Play / App Store / RuStore).
* blast.hk/threads/94904/ - static analysis of Black Russia's libsamp.so:
  ClientJoin uses version 24342 (not 4057), mod 1, challenge ^ 0xFD9, a fixed
  40-char joinAuthKey, clientVer "0.3.7"; the client is additionally checked via
  packet 168, which a stock client does not implement; server IPs are hardcoded
  in libsamp.so. The thread also states plainly that this data alone is not enough
  for normal play on the server.
* blast.hk/threads/138834/ - address/port list for CRMP/SAMP Mobile projects
  (all Black Russia servers on port 5125).
"""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field


@dataclass(frozen=True)
class MobileProject:
    name: str
    networks: tuple[str, ...]
    port: int
    join_version: int | None
    notes: tuple[str, ...]
    sources: tuple[str, ...]
    siblings: tuple[str, ...] = field(default_factory=tuple)

    def matches(self, ip: str, port: int | None = None) -> bool:
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return False
        if not any(addr in ipaddress.ip_network(n) for n in self.networks):
            return False
        return port is None or port == self.port


BLACK_RUSSIA = MobileProject(
    name="Black Russia",
    networks=("80.66.82.0/24", "80.66.71.0/24"),
    port=5125,
    join_version=24342,
    notes=(
        "Mobile CRMP project; play goes through its own launcher "
        "(Google Play / App Store / RuStore), not a stock SA-MP client.",
        "ClientJoin carries version 24342 instead of the vanilla 4057, mod 1, "
        "challenge ^ 0xFD9, a fixed 40-char joinAuthKey and clientVer \"0.3.7\".",
        "The client is checked again through packet 168, which a stock 0.3.7 "
        "client does not implement.",
        "Server IPs are hardcoded in the launcher's libsamp.so.",
        "Published reverse-engineering notes state explicitly that these fields "
        "alone are not enough to play on the server.",
    ),
    sources=(
        "https://libertycity.net/servers/black-russia/",
        "https://www.blast.hk/threads/94904/",
        "https://www.blast.hk/threads/138834/",
    ),
    siblings=(
        "80.66.82.46",    # RED
        "80.66.82.237",   # BLACK
        "80.66.82.157",   # MOSCOW
    ),
)

PROJECTS: tuple[MobileProject, ...] = (BLACK_RUSSIA,)

# Vanilla 0.3.7 join parameters, for contrast in the bot's output.
VANILLA_JOIN_VERSION = 4057


def identify(ip: str, port: int | None = None) -> MobileProject | None:
    """Return the known mobile-CRMP project owning this address, if any."""
    for project in PROJECTS:
        if project.matches(ip, port):
            return project
    return None
