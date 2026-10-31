# CB Servers mod index

The list of community maps and mods the CB Servers Launcher shows on its Mods page, for every supported game
except Black Ops III (which uses the Steam Workshop). Creators add entries by pull request; the files stay on
their own hosts.

**Submitting a map or mod:** read [CONTRIBUTING.md](CONTRIBUTING.md).

## Layout

```
items/<game>/<id>/entry.json    one entry
items/<game>/<id>/*.jpg|png     its images, listed in entry.json
games.json                      supported games, install roots, manifests to protect, swept folders
hosts.json                      allowed download hosts and CDN mirrors
schema/entry.schema.json        entry format
scripts/                        validate.py, publish.py, index_lib.py
```

`games.json` mirrors the launcher (`layouts_` in `mod_store.cpp` and the client entries in `game_config.cpp`);
keep them in sync.

## How it is published

- **Validate** (every pull request): entry schema, path and link rules, collisions with the game's
  and clients' manifests from CBServers/updater and with other entries, and a full download of every new or
  changed file to check its size. Downloads are streamed and never stored. A pull request may not add or alter
  a `hash`.
- **Publish** (every push to `main`): downloads each file without a hash, writes the XXH3 hash into its entry
  and commits it as `fill hashes [skip ci]`, then builds `dist/<game>.json` for every game and force-pushes
  them as a single commit to the `dist` branch. Entries that fail a check are left out of the build. Finally it
  pings the workshop worker so the launcher sees the change right away.

Hashes are XXH3-64 in the launcher's `utils::hash` format: the little-endian bytes in uppercase hex.

## dist format

`dist/<game>.json`:

```json
{
  "game": "t6",
  "commit": "<main commit the build came from>",
  "generatedAt": 1793500000,
  "items": [
    {
      "id": "zombies_declassified",
      "type": "map",
      "name": "Zombies Declassified",
      "author": "Logo-2K",
      "version": "beta2",
      "description": "...",
      "requires": [],
      "preview": "https://raw.githubusercontent.com/CBServers/mods-index/<commit>/items/t6/zombies_declassified/main.jpg",
      "screenshots": ["..."],
      "size": 9728225788,
      "changesGameFiles": true,
      "addedAt": 1793400000,
      "updatedAt": 1793450000,
      "files": [
        { "root": "storage", "path": "mods/dlc5/mod_load.ff", "size": 560448, "hash": "...", "url": "https://..." }
      ]
    }
  ]
}
```

`root` is always filled in, `preview` is null without images, and each file has either `url` or `parts`.
`addedAt` and `updatedAt` come from git history (unix seconds), ignoring the hash commits.

## Running locally

```bash
pip install -r scripts/requirements.txt
```

```bash
python scripts/validate.py --no-download
```

`validate.py` without flags also downloads every file that has no hash; `--offline` skips the manifest check
too. `publish.py --dist out` builds the indexes into `out/` without touching any entry.
