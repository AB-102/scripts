#!/usr/bin/env python3
"""
Renames OBS replays to ShadowPlay format based on folder structure.

Usage:
`cd` into the clips root directory and run `python rename_obs_videos.py`.
Clips must be organized at least one level deep: <RootDirectory>/<GameName>/Replay_*.mkv.

By default, an interactive prompt lists discovered game folders and lets you select
which to include. Pass --whitelist to skip the prompt for non-interactive use.
Files directly in the root are ignored unless --include-root is passed.

Writes a .log file recording each rename as it happens.

Run with --help for full argument details.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

LOG_PREFIX = "rename_obs_videos_"
ROOT_DIR = Path.cwd()


def setup_file_logging() -> Path:
    log_path = ROOT_DIR / f"{LOG_PREFIX}{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log"
    file_handler = logging.FileHandler(log_path)
    file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logging.getLogger().addHandler(file_handler)
    return log_path


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
    return old_path.parent / f"{new_prefix} {old_without_prefix}"


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

        log_path = setup_file_logging()
        logging.info(f"Log: {log_path}")

        videos_total = len(matching_videos)
        for count, video_path in enumerate(matching_videos, start=1):
            logging.info(f"Processing video {count} of {videos_total}")
            new_path = get_new_path(video_path)
            try:
                rename_video(video_path, new_path)
            except Exception as e:
                logging.error(
                    f"Something went wrong when attempting to rename: {e}\n"
                    f"Old path: {video_path}\n"
                    f"New path: {new_path}"
                )
                return

    except KeyboardInterrupt:
        print()
        print("Aborted.", flush=True)
        sys.exit(0)


if __name__ == "__main__":
    main()
