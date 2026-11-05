#!/usr/bin/env python3
"""Legge pagine web con un Chrome vero (non headless) e un profilo dedicato.

Serve per i siti che bloccano i lettori automatici semplici (es. Trovaprezzi).
Chrome viene comandato con il protocollo DevTools via WebSocket, scritto qui con
la sola libreria standard: nessuna dipendenza.

Il profilo dedicato è necessario perché da Chrome 136 il debug remoto non è
permesso sul profilo principale. La prima volta va aperto a mano per accettare
i cookie dei siti:  python3 browser.py --setup
"""
import base64
import json
import os
import platform
import shutil
import socket
import struct
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

PORT = 9223  # porta locale del debug remoto (solo 127.0.0.1)

# Senza proxy: le chiamate vanno solo a Chrome su questo PC.
_local = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def profile_dir(command=None):
    if command and Path(command[0]).name == "flatpak":
        # Chrome in Flatpak vede solo la sua cartella in ~/.var/app: un profilo altrove
        # finirebbe in una cartella temporanea della sandbox e si perderebbe a ogni avvio.
        app_id = next((a for a in command[2:] if not a.startswith("-")), "com.google.Chrome")
        return Path.home() / ".var" / "app" / app_id / "data" / "price-tracker" / "chrome-profile"
    if platform.system() == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "price-tracker" / "chrome-profile"


def find_chrome(setting="auto"):
    """Restituisce il comando di Chrome come lista, oppure None se non lo trova.

    setting: "auto" per cercarlo, altrimenti un percorso o un comando
    (anche con argomenti, es. "flatpak run com.google.Chrome").
    """
    if setting and setting not in ("auto", "on", "1", "yes"):
        return setting.split()
    for name in ("google-chrome-stable", "google-chrome", "chromium-browser", "chromium", "chrome"):
        path = shutil.which(name)
        if path:
            return [path]
    for path in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                 r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                 str(Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe")):
        if Path(path).exists():
            return [path]
    if shutil.which("flatpak"):
        r = subprocess.run(["flatpak", "info", "com.google.Chrome"], capture_output=True)
        if r.returncode == 0:
            return ["flatpak", "run", "com.google.Chrome"]
    return None


def _http(path, method="GET"):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", method=method)
    with _local.open(req, timeout=5) as r:
        return json.loads(r.read().decode())


class WebSocket:
    """Client WebSocket minimo (RFC 6455): testo, frammentazione, ping/pong."""

    def __init__(self, url, timeout=60):
        u = urllib.parse.urlparse(url)
        self.sock = socket.create_connection((u.hostname, u.port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET {u.path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\n"
                           "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                           f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("WebSocket: connessione chiusa durante l'handshake")
            data += chunk
        head, _, self.buf = data.partition(b"\r\n\r\n")
        if b" 101 " not in head.split(b"\r\n")[0]:
            raise ConnectionError("WebSocket rifiutato: " + head.split(b"\r\n")[0].decode(errors="ignore"))

    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(max(65536, n - len(self.buf)))
            if not chunk:
                raise ConnectionError("WebSocket chiuso")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def _send_frame(self, opcode, payload):
        n = len(payload)
        head = bytes([0x80 | opcode])
        if n < 126:
            head += bytes([0x80 | n])
        elif n < 65536:
            head += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            head += bytes([0x80 | 127]) + struct.pack(">Q", n)
        mask = os.urandom(4)  # i client devono mascherare
        self.sock.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def send(self, text):
        self._send_frame(0x1, text.encode())

    def recv(self):
        parts = []
        while True:
            b1, b2 = self._read(2)
            fin, opcode, n = b1 & 0x80, b1 & 0x0F, b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            mask = self._read(4) if b2 & 0x80 else None
            payload = self._read(n)
            if mask:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if opcode == 0x8:
                raise ConnectionError("WebSocket chiuso da Chrome")
            if opcode == 0x9:
                self._send_frame(0xA, payload)
                continue
            if opcode in (0x1, 0x2, 0x0):
                parts.append(payload)
                if fin:
                    return b"".join(parts).decode("utf-8", errors="replace")

    def close(self):
        try:
            self._send_frame(0x8, b"")
        except OSError:
            pass
        self.sock.close()


class Tab:
    """Una scheda di Chrome comandata via DevTools."""

    def __init__(self, ws_url):
        self.ws = WebSocket(ws_url)
        self.next_id = 0

    def call(self, method, **params):
        self.next_id += 1
        my_id = self.next_id
        self.ws.send(json.dumps({"id": my_id, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == my_id:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error'].get('message')}")
                return msg.get("result", {})

    def eval(self, expression):
        r = self.call("Runtime.evaluate", expression=expression, returnByValue=True)
        return r.get("result", {}).get("value")

    def goto(self, url, timeout=45, settle=4):
        """Apre l'URL e aspetta che la pagina abbia finito di caricare."""
        self.call("Page.navigate", url=url)
        time.sleep(1)
        end = time.time() + timeout
        while time.time() < end:
            if self.eval("document.readyState") == "complete":
                break
            time.sleep(0.5)
        time.sleep(settle)  # tempo per i contenuti caricati dopo (prezzi, banner)

    def html(self):
        return self.eval("document.documentElement.outerHTML") or ""


class Chrome:
    """Avvia Chrome con il profilo dedicato (o si collega se è già aperto) e lo chiude alla fine."""

    def __init__(self, command, url="about:blank"):
        self.proc, self.tab_id = None, None
        try:
            _http("/json/version")  # già in esecuzione (es. da un giro precedente interrotto)
        except OSError:
            profile = profile_dir(command)
            profile.mkdir(parents=True, exist_ok=True)
            self.proc = subprocess.Popen(
                command + [f"--remote-debugging-port={PORT}", "--remote-debugging-address=127.0.0.1",
                           f"--user-data-dir={profile}", "--no-first-run",
                           "--no-default-browser-check", "--new-window", url],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(60):
                time.sleep(0.5)
                if self.proc.poll() is not None:
                    raise RuntimeError("Chrome si è chiuso subito (c'è un desktop attivo?)")
                try:
                    _http("/json/version")
                    break
                except OSError:
                    continue
            else:
                raise RuntimeError("Chrome non risponde sulla porta di debug")

    def new_tab(self):
        t = _http("/json/new?about:blank", method="PUT")
        self.tab_id = t["id"]
        return Tab(t["webSocketDebuggerUrl"])

    def close(self):
        if self.proc is None:
            if self.tab_id:  # Chrome non l'abbiamo aperto noi: chiudiamo solo la nostra scheda
                try:
                    _http(f"/json/close/{self.tab_id}")
                except OSError:
                    pass
            return
        try:
            ws = WebSocket(_http("/json/version")["webSocketDebuggerUrl"], timeout=5)
            ws.send(json.dumps({"id": 1, "method": "Browser.close"}))
            ws.close()
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.terminate()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def setup(command):
    """Apre il profilo dedicato su Trovaprezzi: accetta i cookie, poi chiudi la finestra."""
    profile = profile_dir(command)
    profile.mkdir(parents=True, exist_ok=True)
    print(f"Profilo Chrome del tracker: {profile}")
    print("Si apre Chrome su Trovaprezzi: accetta i cookie, risolvi l'eventuale verifica,")
    print("guarda pure qualche pagina, poi chiudi la finestra.")
    subprocess.run(command + [f"--user-data-dir={profile}", "--no-first-run",
                              "--no-default-browser-check", "--new-window", "https://www.trovaprezzi.it/"])
    print("Fatto.")


if __name__ == "__main__":
    cmd = find_chrome(os.environ.get("TRACKER_CHROME", "auto"))
    if not cmd:
        sys.exit("Chrome non trovato: installalo o indica il comando in TRACKER_CHROME.")
    if "--setup" in sys.argv:
        setup(cmd)
    else:
        print("Chrome:", " ".join(cmd))
        print("Uso: python3 browser.py --setup")
