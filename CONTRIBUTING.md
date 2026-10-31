# Submitting a map or mod

The CB Servers Launcher lists every entry in this repository on its Mods page and installs it for players. Your
files stay where you host them; this repository only holds the list.

1. Upload your files to a release on your own GitHub repository.
2. Fork this repository.
3. Add a folder `items/<game>/<id>/` with an `entry.json` and your images.
4. Open a pull request. The checks download your files and tell you if anything is wrong.

Once a maintainer merges it, the hashes are filled in automatically and the entry shows up in the launcher a few
minutes later.

## Games

| Folder | Game |
|---|---|
| `cod4x` | Call of Duty 4: Modern Warfare |
| `iw4x` | Call of Duty: Modern Warfare 2 |
| `iw5` | Call of Duty: Modern Warfare 3 (Plutonium) |
| `mw2r` | Call of Duty: Modern Warfare 2 Campaign Remastered |
| `mwr` | Call of Duty: Modern Warfare Remastered |
| `iw` | Call of Duty: Infinite Warfare |
| `t4` | Call of Duty: World at War (Plutonium) |
| `t5` | Call of Duty: Black Ops (Plutonium) |
| `t6` | Call of Duty: Black Ops II (Plutonium) |

Black Ops III uses the Steam Workshop and is not listed here.

## The entry

```json
{
    "id": "zm_example",
    "type": "map",
    "name": "Example",
    "author": "you",
    "version": "1.0",
    "description": "One or two sentences about the map.",
    "images": ["main.jpg", "spawn.jpg", "boss.png"],
    "requires": [],
    "files": [
        {
            "path": "usermaps/zm_example/zm_example.ff",
            "size": 640057512,
            "url": "https://github.com/you/your-repo/releases/download/v1.0/zm_example.ff"
        }
    ]
}
```

- `id`: lowercase letters, numbers, `_` and `-`, up to 64 characters. It must match the folder name and be unique
  for the game.
- `type`: `map` or `mod`. It only decides where the entry is filtered in the launcher.
- `name`: the title on the card, up to 64 characters.
- `author`: you, up to 64 characters.
- `version`: any text. Change it every time you update your files.
- `description`: shown on the card and in the details panel. Keep it short.
- `images`: file names in your entry folder, in order. See below.
- `requires`: ids of other entries for the same game that must be installed first, up to 16.
- `files`: every file the launcher installs. See below.

Leave out `hash`. It is filled in after merge.

## Files

Each file says where it goes and where to download it from:

- `path`: where the file goes, relative to the root, with forward slashes. Subfolders are fine.
- `root`: `storage` or `game`. Optional.
  - `storage` is Plutonium's folder for the game (`%LOCALAPPDATA%\Plutonium\storage\<game>`). It is the default
    for `t4`, `t5`, `iw5` and `t6`, and is not available for the other games.
  - `game` is the player's game install folder. It is the default for every other game.
- `size`: the size of the file in bytes.
- `url`: a direct download link (see Links).

Most maps and mods only need `mods/<name>/...` or `usermaps/<name>/...`. Files may go elsewhere under the root
when they have to (for example `zone/all/` or `raw/`), with these limits:

- A file must not replace a file that belongs to the game or to the game's client.
- On Modern Warfare Remastered, Infinite Warfare and MW2 Campaign Remastered, nothing may go in `cdata/`. The
  client deletes anything there it did not ship.
- Two entries cannot list the same file.

The launcher shows a "Changes game files" tag on entries with files outside `mods/` and `usermaps/`.

The file name in `path` does not have to match the name in the link, so flat release asset names can land in
nested folders.

## Links

Every link must be a direct download that works without logging in. Allowed at the moment:

- GitHub release assets: `https://github.com/<you>/<repo>/releases/download/<tag>/<file>`

Google Drive, Mega, MediaFire, Dropbox, OneDrive, ModDB and Nexus links are rejected, because they put a page,
a login or a changing link in front of the file. If you need another host, open an issue.

Files hosted on the CB Servers CDN use `cdn:mods/<game>/<id>/<file>` links. Only maintainers upload there.

## Files of 2 GB or more

GitHub releases do not allow files of 2 GB or more. Split the file and list the parts in order under `parts`
instead of `url`:

```json
{
    "path": "usermaps/zm_example/zm_example.pak",
    "size": 6442450944,
    "parts": [
        "https://github.com/you/your-repo/releases/download/v1.0/zm_example.pak.001",
        "https://github.com/you/your-repo/releases/download/v1.0/zm_example.pak.002",
        "https://github.com/you/your-repo/releases/download/v1.0/zm_example.pak.003",
        "https://github.com/you/your-repo/releases/download/v1.0/zm_example.pak.004"
    ]
}
```

`size` is the size of the whole file, not of a part. The launcher downloads the parts and joins them back
into one file.

To split a file with 7-Zip (https://www.7-zip.org): right click the file, choose Split file, type `1900M` in
"Split to volumes, bytes", and click OK. Upload every `.001`, `.002`, ... part as it is. Do not zip or rename them.
Archives (`.zip`, `.7z`, `.rar`) are not supported; list every file on its own.

## Images

Put up to 10 PNG or JPG images in your entry folder and list them in `images`:

- The first image is the main one: it is shown on the card and first in the details panel. 16:9 (1920x1080
  or 1280x720) fills the card; other shapes are shown whole over a blurred copy of themselves.
- The rest show up as the scrolling screenshot list in the details panel.
- Any shape is fine for every image.
- Each image is at most 8 MB and at most 3840 pixels on its longest side.

Only `entry.json` and the images you list belong in the folder.

## Coming soon

Leave out `files` (and `version` if you like) and the launcher shows the entry with a COMING SOON tag that
cannot be installed yet. Add `files` in a later pull request.

## Updates

Make a new release with the new files, then open a pull request that changes your entry: a new `version`, new
links and new sizes. Remove the `hash` of every file you changed; the checks tell you if you missed one.
Players see Update in the launcher and only download the files that changed. Files your new version no longer
lists are removed from their game.

## Changing files after merge

Do not replace a file in a release after your entry is merged. Every file has a hash, and a file that no longer
matches fails to install. Publish an update instead.

## What gets a submission rejected

- Links that are not direct downloads or not on an allowed host.
- Files that would replace game or client files, or that another entry already lists.
- An id that is already taken for the game.
- Images that break the rules above.
- A map or mod that does not load.
