import argparse
import json
import os
import sys
import time
from pathlib import Path

import index_lib as lib


def main():
    parser = argparse.ArgumentParser(description="Fill in missing hashes and build the per-game indexes.")
    parser.add_argument("--hash", action="store_true", help="download files without a hash and write it into their entry")
    parser.add_argument("--dist", help="write <game>.json for every game into this folder")
    parser.add_argument("--offline", action="store_true", help="skip the manifest collision check")
    parser.add_argument("--summary", help="append a Markdown report to this file (GITHUB_STEP_SUMMARY)")
    args = parser.parse_args()

    games, hosts, schema = lib.load_config()
    report = lib.Report()
    entries = lib.load_entries(report, games)
    valid = [entry for entry in entries if lib.check_entry(report, entry, games, hosts, schema)]

    protected = None
    if not args.offline:
        protected = {}
        for game in sorted({entry.game for entry in valid}):
            try:
                protected[game] = lib.fetch_protected_paths(games, game)
            except Exception as error:
                # Building without the collision check would drop or wrongly keep entries, so publish nothing.
                print(f"could not fetch the {game} game or client manifests: {error}", file=sys.stderr)
                return 1
    bad = lib.check_catalog(report, valid, games, protected)
    valid = [entry for entry in valid if entry.source not in bad]

    hashed = []
    if args.hash:
        for entry in valid:
            changed = False
            for index, file in enumerate(entry.files):
                if "hash" in file:
                    continue
                where = f"{entry.source} ({file['path']})"
                print(f"hashing {where}", flush=True)
                try:
                    digest = lib.download_hash(file, hosts)
                except lib.DownloadError as error:
                    report.error(where, str(error))
                    continue
                ordered = {key: file[key] for key in ("root", "path", "size") if key in file}
                ordered["hash"] = digest
                ordered.update({key: value for key, value in file.items() if key not in ordered})
                entry.data["files"][index] = ordered
                changed = True
                hashed.append(f"| `{entry.game}/{entry.id}` | `{file['path']}` | `{digest}` |")
            if changed:
                lib.write_entry(entry)

    listed = []
    if args.dist:
        out = Path(args.dist)
        out.mkdir(parents=True, exist_ok=True)
        repository = os.environ.get("GITHUB_REPOSITORY", "CBServers/mods-index")
        commit = os.environ.get("INDEX_COMMIT") or lib.git("rev-parse", "HEAD").strip()
        for game in sorted(games["games"]):
            items = []
            for entry in valid:
                if entry.game != game:
                    continue
                missing = [file["path"] for file in entry.files if "hash" not in file]
                if missing:
                    report.error(entry.source, f"left out of the index: {len(missing)} file(s) have no hash")
                    continue
                items.append(lib.dist_item(entry, games, repository, commit))
            items.sort(key=lambda item: item["id"])
            document = {"game": game, "commit": commit, "generatedAt": int(time.time()), "items": items}
            (out / f"{game}.json").write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
            listed.append(f"| `{game}` | {len(items)} |")

    extra = ""
    if hashed:
        extra += "### Hashed\n\n| Entry | File | Hash |\n|---|---|---|\n" + "\n".join(hashed) + "\n\n"
    if listed:
        extra += "### Built\n\n| Game | Entries |\n|---|---|\n" + "\n".join(listed)
    markdown = lib.summary_markdown("Mod index publish", report, extra.strip())
    print(markdown)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as handle:
            handle.write(markdown + "\n")
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
