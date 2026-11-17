"""Read-only UniFi Access exporter. Python standard library; no HA Core access."""
import csv
import hashlib
import html
import io
import json
import logging
import ntpath
import os
from pathlib import Path
import re
import signal
import ssl
import tempfile
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener

LOG = logging.getLogger("badge-export")
HEADERS = ["UserID", "FirstName", "LastName", "FullName", "ID", "PhotoPath"]


class ExportError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".badge-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class Client:
    def __init__(self, options):
        raw = options.get("console_url", "").strip().rstrip("/")
        if not raw or not options.get("api_token", "").strip():
            raise ExportError("Set console_url and api_token in the add-on configuration, then restart.")
        if "://" not in raw:
            raw = "https://" + raw
        parsed = urlsplit(raw)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
            raise ExportError("console_url must be an HTTPS console address without a path or credentials.")
        try:
            port = parsed.port or 12445
        except ValueError:
            raise ExportError("Invalid API port.") from None
        host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
        self.base = f"https://{host}:{port}"
        self.token = options["api_token"].strip()
        context = ssl.create_default_context()
        if not options.get("verify_ssl", True):
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        self.opener = build_opener(ProxyHandler({}), HTTPSHandler(context=context), NoRedirect())

    def get(self, path, binary=False):
        if not path.startswith("/api/v1/developer/"):
            raise ExportError("Refused a request outside the Access developer API.")
        req = Request(self.base + path, headers={
            "Authorization": "Bearer " + self.token,
            "Accept": "image/*" if binary else "application/json",
        })
        try:
            with self.opener.open(req, timeout=30) as response:
                maximum = 10 * 1024 * 1024
                data = response.read(maximum + 1)
                if len(data) > maximum:
                    raise ExportError("API response exceeds 10 MiB.")
        except HTTPError as ex:
            hints = {401: "API token rejected or expired.",
                     403: "API token lacks permission (view:user; photos also require view:system_log)."}
            raise ExportError(hints.get(ex.code, f"Access API returned HTTP {ex.code}.")) from None
        except (URLError, TimeoutError, OSError):
            raise ExportError("Cannot reach the Access API. Check the console address, API port, network and SSL setting.") from None
        if binary:
            return data
        try:
            payload = json.loads(data)
        except (ValueError, UnicodeError):
            raise ExportError("API returned invalid JSON.") from None
        if not isinstance(payload, dict) or payload.get("code") != "SUCCESS":
            raise ExportError("Access API did not return SUCCESS.")
        return payload

    def users(self):
        users, seen, expected = [], set(), None
        for page in range(1, 10001):
            payload = self.get("/api/v1/developer/users?" + urlencode({"page_num": page, "page_size": 100}))
            records = payload.get("data")
            if not isinstance(records, list):
                raise ExportError("Unexpected users response: data must be a list.")
            pagination = payload.get("pagination")
            if not isinstance(pagination, dict) or "total" not in pagination:
                raise ExportError("Users response is missing pagination.total; previous CSV retained.")
            try:
                total = int(pagination["total"])
                returned_page = int(pagination.get("page_num", page))
            except (ValueError, TypeError):
                raise ExportError("Invalid API pagination.") from None
            if total < 0 or returned_page != page or (expected is not None and total != expected):
                raise ExportError("User list changed during paging or pagination is inconsistent; retry next sync.")
            expected = total
            for user in records:
                if not isinstance(user, dict) or not isinstance(user.get("id"), str) or not user["id"]:
                    raise ExportError("User response contains a missing or invalid user ID.")
                if user["id"] in seen:
                    raise ExportError("API returned repeated users; previous CSV retained.")
                seen.add(user["id"])
                users.append(user)
            if len(users) == total:
                return users
            if not records or len(users) > total:
                raise ExportError("Incomplete or inconsistent user list; previous CSV retained.")
        raise ExportError("API pagination limit exceeded.")


def text(user, field):
    value = user.get(field)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ExportError(f"Unexpected non-text {field}; previous CSV retained.")
    if "\x00" in value:
        raise ExportError("User field contains a NUL character.")
    return value


def photo_path(client, user, folder, windows_folder):
    raw = user.get("avatar_relative_path") or user.get("user_avatar") or ""
    if not isinstance(raw, str) or not raw:
        return ""
    # Only use a path identifier. Never send bearer tokens to a returned URL.
    match = re.search(r"/avatar/([A-Za-z0-9._-]+)$", urlsplit(raw).path)
    if not match or match.group(1) in (".", ".."):
        raise ExportError("Unrecognized avatar path.")
    data = client.get("/api/v1/developer/system/static/avatar/" + match.group(1), binary=True)
    if data.startswith(b"\xff\xd8\xff"):
        ext = ".jpg"
    elif data.startswith(b"\x89PNG\r\n\x1a\n"):
        ext = ".png"
    else:
        raise ExportError("Avatar response is not JPEG or PNG.")
    name = hashlib.sha256((user["id"]).encode()).hexdigest()[:20] + "-" + hashlib.sha256(data).hexdigest()[:16] + ext
    target = folder / "photos" / name
    if not target.exists():
        atomic_write(target, data)
    return ntpath.join(windows_folder, name)


def export(options, client, share_root=Path("/share")):
    sub = options.get("output_folder", "unifi-badges")
    if not isinstance(sub, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", sub):
        raise ExportError("output_folder must be a simple folder name (letters, digits, hyphens or underscores).")
    folder = share_root / sub
    # Refuse symlink targets that could move the output outside the shared directory.
    if folder.is_symlink() or (folder / "photos").is_symlink():
        raise ExportError("Output folders cannot be symbolic links.")
    users = client.users()
    active = [u for u in users if u.get("status") == "ACTIVE"]
    if not active and not options.get("allow_empty_export", False):
        raise ExportError("No active users returned; previous CSV retained. Enable allow_empty_export only if intentional.")
    photos = options.get("export_photos", False)
    windows_folder = options.get("windows_photo_folder", "").strip()
    if photos and not (ntpath.isabs(windows_folder) and (windows_folder.startswith("\\\\") or ntpath.splitdrive(windows_folder)[0])):
        raise ExportError("Set windows_photo_folder to the Windows UNC or drive path of the exported photos folder.")
    previous = {}
    try:
        with (folder / "employees.csv").open(encoding="utf-8-sig", newline="") as stream:
            previous = {r["UserID"]: r.get("PhotoPath", "") for r in csv.DictReader(stream)}
    except (OSError, KeyError, csv.Error, UnicodeError):
        pass
    rows, warnings = [], []
    for user in active:
        first, last, number = (text(user, key) for key in ("first_name", "last_name", "employee_number"))
        photo = ""
        if photos:
            try:
                photo = photo_path(client, user, folder, windows_folder)
            except ExportError:
                warnings.append("A photo could not be refreshed.")
                old = previous.get(user["id"], "")
                if (ntpath.dirname(old).rstrip("\\/").casefold() == windows_folder.rstrip("\\/").casefold()
                        and re.fullmatch(r"[0-9a-f]{20}-[0-9a-f]{16}\.(jpg|png)", ntpath.basename(old))
                        and (folder / "photos" / ntpath.basename(old)).is_file()):
                    photo = old
        rows.append([user["id"], first, last, " ".join(p for p in (first, last) if p), number, photo])
    rows.sort(key=lambda row: (row[2].casefold(), row[1].casefold(), row[0]))
    missing = sum(not row[4] for row in rows)
    if missing:
        warnings.append(f"{missing} active users have no employee number; ID is blank for them.")
    numbers = [row[4] for row in rows if row[4]]
    duplicates = len(numbers) - len(set(numbers))
    if duplicates:
        warnings.append(f"{duplicates} duplicate employee numbers; use UserID as the record key.")
    output = io.StringIO(newline="")
    writer = csv.writer(output, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    writer.writerow(HEADERS)
    writer.writerows(rows)
    schema = ("[employees.csv]\r\nColNameHeader=True\r\nFormat=CSVDelimited\r\n"
              "CharacterSet=65001\r\nMaxScanRows=0\r\n" +
              "".join(f"Col{i}={name} Text Width 2048\r\n" for i, name in enumerate(HEADERS, 1)))
    # Microsoft Text providers honor this sidecar; other CSV readers can ignore it.
    atomic_write(folder / "schema.ini", schema.encode("ascii"))
    atomic_write(folder / "employees.csv", output.getvalue().encode("utf-8-sig"))
    return {"active_users": len(rows), "total_users": len(users), "warnings": warnings,
            "csv_path": str(folder / "employees.csv")}


class Service:
    def __init__(self, options):
        self.options = options
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.stop = threading.Event()
        self.state = {"running": False, "last_success": None, "error": None}
        try:
            saved = json.loads(Path("/data/last-success.json").read_text())
            if isinstance(saved, dict):
                self.state.update(saved)
        except (OSError, ValueError):
            pass

    def status(self):
        with self.lock:
            return dict(self.state)

    def run(self):
        while not self.stop.is_set():
            self.wake.clear()
            with self.lock:
                self.state.update(running=True, error=None)
            try:
                result = export(self.options, Client(self.options))
                result.update(last_success=datetime.now(timezone.utc).isoformat(), running=False, error=None)
                with self.lock:
                    self.state.update(result)
                try:
                    atomic_write("/data/last-success.json", json.dumps(result).encode())
                except OSError:
                    LOG.warning("CSV saved, but could not persist status.")
                LOG.info("Exported %s active users; %s warnings.", result["active_users"], len(result["warnings"]))
            except Exception as ex:
                error = str(ex) if isinstance(ex, ExportError) else "Sync failed; previous CSV retained. Check writable shared folder and configuration."
                with self.lock:
                    self.state.update(running=False, error=error)
                LOG.error("%s", error)
            self.wake.wait(int(self.options.get("sync_interval_seconds", 300)))


def handler_for(service):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def allowed(self):
            if self.client_address[0] != "172.30.32.2":
                self.send_error(403, "Use Home Assistant ingress.")
                return False
            return True

        def reply(self, body, kind="text/html; charset=utf-8", code=200):
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'self'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self.allowed():
                return
            path = urlsplit(self.path).path
            if path == "/status":
                return self.reply(json.dumps(service.status()).encode(), "application/json")
            if path == "/download":
                sub = service.options.get("output_folder", "unifi-badges")
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", sub):
                    return self.send_error(400)
                try:
                    data = (Path("/share") / sub / "employees.csv").read_bytes()
                except OSError:
                    return self.send_error(404, "No successful export yet.")
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="employees.csv"')
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return self.wfile.write(data)
            if path != "/":
                return self.send_error(404)
            state = service.status()
            details = html.escape(json.dumps(state, indent=2))
            body = f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>UniFi Badge Export</title>
<style>body{{font:16px system-ui;max-width:820px;margin:40px auto;padding:20px;background:#f5f7fa;color:#182538}}button,a{{display:inline-block;padding:12px;margin-right:12px}}pre{{white-space:pre-wrap;background:white;padding:24px;border-radius:12px}}</style></head>
<body><h1>UniFi Badge Export</h1><p>Active UniFi Access users for CardExchange.</p>
<form method="post" action="sync"><button>Sync now</button><a href="./">Refresh status</a><a href="download">Download CSV</a></form>
<pre>{details}</pre><p>Configuration changes take effect after restarting the add-on. All sync times are UTC.</p></body></html>'''
            self.reply(body.encode())

        def do_POST(self):
            if not self.allowed():
                return
            if urlsplit(self.path).path != "/sync":
                return self.send_error(404)
            # Ingress requests are authenticated by Supervisor; forms cannot change configuration.
            service.wake.set()
            self.send_response(303)
            self.send_header("Location", "./")
            self.send_header("Content-Length", "0")
            self.end_headers()
    return Handler


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    options = json.loads(Path("/data/options.json").read_text())
    service = Service(options)
    server = ThreadingHTTPServer(("0.0.0.0", 8099), handler_for(service))
    worker = threading.Thread(target=service.run, daemon=True)
    worker.start()

    def shutdown(*_):
        service.stop.set()
        service.wake.set()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        worker.join(timeout=3)


if __name__ == "__main__":
    main()
