import json
import re
import struct
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import jsonschema
import xxhash

ROOT = Path(__file__).resolve().parent.parent
USER_AGENT = "cb-mods-index/1 (+https://github.com/CBServers/mods-index)"
CONTENT_FOLDERS = ("mods", "usermaps")
ENTRY_FILE = "entry.json"
MAX_IMAGE_BYTES = 8 * 1024 * 1024
HASH_COMMIT_SUBJECT = "fill hashes"
RESERVED_NAMES = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
INVALID_PATH_CHARS = set('<>:"|?*\\')
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class DownloadError(Exception):
    pass


class Entry:
    def __init__(self, game, entry_id, data, folder=None):
        self.game = game
        self.id = entry_id
        self.data = data
        self.folder = folder
        self.where = f"items/{game}/{entry_id}"
        self.source = f"{self.where}/{ENTRY_FILE}"

    @property
    def files(self):
        files = self.data.get("files") if isinstance(self.data, dict) else None
        return files if isinstance(files, list) else []

    @property
    def images(self):
        images = self.data.get("images") if isinstance(self.data, dict) else None
        return images if isinstance(images, list) else []


class Report:
    def __init__(self):
        self.errors = []
        self.warnings = []

    def error(self, where, message):
        self.errors.append((where, message))

    def warn(self, where, message):
        self.warnings.append((where, message))


def load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def load_config(root=ROOT):
    return load_json(root / "games.json"), load_json(root / "hosts.json"), load_json(root / "schema" / "entry.schema.json")


def format_hash(hasher):
    # Little-endian bytes in uppercase hex, the launcher's utils::hash format.
    return hasher.digest()[::-1].hex().upper()


def hash_bytes(data):
    return format_hash(xxhash.xxh3_64(data))


def file_root(game_config, file):
    return file.get("root", game_config["defaultRoot"])


def file_key(game_config, file):
    return f"{file_root(game_config, file)}:{str(file.get('path', '')).lower()}"


def same_source(a, b):
    return a.get("url") == b.get("url") and a.get("parts") == b.get("parts") and a.get("size") == b.get("size")


def file_urls(file):
    return [file["url"]] if "url" in file else list(file.get("parts") or [])


def path_error(path):
    if path.startswith("/"):
        return "must be relative"
    for segment in path.split("/"):
        if segment in ("", ".", ".."):
            return 'has an empty, "." or ".." segment'
        if any(char in INVALID_PATH_CHARS or ord(char) < 32 for char in segment):
            return f'"{segment}" has a character Windows paths cannot hold (use forward slashes between folders)'
        if segment[-1] in " .":
            return f'"{segment}" ends with a dot or a space'
        if segment.split(".")[0].lower() in RESERVED_NAMES:
            return f'"{segment}" is a reserved Windows name'
    return None


def url_error(url, game, entry_id, hosts):
    if url.startswith("cdn:"):
        prefix = f"cdn:mods/{game}/{entry_id}/"
        if not url.startswith(prefix) or len(url) == len(prefix):
            return f"CDN links must start with {prefix}"
        return path_error(url[len("cdn:"):])
    if any(re.match(source["pattern"], url) for source in hosts["sources"]):
        return None
    return f"{url} is not on an allowed host (see hosts.json)"


def resolve_candidates(url, hosts):
    if url.startswith("cdn:"):
        return [base + urllib.parse.quote(url[len("cdn:"):]) for base in hosts["cdn"]]
    return [url]


def image_size(data):
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        width, height = struct.unpack(">II", data[16:24])
        return "png", width, height
    if data[:2] == b"\xff\xd8":
        index = 2
        while index + 9 < len(data):
            if data[index] != 0xFF:
                index += 1
                continue
            marker = data[index + 1]
            index += 2
            if marker == 0xFF or marker == 0x01 or 0xD0 <= marker <= 0xD9:
                continue
            length = struct.unpack(">H", data[index:index + 2])[0]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                height, width = struct.unpack(">HH", data[index + 3:index + 7])
                return "jpeg", width, height
            index += length
    return None


def image_error(path):
    data = path.read_bytes()
    if len(data) > MAX_IMAGE_BYTES:
        return "is larger than 8 MB"
    size = image_size(data)
    if not size:
        return "is not a PNG or JPEG image"
    kind, width, height = size
    if (kind == "png") != (path.suffix.lower() == ".png"):
        return f"is a {kind.upper()} with the wrong extension"
    if not width or not height or max(width, height) > 3840:
        return f"is {width}x{height}; the longest side must be at most 3840"
    return None


def git(*args, root=ROOT):
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True, encoding="utf-8").stdout


def load_entries(report, games, root=ROOT):
    entries = []
    items = root / "items"
    if not items.exists():
        return entries
    for game_dir in sorted(items.iterdir()):
        where = f"items/{game_dir.name}"
        if not game_dir.is_dir():
            report.error(where, "only game folders belong in items/")
            continue
        if game_dir.name not in games["games"]:
            report.error(where, f'"{game_dir.name}" is not a supported game (see games.json)')
            continue
        for folder in sorted(game_dir.iterdir()):
            name = f"{where}/{folder.name}"
            if not folder.is_dir():
                report.error(name, f"each entry is a folder: {where}/<id>/{ENTRY_FILE}")
                continue
            if not ID_PATTERN.match(folder.name):
                report.error(name, "folder name must be the entry id (lowercase letters, numbers, _ and -)")
                continue
            path = folder / ENTRY_FILE
            if not path.is_file():
                report.error(name, f"has no {ENTRY_FILE}")
                continue
            try:
                data = load_json(path)
            except (ValueError, UnicodeDecodeError) as error:
                report.error(f"{name}/{ENTRY_FILE}", f"is not valid JSON: {error}")
                continue
            entries.append(Entry(game_dir.name, folder.name, data, folder))
    return entries


def load_entries_at(ref, root=ROOT):
    entries = {}
    try:
        listing = git("ls-tree", "-r", "--name-only", ref, "--", "items", root=root)
    except subprocess.CalledProcessError:
        return entries
    for name in listing.splitlines():
        parts = name.split("/")
        if len(parts) != 4 or parts[3] != ENTRY_FILE:
            continue
        try:
            data = json.loads(git("show", f"{ref}:{name}", root=root))
        except (ValueError, subprocess.CalledProcessError):
            continue
        entries[(parts[1], parts[2])] = data
    return entries


def check_entry(report, entry, games, hosts, schema):
    validator = jsonschema.Draft202012Validator(schema)
    schema_errors = sorted(validator.iter_errors(entry.data), key=lambda error: list(error.absolute_path))
    for error in schema_errors:
        location = "/".join(str(part) for part in error.absolute_path)
        report.error(entry.source, f"{location or 'entry'}: {error.message}")
    if schema_errors:
        return False

    ok = True
    game_config = games["games"][entry.game]
    if entry.data["id"] != entry.id:
        report.error(entry.source, f'id "{entry.data["id"]}" must match the file name "{entry.id}"')
        ok = False
    if entry.files and "version" not in entry.data:
        report.error(entry.source, "an entry with files needs a version")
        ok = False
    if entry.id in entry.data.get("requires", []):
        report.error(entry.source, "requires itself")
        ok = False

    seen = set()
    for index, file in enumerate(entry.files):
        where = f"{entry.source} files/{index} ({file['path']})"
        root = file_root(game_config, file)
        if root not in game_config["roots"]:
            report.error(where, f'root "{root}" is not available for {entry.game}')
            ok = False
        message = path_error(file["path"])
        if message:
            report.error(where, f"path {message}")
            ok = False
        key = file_key(game_config, file)
        if key in seen:
            report.error(where, "is listed twice")
            ok = False
        seen.add(key)
        for url in file_urls(file):
            message = url_error(url, entry.game, entry.id, hosts)
            if message:
                report.error(where, message)
                ok = False

    if entry.folder is not None:
        for name in entry.images:
            path = entry.folder / name
            if not path.is_file():
                report.error(f"{entry.where}/{name}", "is listed in images but missing")
                ok = False
                continue
            message = image_error(path)
            if message:
                report.error(f"{entry.where}/{name}", message)
                ok = False
        expected = {ENTRY_FILE, *entry.images}
        for path in sorted(entry.folder.iterdir()):
            if path.name not in expected:
                report.error(f"{entry.where}/{path.name}", f"unexpected file; only {ENTRY_FILE} and the files listed in images belong here")
                ok = False
    return ok


def manifest_paths(document):
    paths = set()
    rows = document.get("files", []) if isinstance(document, dict) else document
    for row in rows:
        if isinstance(row, str):
            paths.add(row)
        elif isinstance(row, list) and row and isinstance(row[0], str):
            if len(row) >= 4 and row[3] == "appdata":
                continue
            paths.add(row[0])
    return {path.replace("\\", "/").lower() for path in paths}


def fetch_json(url, timeout=60):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_protected_paths(games, game, fetch=fetch_json):
    config = games["games"][game]
    base = games["updaterBase"]
    paths = set()
    for name in [config["gameManifest"], *config["clientManifests"]]:
        paths |= manifest_paths(fetch(base + name))
    return paths


def check_catalog(report, entries, games, protected=None):
    by_game = {}
    for entry in entries:
        by_game.setdefault(entry.game, []).append(entry)

    bad = set()
    for game, game_entries in by_game.items():
        config = games["games"][game]
        ids = {entry.id for entry in game_entries}
        owners = {}
        directories = {}
        for entry in game_entries:
            for required in entry.data.get("requires", []):
                if required not in ids:
                    report.error(entry.source, f'requires "{required}", which is not a {game} entry')
                    bad.add(entry.source)
            for file in entry.files:
                key = file_key(config, file)
                root, path = key.split(":", 1)
                where = f"{entry.source} ({file['path']})"
                other = owners.get(key)
                if other and other != entry.source:
                    report.error(where, f"is also listed by {other}")
                    bad.add(entry.source)
                owners[key] = entry.source
                parent = path
                while "/" in parent:
                    parent = parent.rsplit("/", 1)[0]
                    directories.setdefault(f"{root}:{parent}", entry.source)
                if root == "game":
                    for folder in config["sweptFolders"]:
                        if path == folder or path.startswith(folder + "/"):
                            report.error(where, f"is inside {folder}/, which the client deletes foreign files from on every update")
                            bad.add(entry.source)
                    if protected is not None and path in protected.get(game, set()):
                        report.error(where, "would overwrite a game or client file")
                        bad.add(entry.source)
        for key, source in owners.items():
            if key in directories:
                report.error(source, f'"{key.split(":", 1)[1]}" is a file here but a folder in {directories[key]}')
                bad.add(source)

        graph = {entry.id: [r for r in entry.data.get("requires", []) if r in ids] for entry in game_entries}
        sources = {entry.id: entry.source for entry in game_entries}
        state = {}

        def visit(node, stack):
            state[node] = 1
            for child in graph[node]:
                if state.get(child) == 1:
                    report.error(sources[node], f"requires forms a cycle: {' -> '.join(stack + [child])}")
                    bad.add(sources[node])
                elif not state.get(child):
                    visit(child, stack + [child])
            state[node] = 2

        for node in graph:
            if not state.get(node):
                visit(node, [node])
    return bad


def check_hash_policy(report, entry, base_data, games):
    config = games["games"][entry.game]
    base_files = {}
    if isinstance(base_data, dict):
        for file in base_data.get("files", []) or []:
            if isinstance(file, dict):
                base_files[file_key(config, file)] = file
    changed = []
    for file in entry.files:
        base = base_files.get(file_key(config, file))
        unchanged = base is not None and same_source(base, file)
        if "hash" in file and not (unchanged and base.get("hash") == file["hash"]):
            report.error(f"{entry.source} ({file['path']})", "remove hash; it is filled in automatically after merge")
        if not unchanged or "hash" not in base:
            changed.append(file)
    return changed


class _RedirectGuard(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed):
        self.allowed = allowed

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlsplit(newurl)
        if target.scheme != "https" or target.hostname not in self.allowed:
            raise DownloadError(f"redirected to {target.scheme}://{target.hostname}, which is not allowed")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def default_opener(hosts):
    allowed = set(hosts["redirects"]) | {urllib.parse.urlsplit(base).hostname for base in hosts["cdn"]}
    opener = urllib.request.build_opener(_RedirectGuard(allowed))
    return opener.open


def _stream(open_url, url, hasher, total, limit, timeout, chunk_size):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with open_url(request, timeout=timeout) as response:
        content_type = (response.headers.get("Content-Type") or "").lower()
        if content_type.startswith("text/html"):
            raise DownloadError(f"{url} returned a web page, not a file")
        while True:
            chunk = response.read(chunk_size)
            if not chunk:
                return total
            total += len(chunk)
            if total > limit:
                raise DownloadError(f"{url} is larger than the listed size")
            hasher.update(chunk)


def download_hash(file, hosts, open_url=None, timeout=60, retries=3, chunk_size=1 << 20, progress=None):
    open_url = open_url or default_opener(hosts)
    hasher = xxhash.xxh3_64()
    total = 0
    for url in file_urls(file):
        candidates = resolve_candidates(url, hosts)
        failure = None
        for _ in range(retries):
            for candidate in candidates:
                saved, start = hasher.copy(), total
                try:
                    total = _stream(open_url, candidate, hasher, total, file["size"], timeout, chunk_size)
                    failure = None
                    break
                except DownloadError:
                    raise
                except (urllib.error.URLError, OSError, ValueError) as error:
                    hasher, total = saved, start
                    failure = f"{candidate}: {error}"
            if failure is None:
                break
        if failure is not None:
            raise DownloadError(failure)
        if progress:
            progress(url, total)
    if total != file["size"]:
        raise DownloadError(f"downloaded {total} bytes but size says {file['size']}")
    return format_hash(hasher)


def entry_times(where, root=ROOT):
    try:
        log = git("log", "--format=%ct%x09%s", "--", where, root=root)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return 0, 0
    times = [int(line.split("\t", 1)[0]) for line in log.splitlines()
             if line and not line.split("\t", 1)[-1].startswith(HASH_COMMIT_SUBJECT)]
    return (times[-1], times[0]) if times else (0, 0)


def dist_item(entry, games, repository, commit, root=ROOT):
    config = games["games"][entry.game]
    files = []
    for file in entry.files:
        item = {"root": file_root(config, file), "path": file["path"], "size": file["size"], "hash": file["hash"]}
        item.update({"url": file["url"]} if "url" in file else {"parts": file["parts"]})
        files.append(item)
    added, updated = entry_times(entry.where, root)
    images = [f"https://raw.githubusercontent.com/{repository}/{commit}/{entry.where}/{name}" for name in entry.images]
    return {
        "id": entry.id,
        "type": entry.data["type"],
        "name": entry.data["name"],
        "author": entry.data["author"],
        "version": entry.data.get("version", ""),
        "description": entry.data["description"],
        "requires": entry.data.get("requires", []),
        "preview": images[0] if images else None,
        "screenshots": images[1:],
        "size": sum(file["size"] for file in files),
        "changesGameFiles": any(file["path"].split("/", 1)[0].lower() not in CONTENT_FOLDERS for file in files),
        "addedAt": added,
        "updatedAt": updated,
        "files": files,
    }


def write_entry(entry, root=ROOT):
    text = json.dumps(entry.data, indent=4, ensure_ascii=False) + "\n"
    (root / entry.source).write_text(text, encoding="utf-8", newline="\n")


def format_size(size):
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024


def summary_markdown(title, report, extra=""):
    lines = [f"## {title}", ""]
    lines.append(f"**Failed: {len(report.errors)} error(s).**" if report.errors else "**Passed.**")
    lines.append("")
    if report.errors:
        lines += ["### Errors", ""] + [f"- `{where}`: {message}" for where, message in report.errors] + [""]
    if report.warnings:
        lines += ["### Warnings", ""] + [f"- `{where}`: {message}" for where, message in report.warnings] + [""]
    if extra:
        lines += [extra, ""]
    return "\n".join(lines)
