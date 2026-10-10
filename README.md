# media_metafix

A pair of scripts that check and fix media library metadata:

- **`music_metafix`**: music as `root/artist/album/song.ext`.
- **`tv_metafix`**: shows as `root/show/season/episode.ext` and/or
  movies as `root/series/title.ext`. One root can hold both.

Folder names are trusted (artist/album, show/season, series); the rest
comes from online lookups.

Examples of acceptable directory structure:

```
Eagles/Hotel California/03 Life in the Fast Lane.mp3

Futurama/Season 02/S02E07 A Head in the Polls.mp4

Harry Potter/Harry Potter and the Sorcerer's Stone (2001).mkv
```

## Setup

First you'll need the latest version of [python](https://www.python.org/downloads/). 

Then, install dependencies for the scripts you'll be using. For `music_metafix`:

```sh
sudo apt install ffmpeg libchromaprint-tools 
pip install pyyaml pathspec mutagen pyacoustid musicbrainzngs pillow
```

And/or for `tv_metafix`:

```sh
sudo apt install ffmpeg
pip install pyyaml pathspec
```

And to optionally run tests:

```sh
pip install pytest && pytest tests
```

### Optional Features

- `MMF_MUSICBRAINZ_CONTACT`: your email, sent to MusicBrainz (required
  for `music_metafix scan`).
- `MMF_ACOUSTID_API_KEY`: free at acoustid.org/new-application (for
  `music_metafix fingerprint`).
- `TMF_TMDB_API_KEY`: free at themoviedb.org/settings/api (for movies
  during `tv_metafix scan`).
- `TMF_OPENSUBTITLES_API_KEY`: free at opensubtitles.com/consumers (for
  subtitles in `tv_metafix scan`, and `fingerprint`).
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
review, and downloads album art (for music) or missing subtitles (for TV) into
`tmp/art/` or `tmp/subtitles/`, mirroring root's folders. In the queue,
delete a field to skip that change, or an entry to skip that file;
delete a downloaded file to skip it too.

`apply` writes the queue, then copies in the art or embeds the subtitles. 

`check` interactively flags things like duplicate or missing track/episode
numbers, filenames that don't match the new number or title, and
blank/inconsistent fields.

Other steps (run any step with `-h` for its options):

- `normalize <root>`: even out loudness (`music_metafix` only).
- `convert <root> <from> <to>`: re-encode or remux files in bulk,
  keeping tags, e.g. `wma mp3` or `avi mkv`.
- `rename <root> ...`: after `apply`, rename files based on their metadata:
  ```sh
  music_metafix rename /library/Music/ "%num - %title"`
  tv_metafix rename /library/TV/ --episodes "S%seasonE%episode - %title" --movies "%title (%year)"
  ```
