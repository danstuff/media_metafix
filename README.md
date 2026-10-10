# media_metafix

Two scripts that check and fix media library metadata:

- **`music_metafix`** (MMF): music as `root/artist/album/song.ext`.
- **`tv_metafix`** (TMF): shows as `root/show/season/episode.ext` and
  movies as `root/series/title.ext`, e.g. `Harry Potter/Harry Potter
  and the Sorcerer's Stone (2001).mkv`. One root can hold both.

Folder names are trusted (artist/album, show/season, series); the rest
comes from online lookups.

## Setup

```sh
sudo apt install ffmpeg libchromaprint-tools   # chromaprint: MMF only
pip install pyyaml pathspec                    # both scripts
pip install mutagen pyacoustid musicbrainzngs pillow   # MMF only
```

Optional settings, each unlocking the steps listed:

- `MMF_MUSICBRAINZ_CONTACT`: your email, sent to MusicBrainz (MMF
  `scan`).
- `MMF_ACOUSTID_API_KEY`: free at acoustid.org/new-application (MMF
  `fingerprint`).
- `TMF_TMDB_API_KEY`: free at themoviedb.org/settings/api (TMF `scan`
  for movies; without it, titles and years come from filenames like
  `Heat (1995).mkv`).
- `TMF_OPENSUBTITLES_API_KEY`: free at opensubtitles.com/consumers (TMF
  subtitles in `scan`, and `fingerprint`).
- `TMF_OPENSUBTITLES_USERNAME` / `_PASSWORD`: optional login, raising
  the daily subtitle download limit.

## Workflow

Both scripts share a scan → check → apply loop:

```sh
tv_metafix scan /videos             # look up metadata, queue changes
tv_metafix check                    # flag suspicious entries
tv_metafix fingerprint /videos      # optional: compare with the files
tv_metafix apply /videos --dry-run  # preview what apply would write
tv_metafix apply /videos            # write the (edited) queue
```

`scan` changes nothing in root. It writes a YAML queue for you to
review, and downloads album art (MMF) or missing subtitles (TMF) into
`tmp/art/` or `tmp/subtitles/`, mirroring root's folders. In the queue,
delete a field to skip that change, or an entry to skip that file;
delete a downloaded file to skip it too. `apply` writes the queue,
then copies in the art or embeds the subtitles. `check` flags things
like duplicate or missing track/episode numbers, filenames that don't
match the new number or title, and blank or inconsistent fields. For
each, you can edit the queue, skip it, or mark it `# OK` for good.

Other steps (run any step with `-h` for its options):

- MMF `normalize <root>`: even out loudness.
- `convert <root> <from> <to>`: re-encode (MMF) or remux (TMF), keeping
  tags, e.g. `wma mp3` or `avi mkv`.
- `rename <root> ...`: rename files from their tags, e.g. MMF
  `"%num - %title"`, TMF `--episodes "S%seasonE%episode - %title"
  --movies "%title (%year)"`.

## Data sources

- **MMF:** MusicBrainz (titles, track numbers), Cover Art Archive
  (album art), AcoustID (`fingerprint`).
- **TMF:** [TVmaze](https://www.tvmaze.com/api) (episodes, no key),
  [TMDB](https://developer.themoviedb.org) (movies) and
  [OpenSubtitles](https://opensubtitles.com) (subtitles).
- **TMF `fingerprint`** looks files up by their OpenSubtitles hash. No
  free service fingerprints video content, so only unmodified copies of
  known releases are identified; re-encoded files show as "unknown".
- **Album art** is saved as `art.jpg`; `scan --art-fn cover.png`
  picks another name, and its extension sets the image format. Art is
  only downloaded for albums without a file of that name, and `apply`
  never replaces an existing one.
- **Subtitles** are English by default; `scan --sub-lang fr` (or any
  OpenSubtitles code, like `pt-BR`) picks another language, and
  `--no-subs` skips them. `scan` checks the code with OpenSubtitles
  before scanning anything. Subtitles are only downloaded for videos
  without any in that language, embedded or in a file alongside
  (`.srt`, `.ass`, `.ssa`, `.vtt`, `.sub`); subtitles with no language
  tag count too, to avoid duplicates. Downloads count against
  OpenSubtitles' daily limit, and a rescan reuses files already in
  `tmp/subtitles/`. `apply` embeds them in MKV, MP4, M4V, MOV and WebM;
  other containers, like AVI, get a `name.<lang>.srt` file alongside.

TMF tags are `title`, `show`, `season_number`, `episode_sort`, `date`
and `collection` (the series; `album` in MP4/AVI). AVI can't hold the
episode tags, so `apply` suggests converting those files to MKV.

## Safety

- `apply`, `normalize`, `convert` and `rename` take `--dry-run`, which
  prints each change without making it. Nothing is backed up, so
  dry-run first and keep your own backups: a real run can't be undone.
- `tmp/` is relative to the current directory, not root. The queue
  records its root, and `apply` refuses to run against another one.
- A `.mmfignore` file in root (`.gitignore` syntax) excludes files and
  folders from every step.

## Layout

```
music_metafix, tv_metafix   the scripts
common/                     shared code: queue, checks, .mmfignore,
                            dry runs, ffmpeg, HTTP, CLI
tests/                      pytest suite; APIs are faked, network is
                            blocked, ffmpeg tests skip without ffmpeg
```

Run the tests with `pip install pytest && pytest tests`.
