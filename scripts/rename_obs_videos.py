#!/usr/bin/env python3
"""
Renames OBS replays to ShadowPlay format based on folder structure.

Usage:
`cd` into the clips root directory (e.g. Videos/) and run `python rename_obs_videos.py`.
Clips must be organized at least one level deep: <RootDirectory>/<GameName>/Replay_*.mkv.

By default, an interactive prompt lists discovered game folders and lets you select
which to include. Pass --whitelist to skip the prompt for non-interactive use.
Files directly in the root are ignored unless --include-root is passed.

Writes a JSON log of all planned renames before touching any files.
On success, the log is deleted, otherwise it is preserved for inspection.

Run with --help for full argument details.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
from pathlib import Path
from tempfile import mkstemp

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)

JSON_PREFIX = "rename_obs_videos_"
ROOT_DIR = Path.cwd()


@dataclass(frozen=True)
class VideoEntry:
    old_path: Path
    new_path: Path


# https://stackoverflow.com/a/51286749/
class VideoEntryJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if is_dataclass(o):
            return asdict(o)
        if isinstance(o, Path):
            return str(o)
        return super().default(o)


def build_json_filename() -> str:
    return JSON_PREFIX + datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def create_json_file() -> Path:
    filename = build_json_filename()
    title_exists = (ROOT_DIR / f"{filename}.json").exists()
    if title_exists:
        fd, json_path = mkstemp(".json", filename + "_", ROOT_DIR)
        os.close(fd)
        json_path = Path(json_path)
    else:
        json_path = ROOT_DIR / f"{filename}.json"
        json_path.touch()
    return json_path


def find_game_folders() -> list[Path]:
    return sorted(
        {
            video.parent
            for video in ROOT_DIR.glob("**/Replay_*.mkv")
            if video.parent != ROOT_DIR
        }
    )


def prompt_folder_selection(folders: list[Path]) -> list[Path]:
    print("\nFound game folders:")
    for i, folder in enumerate(folders, start=1):
        print(f"  {i}. {folder.name}")

    selection = input(
        "\nSelect folders (comma-separated numbers, or Enter for all): "
    ).strip()

    if not selection:
        return folders

    selected = []
    for part in selection.split(","):
        part = part.strip()
        if not part.isdigit():
            logging.warning(f"Ignoring invalid input: '{part}'")
            continue
        index = int(part) - 1
        if 0 <= index < len(folders):
            selected.append(folders[index])
        else:
            logging.warning(f"Ignoring out-of-range selection: {part}")

    return selected


def find_matching_videos(folders: list[Path], include_root: bool = False) -> list[Path]:
    videos: list[Path] = []
    for folder in folders:
        videos.extend(folder.rglob("Replay_*.mkv"))
    if include_root:
        videos.extend(ROOT_DIR.glob("Replay_*.mkv"))
    return videos


def get_new_path(old_path: Path) -> Path:
    new_prefix = old_path.parent.name
    old_without_prefix = old_path.name.removeprefix("Replay_")
    # extra space after the prefix follows shadowplay format
    new_path = old_path.parent / f"{new_prefix} {old_without_prefix}"
    return new_path


def rename_video(old_path: Path, new_path: Path) -> None:
    if old_path == new_path:
        raise ValueError("File is already named correctly")
    logging.info(f"Renaming '{old_path.name}' to '{new_path.name}'")
    old_path.rename(new_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rename OBS replays to ShadowPlay format."
    )
    parser.add_argument(
        "--include-root",
        action="store_true",
        help="also rename videos sitting directly in the root folder",
    )
    parser.add_argument(
        "--whitelist",
        nargs="+",
        metavar="FOLDER",
        help='only rename videos in the named game folders, skipping the interactive prompt (e.g. --whitelist Desktop Minecraft "Counter-Strike 2")',
    )
    args = parser.parse_args()

    try:
        game_folders = find_game_folders()

        if not game_folders and not args.include_root:
            logging.info("No game folders with matching videos found.")
            return

        if args.whitelist:
            whitelist_set = set(args.whitelist)
            game_folders = [f for f in game_folders if f.name in whitelist_set]
            missing = whitelist_set - {f.name for f in game_folders}
            for name in sorted(missing):
                logging.warning(f"Whitelisted folder not found: '{name}'")
        elif game_folders:
            game_folders = prompt_folder_selection(game_folders)

        matching_videos = find_matching_videos(
            game_folders, include_root=args.include_root
        )

        if not matching_videos:
            logging.info("No matching videos found in selected folders.")
            return

        json_path = create_json_file()
        json_array: list[VideoEntry] = []
        videos_total = len(matching_videos)

        for video_path in matching_videos:
            new_path = get_new_path(video_path)
            json_array.append(VideoEntry(video_path, new_path))

        try:
            with json_path.open("w") as file:
                json.dump(json_array, file, cls=VideoEntryJSONEncoder)
        except Exception as e:
            logging.error(f"Something went wrong when initializing JSON file: {e}")
            return

        count = 0
        for entry in json_array:
            count += 1
            logging.info(f"Processing video {count} of {videos_total}")
            try:
                rename_video(entry.old_path, entry.new_path)
            except Exception as e:
                logging.error(
                    f"Something went wrong when attempting to rename: {e}\n"
                    f"Old path: {str(entry.old_path)}\n"
                    f"New path: {str(entry.new_path)}"
                )
                logging.info(f"JSON log preserved at: {json_path}")
                return

        # JSON file is temporary on happy path
        json_path.unlink()

    except KeyboardInterrupt:
        print()
        print("Aborted.", flush=True)
        sys.exit(0)


if __name__ == "__main__":
    main()
