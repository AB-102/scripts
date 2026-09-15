#!/usr/bin/env python3
"""
Trims overlapping replays per directory based on comparisons using ffmpeg and format pattern matching.

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
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise
from pathlib import Path

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)

LOG_PREFIX = "trim_overlapping_videos_"
TIMESTAMP_LENGTH = len("YYYY-MM-DD_HH-MM-SS")
TRIM_SUFFIX = "_trimmed"
TRIM_LEEWAY_SECONDS = 0.5  # ensures frames aren't clipped off for editors
ROOT_DIR = Path.cwd()


@dataclass(frozen=True)
class VideoClip:
    path: Path
    end_time: datetime
    start_time: datetime
    duration: timedelta


def setup_file_logging() -> Path:
    log_path = (
        ROOT_DIR
        / f"{LOG_PREFIX}{datetime.now().astimezone().strftime('%Y-%m-%d_%H-%M-%S')}.log"
    )
    file_handler = logging.FileHandler(log_path)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    )
    logging.getLogger().addHandler(file_handler)
    return log_path


def is_eligible_video(video: Path) -> bool:
    file = video.stem
    parent_folder_prefix = video.parent.stem + " "
    valid_prefixes = (parent_folder_prefix, "Replay_")

    file_prefix = next((p for p in valid_prefixes if file.startswith(p)), None)
    if file_prefix is None:
        return False

    # include modified clips with an appended suffix
    timestamp = file.removeprefix(file_prefix)[:TIMESTAMP_LENGTH]
    try:
        datetime.strptime(timestamp, "%Y-%m-%d_%H-%M-%S")  # noqa: DTZ007
    except ValueError:
        return False

    return True


def parse_end_time(video: Path) -> datetime:
    file = video.stem
    parent_folder_prefix = video.parent.stem + " "
    valid_prefixes = (parent_folder_prefix, "Replay_")
    file_prefix = next(p for p in valid_prefixes if file.startswith(p))
    timestamp = file.removeprefix(file_prefix)[:TIMESTAMP_LENGTH]
    return datetime.strptime(timestamp, "%Y-%m-%d_%H-%M-%S")  # noqa: DTZ007


def find_game_folders() -> list[Path]:
    return sorted(
        {
            video.parent
            for video in ROOT_DIR.glob("**/*.mkv")
            # if video.parent != ROOT_DIR and is_eligible_video(video)
            if is_eligible_video(video)
        }
    )


def confirm_folder(folder: Path) -> bool:
    response = input(f"Trim overlapping clips in '{folder.name}'? [y/N] ").strip()
    return response.lower() in ("y", "yes")


def find_folder_videos(folder: Path) -> list[Path]:
    return sorted(filter(is_eligible_video, folder.rglob("*.mkv")))


def find_untrimmed_originals(videos: list[Path]) -> list[Path]:
    trimmed_stems = {video.stem for video in videos if video.stem.endswith(TRIM_SUFFIX)}
    return [
        video
        for video in videos
        if not video.stem.endswith(TRIM_SUFFIX)
        and f"{video.stem}{TRIM_SUFFIX}" not in trimmed_stems
    ]


def get_duration(video: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            video,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


def build_video_clip(video: Path) -> VideoClip:
    end_time = parse_end_time(video)
    duration = timedelta(seconds=get_duration(video))
    return VideoClip(
        path=video,
        end_time=end_time,
        start_time=end_time - duration,
        duration=duration,
    )


def has_enough_space(video: Path) -> bool:
    free_space = shutil.disk_usage(video.parent).free
    return free_space > video.stat().st_size


def trim_video(clip: VideoClip, trim_seconds: float) -> Path:
    output_path = clip.path.with_stem(f"{clip.path.stem}{TRIM_SUFFIX}")
    logging.info(
        f"Trimming '{clip.path.name}' by {trim_seconds:.2f}s -> '{output_path.name}'"
    )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            f"{trim_seconds:.3f}",
            "-i",
            clip.path,
            "-map",
            "0",
            "-c",
            "copy",
            output_path,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Trim overlapping ShadowPlay format video clips."
    )
    parser.add_argument(
        "--delete-originals",
        action="store_true",
        help="delete the pre-trim original file after a successful trim",
    )
    args = parser.parse_args()

    try:
        game_folders = find_game_folders()

        if not game_folders:
            logging.info("No game folders with matching videos found.")
            return

        selected_folders = [f for f in game_folders if confirm_folder(f)]

        if not selected_folders:
            logging.info("No folders selected.")
            return

        log_path = setup_file_logging()
        logging.info(f"Log: {log_path}")

        folders_total = len(selected_folders)
        for folder_count, folder in enumerate(selected_folders, start=1):
            logging.info(
                f"Processing folder {folder_count} of {folders_total}: '{folder.name}'"
            )

            originals = find_untrimmed_originals(find_folder_videos(folder))
            if len(originals) < 2:
                continue

            try:
                clips = sorted(
                    (build_video_clip(video) for video in originals),
                    key=lambda clip: clip.end_time,
                )
            except Exception as e:
                logging.error(
                    f"Something went wrong reading clip info in '{folder.name}': {e}"
                )
                return

            for former, latter in pairwise(clips):
                overlap_seconds = (former.end_time - latter.start_time).total_seconds()
                if overlap_seconds <= 0:
                    continue

                trim_seconds = max(0.0, overlap_seconds - TRIM_LEEWAY_SECONDS)
                if trim_seconds <= 0:
                    continue

                if not has_enough_space(latter.path):
                    logging.error(
                        f"Not enough free disk space to trim '{latter.path.name}'."
                    )
                    return

                try:
                    trim_video(latter, trim_seconds)
                except Exception as e:
                    logging.error(
                        f"Something went wrong when attempting to trim file {latter.path.name}: {e}\n"
                        f"Path: {latter.path}"
                    )
                    return

                if args.delete_originals:
                    logging.info(f"Deleting original '{latter.path.name}'")
                    latter.path.unlink()

    except KeyboardInterrupt:
        print()
        print("Aborted.", flush=True)
        sys.exit(0)


if __name__ == "__main__":
    main()
