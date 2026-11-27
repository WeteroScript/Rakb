"""SA-MP server query over UDP (the 'SAMP' query protocol).

Doubles as a reachability probe for the container's outbound UDP:
  - query answers, but RakNet /connect fails -> UDP egress works, problem is at
    the game-protocol layer (version / cookie / server-side filtering of the play
    connection).
  - query times out -> outbound UDP is blocked on the host, or the server
    firewalls this container's source IP. SA-MP needs UDP, so the client cannot
    connect until that is resolved.
"""
from __future__ import annotations

import asyncio
import random
import socket
import struct


def _query_sync(ip: str, port: int, opcode: str, timeout: float) -> bytes:
    resolved = socket.gethostbyname(ip)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        header = b"SAMP" + socket.inet_aton(resolved) + struct.pack("<H", port)
        pkt = header + opcode.encode("ascii")
        if opcode == "p":
            pkt += b"\x00\x00\x00\x00"
        sock.sendto(pkt, (resolved, port))
        data, _ = sock.recvfrom(4096)
        return data
    finally:
        sock.close()


def _parse_info(data: bytes) -> dict:
    # header: "SAMP"(4) + ip(4) + port(2) + opcode(1) = 11 bytes
    if len(data) < 11 or data[:4] != b"SAMP":
        raise ValueError("malformed query response")
    off = 11
    password = data[off]
    off += 1
    players, maxplayers = struct.unpack("<HH", data[off:off + 4])
    off += 4

    def read_str(o: int):
        n = struct.unpack("<I", data[o:o + 4])[0]
        o += 4
        s = data[o:o + n].decode("latin-1", "replace")
        return s, o + n

    hostname, off = read_str(off)
    gamemode, off = read_str(off)
    language, off = read_str(off)
    return {
        "password": bool(password), "players": players, "maxplayers": maxplayers,
        "hostname": hostname, "gamemode": gamemode, "language": language,
    }


async def query_server(ip: str, port: int, timeout: float = 3.0) -> dict:
    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(None, _query_sync, ip, port, "i", timeout)
    return _parse_info(data)


# Large, long-lived public SA-MP servers used purely as UDP-egress control probes.
# If at least one answers, outbound UDP from the container works.
REFERENCE_SERVERS = (
    ("185.169.134.188", 7777),  # RADMIR RolePlay 08
    ("185.169.134.22", 7771),   # Samp-Rp.Ru 09
    ("46.39.225.193", 7778),    # GTA LEAGUE
)

# Public DNS resolvers answer a UDP query from any source, so they are the most
# reliable test of whether UDP egress AND the return path work at all.
DNS_RESOLVERS = ("8.8.8.8", "1.1.1.1")

# Public NTP servers answer on UDP port 123 (a NON-53 port). If DNS (53) works but
# SA-MP is silent, NTP tells us whether arbitrary-port UDP works: NTP answers ->
# the game servers filter this hosting IP; NTP also silent -> likely only DNS UDP
# is permitted (or NTP is blocked), i.e. a host egress restriction.
NTP_SERVERS = ("time.google.com", "time.cloudflare.com")

# STUN is the decisive probe: it answers on HIGH UDP ports (19302 / 3478), the same
# port range SA-MP uses. DNS (53) and NTP (123) are well-known low ports that hosts
# often permit individually, so they do NOT prove arbitrary-port UDP works.
# A STUN reply also carries the container's real egress IP, which is what a game
# server would see and could be firewalled by.
STUN_SERVERS = (
    ("stun.l.google.com", 19302),
    ("stun1.l.google.com", 19302),
    ("stun.cloudflare.com", 3478),
    ("stun.stunprotocol.org", 3478),
)

STUN_MAGIC = 0x2112A442


def _stun_query_sync(server: str, port: int, timeout: float) -> str | None:
    """RFC 5389 Binding Request -> the XOR-MAPPED-ADDRESS IPv4, or None.

    Returning the mapped address (not just True) proves a real STUN answer came
    back and reveals which source IP the outside world sees for this container.
    """
    tid = random.randbytes(12)
    pkt = struct.pack(">HHI", 0x0001, 0, STUN_MAGIC) + tid  # Binding Request, no attrs
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(pkt, (server, port))
        data, _ = sock.recvfrom(2048)
        if len(data) < 20:
            return None
        mtype, mlen, magic = struct.unpack(">HHI", data[:8])
        if magic != STUN_MAGIC or data[8:20] != tid:
            return None
        if mtype != 0x0101:  # Binding Success Response
            return None
        off = 20
        end = min(len(data), 20 + mlen)
        fallback = None
        while off + 4 <= end:
            atype, alen = struct.unpack(">HH", data[off:off + 4])
            val = data[off + 4:off + 4 + alen]
            off += 4 + alen + ((4 - alen % 4) % 4)  # attributes are 32-bit padded
            if len(val) < 8 or val[1] != 0x01:  # IPv4 family
                continue
            if atype == 0x0020:  # XOR-MAPPED-ADDRESS
                addr = struct.unpack(">I", val[4:8])[0] ^ STUN_MAGIC
                return socket.inet_ntoa(struct.pack(">I", addr))
            if atype == 0x0001:  # MAPPED-ADDRESS (plain, older servers)
                fallback = socket.inet_ntoa(val[4:8])
        return fallback
    except (socket.timeout, TimeoutError, OSError):
        return None
    finally:
        sock.close()


def _ntp_query_sync(server: str, timeout: float, port: int = 123) -> bool:
    # NTP client request: LI=0, VN=3, Mode=3 -> 0x1B, then 47 zero bytes (48 total).
    pkt = b"\x1b" + 47 * b"\x00"
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(pkt, (server, port))
        data, _ = sock.recvfrom(1024)
        return len(data) >= 48
    except (socket.timeout, TimeoutError, OSError):
        return False
    finally:
        sock.close()


def _dns_query_sync(server: str, timeout: float, port: int = 53) -> bool:
    tid = random.randint(0, 65535)
    # header: id, flags=0x0100 (recursion desired), QDCOUNT=1, rest 0
    header = struct.pack(">HHHHHH", tid, 0x0100, 1, 0, 0, 0)
    question = b"\x06google\x03com\x00" + struct.pack(">HH", 1, 1)  # google.com A IN
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(header + question, (server, port))
        data, _ = sock.recvfrom(512)
        if len(data) >= 12:
            rid, flags = struct.unpack(">HH", data[:4])
            return rid == tid and bool(flags & 0x8000)  # matching id + QR=response
        return False
    except (socket.timeout, TimeoutError, OSError):
        return False
    finally:
        sock.close()


# --- SA-MP 0.3.7 game-connection handshake (the bytes the client itself sends) ---
# Every client->server datagram is obfuscated with samp_encode (see sampnetencr).
# Server->client datagrams are plaintext.
# C->S  18 00 00            ID_OPEN_CONNECTION_REQUEST (24)
# S->C  1a <cookie:2>       ID_OPEN_CONNECTION_COOKIE (26) challenge
# C->S  18 <cookie^0x6969>  challenge answer
# S->C  19 ..               ID_OPEN_CONNECTION_REPLY (25) -> handshake accepted
ID_OPEN_CONNECTION_REQUEST = 24
ID_OPEN_CONNECTION_COOKIE = 26
ID_OPEN_CONNECTION_REPLY = 25
ID_CONNECTION_ATTEMPT_FAILED = 29
ID_NO_FREE_INCOMING_CONNECTIONS = 31
COOKIE_XOR = 0x6969  # NETCODE_CONNCOOKIELULZ


def _handshake_sync(ip: str, port: int, timeout: float) -> list:
    """Walk the 0.3.7 handshake with a raw socket, recording every exchange.

    Returns a list of (label, sent_plaintext_bytes, received_bytes_or_None).
    Outgoing packets are samp-encoded exactly like the client does; a connected
    UDP socket keeps only the target's replies.
    """
    from .sampnetencr import samp_encode

    resolved = socket.gethostbyname(ip)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    sock.connect((resolved, port))
    steps = []

    def exchange(payload: bytes, label: str):
        sock.send(samp_encode(payload, port))
        try:
            data = sock.recv(4096)
        except (socket.timeout, TimeoutError):
            data = None
        steps.append((label, payload, data))
        return data

    try:
        request = bytes([ID_OPEN_CONNECTION_REQUEST, 0x00, 0x00])
        reply = exchange(request, "open connection request")
        if reply is None:
            # some anti-DDoS frontends drop the first packet; retry once
            reply = exchange(request, "open connection request (retry)")
        if reply and reply[0] == ID_OPEN_CONNECTION_COOKIE and len(reply) >= 3:
            cookie = struct.unpack("<H", reply[1:3])[0]
            answer = bytes([ID_OPEN_CONNECTION_REQUEST]) + struct.pack("<H", cookie ^ COOKIE_XOR)
            reply = exchange(answer, "cookie answer (xor 0x6969)")
            if reply is None or reply[0] == ID_OPEN_CONNECTION_COOKIE:
                # no answer, or the server re-challenged: retry the answer once
                reply = exchange(answer, "cookie answer (retry)")
        return steps
    finally:
        sock.close()


async def diag(ip: str, port: int, timeout: float = 2.5) -> dict:
    """Full in-bot diagnosis of one server: query + raw 0.3.7 handshake.

    Distinguishes: server silent (IP filtered / offline), query-only answering
    (play connection filtered), cookie challenge refused, handshake accepted.
    """
    loop = asyncio.get_running_loop()
    out = {"ip": ip, "port": port, "resolved": None, "resolve_error": None,
           "info": None, "query_error": None, "steps": [], "handshake_error": None}
    try:
        out["resolved"] = socket.gethostbyname(ip)
    except OSError as e:
        out["resolve_error"] = str(e)
        return out
    try:
        out["info"] = await query_server(out["resolved"], port, timeout)
    except Exception as e:
        out["query_error"] = f"{type(e).__name__}: {e}"
    try:
        out["steps"] = await loop.run_in_executor(
            None, _handshake_sync, out["resolved"], port, timeout)
    except Exception as e:
        out["handshake_error"] = f"{type(e).__name__}: {e}"
    return out


# Ports SA-MP/CRMP servers commonly listen on. 7777 is the stock default, but plenty
# of projects move it (5125 among them), and a wrong port looks exactly like an IP
# block: every packet goes unanswered. Probing these turns that guess into a fact.
COMMON_SAMP_PORTS = (
    7777, 5125, 7778, 7779, 7776, 7780, 1337,
    5000, 5555, 6666, 7000, 8000, 9000, 22005,
)


async def findport(ip: str, ports: tuple[int, ...] | None = None,
                   timeout: float = 2.0) -> dict:
    """Find which UDP port on a host actually answers the SA-MP query.

    For every port that answers, also walk the 0.3.7 handshake so the result says
    whether it is a joinable game server and not just something holding the port.
    Read-only.
    """
    loop = asyncio.get_running_loop()
    out: dict = {"ip": ip, "resolved": None, "resolve_error": None, "results": []}
    try:
        out["resolved"] = socket.gethostbyname(ip)
    except OSError as e:
        out["resolve_error"] = str(e)
        return out
    resolved = out["resolved"]
    candidates = ports or COMMON_SAMP_PORTS

    async def probe(p: int) -> dict:
        entry = {"port": p, "info": None, "accepted": False, "steps": []}
        try:
            entry["info"] = await query_server(resolved, p, timeout)
        except Exception:
            return entry
        try:
            entry["steps"] = await loop.run_in_executor(
                None, _handshake_sync, resolved, p, timeout)
            entry["accepted"] = any(g and g[0] == 25 for _, _, g in entry["steps"])
        except Exception:
            pass
        return entry

    out["results"] = list(await asyncio.gather(*(probe(p) for p in candidates)))
    out["answering"] = [r for r in out["results"] if r["info"] is not None]
    out["joinable"] = [r for r in out["results"] if r["accepted"]]
    return out


async def selftest(timeout: float = 3.0) -> dict:
    """Verify the 0.3.7 handshake against a LIVE public server, not a mock.

    A target that stays silent cannot tell us whether our client or the target is
    at fault. This walks the real cookie exchange against reference servers until
    one answers, so "our encoding is wrong" can be ruled out on live traffic.
    Read-only: it never touches the running instance or its config.
    """
    tried: list[dict] = []
    for host, port in REFERENCE_SERVERS:
        entry: dict = {"host": host, "port": port, "info": None,
                       "query_error": None, "steps": [], "accepted": False}
        try:
            entry["info"] = await query_server(host, port, timeout)
        except Exception as e:
            entry["query_error"] = f"{type(e).__name__}: {e}"
            tried.append(entry)
            continue  # silent server proves nothing, try the next one
        loop = asyncio.get_running_loop()
        try:
            entry["steps"] = await loop.run_in_executor(
                None, _handshake_sync, host, port, timeout)
        except Exception as e:
            entry["query_error"] = f"{type(e).__name__}: {e}"
        entry["accepted"] = any(
            g and g[0] == 25 for _, _, g in entry["steps"])  # ID_OPEN_CONNECTION_REPLY
        tried.append(entry)
        if entry["accepted"]:
            break
    return {
        "tried": tried,
        "verified": any(t["accepted"] for t in tried),
        "reachable": [t for t in tried if t["info"] is not None],
    }


async def nettest(ip: str, port: int, timeout: float = 3.0) -> dict:
    """Probe DNS resolvers + SA-MP reference servers + the target.

    DNS answers but SA-MP silent -> UDP works, the game servers block this IP (or
    are down). DNS also silent -> the UDP return path is dropped on the host.
    """
    loop = asyncio.get_running_loop()

    async def probe(host: str, p: int) -> bool:
        try:
            await query_server(host, p, timeout)
            return True
        except Exception:
            return False

    async def dns(server: str) -> bool:
        return await loop.run_in_executor(None, _dns_query_sync, server, timeout)

    async def ntp(server: str) -> bool:
        return await loop.run_in_executor(None, _ntp_query_sync, server, timeout)

    async def stun(host: str, p: int) -> str | None:
        return await loop.run_in_executor(None, _stun_query_sync, host, p, timeout)

    refs, dns_res, ntp_res, stun_res = await asyncio.gather(
        asyncio.gather(*(probe(h, p) for h, p in REFERENCE_SERVERS)),
        asyncio.gather(*(dns(s) for s in DNS_RESOLVERS)),
        asyncio.gather(*(ntp(s) for s in NTP_SERVERS)),
        asyncio.gather(*(stun(h, p) for h, p in STUN_SERVERS)),
    )
    udp_ok = any(refs)
    dns_ok = any(dns_res)
    ntp_ok = any(ntp_res)
    egress_ip = next((r for r in stun_res if r), None)
    high_port_ok = egress_ip is not None
    info = None
    try:
        info = await query_server(ip, port, timeout)
        target_ok = True
    except Exception:
        target_ok = False
    return {
        "udp_ok": udp_ok,
        "dns_ok": dns_ok,
        "ntp_ok": ntp_ok,
        "high_port_ok": high_port_ok,
        "egress_ip": egress_ip,
        "dns": list(zip(DNS_RESOLVERS, dns_res)),
        "ntp": list(zip(NTP_SERVERS, ntp_res)),
        "stun": list(zip(STUN_SERVERS, stun_res)),
        "refs": list(zip(REFERENCE_SERVERS, refs)),
        "target_ok": target_ok,
        "info": info,
    }
