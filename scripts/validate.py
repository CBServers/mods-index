import argparse
import sys

import index_lib as lib


def main():
    parser = argparse.ArgumentParser(description="Check the mod index. Downloads new or changed files to verify sizes.")
    parser.add_argument("--base", help="git ref to compare against (the PR's base branch)")
    parser.add_argument("--offline", action="store_true", help="skip downloads and the manifest collision check")
    parser.add_argument("--no-download", action="store_true", help="skip downloads only")
    parser.add_argument("--summary", help="append a Markdown report to this file (GITHUB_STEP_SUMMARY)")
    args = parser.parse_args()

    games, hosts, schema = lib.load_config()
    report = lib.Report()
    entries = lib.load_entries(report, games)
    lister = None if args.offline else (lambda archive: lib.list_archive(archive, hosts))
    valid = [entry for entry in entries if lib.check_entry(report, entry, games, hosts, schema, lister)]

    protected = None
    if not args.offline:
        protected = {}
        for game in sorted({entry.game for entry in valid}):
            try:
                protected[game] = lib.fetch_protected_paths(games, game)
            except Exception as error:
                report.error(game, f"could not fetch its game or client manifests: {error}")
    lib.check_catalog(report, valid, games, protected)

    base_entries = lib.load_entries_at(args.base) if args.base else {}
    to_download = []
    archives = []
    for entry in valid:
        former = games["games"][entry.game].get("formerly")
        base = base_entries.get((entry.game, entry.id)) or base_entries.get((former, entry.id))
        changed = lib.check_hash_policy(report, entry, base, games)
        to_download += [(entry, file) for file in changed]
        archives += [(entry, index) for index in lib.check_archive_policy(report, entry, base)]

    if args.base:
        try:
            touched = lib.git("diff", "--name-only", args.base, "HEAD").splitlines()
        except Exception:
            touched = []
        for name in touched:
            if not name.startswith("items/"):
                report.warn(name, "this PR changes tooling or config outside items/; review it closely")

    rows = []
    downloading = not args.offline and not args.no_download
    if downloading:
        for entry, file in to_download:
            where = f"{entry.source} ({file['path']})"
            print(f"downloading {where}", flush=True)
            try:
                digest = lib.download_hash(file, hosts)
                rows.append(f"| `{entry.game}/{entry.id}` | `{file['path']}` | {lib.format_size(file['size'])} | `{digest}` |")
            except lib.DownloadError as error:
                report.error(where, str(error))

    tables = []
    for entry, index in archives:
        where = lib.archive_where(entry, index)
        archive = entry.archives[index]
        if downloading:
            print(f"downloading {where}", flush=True)
            try:
                digest, contents = lib.download_archive(archive, hosts)
                rows.append(f"| `{entry.game}/{entry.id}` | `{lib.archive_name(archive)}` | {lib.format_size(archive['size'])} | `{digest}` |")
                if [row["member"] for row in contents] != [row["member"] for row in entry.archive_rows(index)]:
                    report.error(where, "the downloaded archive lists different members than its central directory")
            except lib.DownloadError as error:
                report.error(where, str(error))
        members = entry.archive_rows(index)
        if members:
            lines = [f"| `{row['member']}` | `{row['path']}` | {lib.format_size(row['size'])} |" for row in members]
            tables.append(f"#### `{entry.game}/{entry.id}` {lib.archive_name(archive)}\n\n| Member | Installs to | Size |\n|---|---|---|\n" + "\n".join(lines))

    extra = ""
    if rows:
        extra = "### Downloaded\n\n| Entry | File | Size | Hash |\n|---|---|---|---|\n" + "\n".join(rows)
    elif not downloading:
        extra = f"Downloads skipped ({len(to_download)} file(s) and {len(archives)} archive(s) would be checked)."
    if tables:
        extra += "\n\n### Archives\n\n" + "\n\n".join(tables)
    markdown = lib.summary_markdown("Mod index check", report, extra)
    print(markdown)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as handle:
            handle.write(markdown + "\n")
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
