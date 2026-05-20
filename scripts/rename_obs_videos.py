"""
Renames OBS replays to ShadowPlay format based on folder structure.

Usage:
`cd` into the clips root directory (e.g. Videos/) and run `python rename_obs_videos.py`.
Clips must be organized at least one level deep: Videos/<GameName>/Replay_*.mkv.
Files directly in the root are ignored.

Writes a JSON log of all planned renames before touching any files.
On success, the log is deleted, otherwise it is preserved for inspection.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import sys
from tempfile import mkstemp

JSON_PREFIX = 'rename_obs_videos_'
ROOT_DIR = Path.cwd()

@dataclass
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

def format_json_title()->tuple[str, bool]:
    current_date = '{date:%Y-%m-%d_%H-%M-%S}'.format(date=datetime.now())
    title = JSON_PREFIX + current_date
    collision = ROOT_DIR.joinpath(title).exists()
    return title, collision

def create_json_file()->Path:
    json_title, collision = format_json_title()
    if collision:
        fd, json_path = mkstemp('.json', json_title + '_', ROOT_DIR)
        os.close(fd)
        json_path = Path(json_path)
    else:
        json_path = ROOT_DIR.joinpath(json_title + '.json')
        json_path.touch()
    return json_path

def find_matching_videos()->list[Path]:
    # ignores unorganized videos sitting in the root 'Videos/'
    return [video for video in ROOT_DIR.glob('**/Replay_*.mkv') if video.parent != ROOT_DIR]

def get_new_path(old_path: Path)->Path:
    new_prefix = old_path.parent.name
    old_without_prefix = old_path.name.removeprefix('Replay_')
    # extra space after the prefix follows shadowplay format
    new_path = Path(old_path.parent).joinpath(new_prefix + ' ' + old_without_prefix)
    return new_path

def rename_video(old_path: Path, new_path: Path):
    if old_path == new_path:
        raise Exception("Target path already exists")
    print(f"Renaming '{old_path.name}' to '{new_path.name}'")
    old_path.rename(new_path)

def main():
    json_path = create_json_file()
    json_array: list[VideoEntry] = []
    matching_videos = find_matching_videos()
    videos_total = len(matching_videos)

    for video_path in matching_videos:
        new_path = get_new_path(video_path)
        json_array.append(VideoEntry(video_path, new_path))

    try:
        with json_path.open("w") as file:
            json.dump(json_array,
            file,
            cls=VideoEntryJSONEncoder)
    except Exception as e:
        print(f"Something went wrong when initializing JSON file: {e}", file=sys.stderr)
        return

    count = 0
    for entry in json_array:
        try:
            count += 1
            print(f"Processing video {count} of {videos_total}")
            rename_video(entry.old_path, entry.new_path)
        except Exception as e:
            print(f"Something went wrong when attempting to rename: {e}\nOld path: {str(entry.old_path)}\nNew path: {str(entry.new_path)}", , file=sys.stderr)
            # edge case: user can inspect preserved JSON log 
            return
    
    # file is temporary on happy path
    json_path.unlink()
    return

if __name__ == "__main__":
    main()