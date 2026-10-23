# rename_obs_videos.py

## Pipeline approach

```mermaid
flowchart LR
    A[Parse CLI Arguments]
    A --> B[Find Game Folders]
    B --> C{Folders Found?}
    C -->|No| R{--include-root Set?}
    C -->|Yes| D{--whitelist Set?}
    D -->|Yes| E[Filter to Whitelisted Folders]
    D -->|No| F[Prompt Interactive Selection]
    E --> G[Find Matching Videos]
    F --> G
    R -->|No| Z[End]
    R -->|Yes| G
    G --> H{Videos Found?}
    H -->|No| Z
    H -->|Yes| I{Next Video?}
    I -->|No| Z
    I -->|Yes| J[Compute New Path]
    J --> K[Rename Video]
    K --> L{Rename Successful?}
    L -->|No| Z
    L -->|Yes| I
```

I initially leaned toward a plan-apply approach that provided a full plan with a saved JSON file where the user could receive a confirmation prompt before executing renames and that plan would be left as a log or instructions for a future rollback implementation. However, a pipeline approach dropping the JSON file was chosen because having all inputs able to be committed upfront via CLI arguments better fits real workflows, individual renames are atomic filesystem operations leaving no complex partial state, a .log file provides a sufficient audit trail, and how rare rollbacks for this use case would be in practice.

# trim_overlapping_videos.py

## Pipeline approach

```mermaid
flowchart LR
    A[Parse CLI Arguments] --> B[Find Game Folders]
    B --> C{Folders Found?}
    C -->|No| Z[End]
    C -->|Yes| D[Confirm Every Folder Upfront]
    D --> E{Any Selected?}
    E -->|No| Z
    E -->|Yes| F{Next Folder?}
    F -->|No| Z
    F -->|Yes| G[Pattern Match & Sort Folder Clips, Trimmed Replacing Originals]
    G --> H{Next Pair?}
    H -->|No| F
    H -->|Yes| I{Latter Already Trimmed?}
    I -->|Yes| H
    I -->|No| J[Probe Latter Duration]
    J --> K{Probe Successful?}
    K -->|No| Z
    K -->|Yes| L[Calculate Overlap]
    L --> M{Overlap Detected?}
    M -->|No| H
    M -->|Yes| N{Leeway-Adjusted Trim > 0?}
    N -->|No| H
    N -->|Yes| O{Enough Space?}
    O -->|No| Z
    O -->|Yes| P[Trim Latter With Exclusion Suffix]
    P --> Q{Trim Successful?}
    Q -->|No| Z
    Q -->|Yes| R{Deletion Flag Set?}
    R -->|Yes| S[Delete Original Latter]
    S --> H
    R -->|No| H
```

## Data structure

```mermaid
classDiagram
    class VideoClip {
        +Path path
        +datetime end_time
        +datetime start_time
        +timedelta duration
    }
```

Besides general advantages like speed optimization and avoiding plans that can become stale, I chose a pipeline approach because rollback is not possible with file deletion and never re-trimming files with the output suffix (or their originals) is our idempotent guarantee. Trimmed files still stay in the timeline in place of their originals so each clip is compared against its true predecessor, which keeps a run that stopped partway (disk space, ffmpeg error, Ctrl+C) safe to resume. Only the latter clip of a pair is probed for its duration since the former only needs the end time in its name. Clips are grouped by the folder they directly sit in rather than recursively, so running from inside a single game folder works and a root folder holding loose `Replay_` clips never pulls its subfolders' clips into the same timeline. There would still be a TOC/TOU issue when checking for available space while running each subdirectory in parallel, so we'll use sequential execution by default for now. There is also room for greedy lookahead optimization in the future with videos that are fully overlapped by a preceding and succeeding video. I also thought we could potentially utilize the fact that successive replays likely have the same duration set in OBS but I found out that the resulting duration can be off target by up to around 3 seconds.

I dropped the `--whitelist`/numbered-selection flow from the renamer in favor of a per-folder `[y/N]` confirmation prompt. Non-interactive automation makes sense for a reversible rename, but this script permanently deletes footage when `--delete-originals` is set, so an explicit confirmation for each folder, all asked before any folder is touched, fits the risk better than an upfront CLI flag. `--delete-originals` still defaults to off. A `TRIM_LEEWAY_SECONDS` constant (0.5s) is subtracted from the detected overlap before trimming, so a small buffer of duplicate frames is deliberately left at the start of the latter clip instead of cutting exactly on the boundary so editors have room to stitch clips together without dropped frames. Clips are sorted by their parsed timestamp rather than filename string, since a folder can mix already-renamed and not yet renamed files whose prefixes don't sort chronologically together.