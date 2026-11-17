"""Read bounded public HTML references without executing scripts or calling an AI."""
from __future__ import annotations

import asyncio
from html.parser import HTMLParser
from http.client import HTTPConnection, HTTPException
from ipaddress import ip_address, ip_network
import re
import socket
import ssl
from threading import Timer
from time import monotonic
from urllib.parse import quote, urljoin, urlsplit

MAX_BYTES = 2 * 1024 * 1024
TOTAL_SECONDS = 15
MAX_REDIRECTS = 3
# Python 3.12 classifies some special-purpose ranges more broadly than later releases.
SPECIAL_NETWORKS = tuple(ip_network(value) for value in (
    "192.0.0.0/24", "64:ff9b::/96", "64:ff9b:1::/48", "2001::/23", "2002::/16", "3fff::/20",
))


class ReferenceReadError(ValueError):
    pass


def _url_parts(url: str):
    try:
        parts = urlsplit(url)
        port = parts.port or (443 if parts.scheme == "https" else 80)
        if (parts.scheme not in {"http", "https"} or not parts.hostname
                or parts.username is not None or parts.password is not None
                or port not in {80, 443} or len(url) > 4000
                or re.search(r"[\x00-\x20\x7f\\]", url)
                or "%" in parts.hostname):
            raise ValueError()
        host = parts.hostname.encode("idna").decode("ascii")
    except (ValueError, UnicodeError):
        raise ReferenceReadError("请使用公开网页的 HTTP 或 HTTPS 链接。") from None
    return parts, host, port


def _public(address: str) -> bool:
    value = ip_address(address)
    if not value.is_global or value.is_multicast or value.is_reserved:
        return False
    if any(value.version == network.version and value in network for network in SPECIAL_NETWORKS):
        return False
    if getattr(value, "ipv4_mapped", None):
        return _public(str(value.ipv4_mapped))
    if getattr(value, "sixtofour", None):
        return _public(str(value.sixtofour))
    if getattr(value, "teredo", None):
        return False
    return True


class _PinnedConnection(HTTPConnection):
    """Resolve once; connect only to that checked sockaddr, retaining Host and SNI."""

    def __init__(self, host, port, address, secure, timeout):
        super().__init__(host, port, timeout=timeout)
        self.address = address
        self.secure = secure
        self.transport_socket = None

    def connect(self):
        family, kind, protocol, _, sockaddr = self.address
        raw = socket.socket(family, kind, protocol)
        self.transport_socket = raw
        raw.settimeout(self.timeout)
        try:
            raw.connect(sockaddr)
            if self.secure:
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                context.load_default_certs()
                context.set_alpn_protocols(["http/1.1"])
                raw = context.wrap_socket(raw, server_hostname=self.host)
                self.transport_socket = raw
            self.sock = raw
        except Exception:
            raw.close()
            raise

    def abort(self):
        if self.transport_socket is not None:
            try:
                self.transport_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.transport_socket.close()


def _exchange(parts, host, port, address, deadline):
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise TimeoutError()
    connection = _PinnedConnection(host, port, address, parts.scheme == "https", min(8, remaining))
    watchdog = Timer(remaining, connection.abort)
    watchdog.daemon = True
    watchdog.start()
    try:
        target = quote(parts.path or "/", safe="/%:@!$&'()*+,;=-._~")
        if parts.query:
            target += "?" + quote(parts.query, safe="=&?/%:@!$'()*+,;~-._")
        connection.request("GET", target, headers={
            "User-Agent": "CreateJunior/0.1 ReferenceReader",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Encoding": "identity",
            "Connection": "close",
        })
        response = connection.getresponse()
        if response.status in {301, 302, 303, 307, 308}:
            location = response.getheader("Location")
            if not location:
                raise ReferenceReadError("网页跳转地址缺失，请补充图片或文字。")
            return location, None
        if not 200 <= response.status < 300:
            raise ReferenceReadError(f"网页返回 {response.status}，可重试或补充图片。")
        if response.headers.get_content_type() not in {"text/html", "application/xhtml+xml"}:
            raise ReferenceReadError("这个链接不是网页；图纸请用上传 PDF。")
        if response.getheader("Content-Encoding", "identity").lower() not in {"identity", ""}:
            raise ReferenceReadError("网页采用了暂不支持的传输格式，请补充图片或文字。")
        length = response.getheader("Content-Length", "")
        if length.isdigit() and int(length) > MAX_BYTES:
            raise ReferenceReadError("网页超过 2 MB，请补充相关图片或文字。")
        chunks, size = [], 0
        while True:
            if monotonic() >= deadline:
                raise TimeoutError()
            chunk = response.read1(min(65536, MAX_BYTES + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_BYTES:
                raise ReferenceReadError("网页超过 2 MB，请补充相关图片或文字。")
        raw = b"".join(chunks)
        charset = response.headers.get_content_charset()
        if not charset:
            declaration = re.search(br'charset\s*=\s*["\']?([a-zA-Z0-9_-]+)', raw[:4096])
            charset = declaration.group(1).decode("ascii") if declaration else "utf-8"
        try:
            return None, raw.decode(charset, errors="replace")
        except LookupError:
            return None, raw.decode("utf-8", errors="replace")
    finally:
        watchdog.cancel()
        connection.abort()
        connection.close()


class _TextPage(HTMLParser):
    ignored = {"script", "style", "noscript", "svg", "template", "head", "nav", "header", "footer", "form"}
    void = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.title = []
        self.body = []
        self.main = []
        self.description = ""
        self.og_title = ""

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta":
            key = (attrs.get("property") or attrs.get("name") or "").lower()
            if key == "og:title":
                self.og_title = attrs.get("content") or ""
            if key in {"og:description", "description"} and not self.description:
                self.description = attrs.get("content") or ""
        hidden = bool(self.stack and self.stack[-1][1]) or tag in self.ignored
        hidden = hidden or "hidden" in attrs or attrs.get("aria-hidden") == "true"
        hidden = hidden or bool(re.search(r"display\s*:\s*none|visibility\s*:\s*hidden", attrs.get("style") or "", re.I))
        main = bool(self.stack and self.stack[-1][2]) or tag in {"main", "article"} or attrs.get("role") == "main"
        if tag not in self.void:
            self.stack.append((tag, hidden, main))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        if any(item[0] == "title" for item in self.stack):
            self.title.append(data)
        if self.stack and self.stack[-1][1]:
            return
        text = " ".join(data.split())
        if text:
            self.body.append(text)
            if self.stack and self.stack[-1][2]:
                self.main.append(text)

    def result(self, host):
        title = " ".join((self.og_title or " ".join(self.title) or host).split())[:160]
        main = " ".join(self.main)
        text = main if len(main) > 80 else " ".join(self.body)
        if self.description and self.description not in text:
            text = self.description + "\n" + text
        text = text.strip()
        if len(text) < 20:
            raise ReferenceReadError("网页没有可读取的正文，请补充图片或文字。")
        return {"name": title, "text": title + "\n\n" + text[:7600] + ("…" if len(text) > 7600 else "")}


async def read_reference_link(url: str) -> dict[str, str]:
    deadline = monotonic() + TOTAL_SECONDS
    try:
        async with asyncio.timeout(TOTAL_SECONDS):
            current = url
            for hop in range(MAX_REDIRECTS + 1):
                parts, host, port = _url_parts(current)
                addresses = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
                if not addresses or not all(_public(entry[4][0]) for entry in addresses):
                    raise ReferenceReadError("只能读取公开互联网网页。")
                addresses.sort(key=lambda item: item[0] != socket.AF_INET)
                redirect, html = await asyncio.to_thread(_exchange, parts, host, port, addresses[0], deadline)
                if redirect:
                    if hop == MAX_REDIRECTS:
                        raise ReferenceReadError("网页跳转过多，请使用产品页的最终链接。")
                    current = urljoin(current, redirect)
                    continue
                parser = _TextPage()
                parser.feed(html)
                return parser.result(host)
    except ReferenceReadError:
        raise
    except TimeoutError:
        raise ReferenceReadError("网页读取超时，可以重试或补充图片。") from None
    except (OSError, HTTPException, UnicodeError, ValueError):
        raise ReferenceReadError("暂时无法读取这个网页，可以重试或补充图片。") from None
    raise ReferenceReadError("未能读取网页正文。")
