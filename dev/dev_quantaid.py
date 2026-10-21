#!/usr/bin/env python3
"""
Put this in the parent directory of where you want the Quantaid repos and run
'python dev.py' (or python3 dev.py)

This will clone any missing repos, initialize your .env files with the
values below (asking before overwriting any existing ones), install
dependencies, and launch the backend and frontend in one terminal with
prefixed output. Use Ctrl+C to stop all services.

If you simply want to launch the services without changes, run
'python dev.py -f'
"""

from __future__ import annotations

import argparse
import difflib
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

# Update vars as needed below. Ask a maintainer for the REPLACE_ME values.
_BACKEND_ENV = """\
OPENAI_API_KEY=REPLACE_ME
MONGODB_URI=mongodb://127.0.0.1:27017/quantaid-dev
MONGODB_URI_TEST=mongodb://127.0.0.1:27017/quantaid-test
ADMIN_EMAILS=REPLACE_ME
JWT_SECRET_KEY=local-dev-jwt-secret-key
ENVIRONMENT=development
CORS_ORIGINS=http://localhost:5173
IS_RICE_DEPLOYMENT=false
GOOGLE_CLIENT_ID=REPLACE_ME
#FIRST_TIME_USER_EMAIL=your-dev-forced-onboarding@email.com
"""

_FRONTEND_ENV = """\
VITE_BACKEND_URL=http://localhost:8000
"""

PLACEHOLDER = "REPLACE_ME"

# Local MongoDB for the backend (quantaid-dev) and its tests (quantaid-test)
MONGO_CONTAINER = "quantaid-mongo"

ROOT = Path(__file__).parent

RESET = "\033[0m"
BOLD = "\033[1m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
CYAN = "\033[36m"

WIN = sys.platform == "win32"


def _enable_ansi() -> None:
    if not WIN:
        return
    import ctypes

    k32 = ctypes.windll.kernel32
    h = k32.GetStdHandle(-11)
    mode = ctypes.c_ulong()
    k32.GetConsoleMode(h, ctypes.byref(mode))
    k32.SetConsoleMode(h, mode.value | 0x0004)


def _info(msg: str) -> None:
    print(f"{BOLD}[dev]{RESET} {msg}", flush=True)


def _warn(msg: str) -> None:
    print(f"{BOLD}{YELLOW}[dev]{RESET} {msg}", flush=True)


def _error(msg: str) -> None:
    print(f"{BOLD}{RED}[dev]{RESET} {msg}", flush=True)


def _getchar() -> str:
    if WIN:
        import msvcrt

        ch = msvcrt.getwch().lower()
    else:
        import termios
        import tty

        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1).lower()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    if ch == "\x03":
        raise KeyboardInterrupt
    if ch in ("\r", "\n"):
        return "n"
    return ch


def _ask(prompt: str) -> str:
    print(prompt, end="", flush=True)
    ch = _getchar()
    print(ch, flush=True)
    return ch


SERVICES: list[dict] = [
    {
        "label": "API",
        "color": BLUE,
        "repo": "quantaid-backend",
        "repo_url": "https://github.com/AB-102/quantaid-backend.git",
        "env_path": ROOT / "quantaid-backend" / ".env",
        "default_env": _BACKEND_ENV,
        "cwd": ROOT / "quantaid-backend",
        "install_cmd": ["uv", "sync"],
        "deps_dir": ".venv",
        "run_cmd": ["uv", "run", "uvicorn", "main:app", "--reload", "--port", "8000"],
        "port": 8000,
    },
    {
        "label": "WEB",
        "color": CYAN,
        "repo": "quantaid-frontend",
        "repo_url": "https://github.com/AB-102/quantaid-frontend.git",
        "env_path": ROOT / "quantaid-frontend" / "frontend" / ".env",
        "default_env": _FRONTEND_ENV,
        "cwd": ROOT / "quantaid-frontend" / "frontend",
        "install_cmd": ["npm", "install"],
        "deps_dir": "node_modules",
        "run_cmd": ["npm", "run", "dev"],
        "port": 5173,
    },
]


_INSTALL_HINTS: dict[str, str] = {
    "git": (
        "winget install Git.Git"
        if WIN
        else "brew install git"
        if sys.platform == "darwin"
        else "sudo apt-get install git"
    ),
    "uv": (
        'powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"'
        if WIN
        else "curl -LsSf https://astral.sh/uv/install.sh | sh"
    ),
    "node": (
        "winget install OpenJS.NodeJS.LTS"
        if WIN
        else "brew install node"
        if sys.platform == "darwin"
        else "curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash  (restart terminal, then: nvm install --lts)"
    ),
    "npm": "npm is included with Node.js — see the node hint",
    "docker": (
        "winget install Docker.DockerDesktop"
        if WIN
        else "brew install --cask docker"
        if sys.platform == "darwin"
        else "sudo apt-get install docker.io"
    ),
}


def _check_prerequisites() -> bool:
    missing = [t for t in ("git", "uv", "node", "npm", "docker") if not shutil.which(t)]
    if missing:
        _error(f"Missing required tools: {', '.join(missing)}")
        for tool in missing:
            _error(f"  {tool}: {_INSTALL_HINTS[tool]}")
        return False
    return True


def _tag(svc: dict) -> str:
    return f"{svc['color']}[{svc['label']}]{RESET}"


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.1)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _show_env_diff(existing: str, default: str, label: str) -> None:
    diff = difflib.unified_diff(
        existing.splitlines(),
        default.splitlines(),
        fromfile=f"Your existing {label} .env",
        tofile=f"This script's default {label} .env",
        lineterm="",
    )
    for line in diff:
        if line.startswith(("+++", "---")):
            print(f"{BOLD}{line}{RESET}")
        elif line.startswith("+"):
            print(f"{GREEN}{line}{RESET}")
        elif line.startswith("-"):
            print(f"{RED}{line}{RESET}")
        elif line.startswith("@@"):
            print(f"{YELLOW}{line}{RESET}")
        else:
            print(line)


def _parse_env(text: str) -> dict[str, str]:
    result = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, val = line.partition("=")
        result[key.strip()] = val.strip()
    return result


def _clone_repos(services: list[dict]) -> None:
    for svc in services:
        if not (ROOT / svc["repo"]).exists():
            _info(f"Cloning {svc['repo']}...")
            subprocess.run(["git", "clone", svc["repo_url"]], cwd=ROOT, check=True)


def _setup_envs(services: list[dict]) -> None:
    for svc in services:
        env_path: Path = svc["env_path"]
        tag = _tag(svc)
        if not env_path.exists():
            env_path.write_text(svc["default_env"], encoding="utf-8")
            _info(f"{tag} created .env with defaults")
            continue

        existing = env_path.read_text(encoding="utf-8")
        if _parse_env(existing) == _parse_env(svc["default_env"]):
            continue

        _show_env_diff(existing, svc["default_env"], svc["label"])
        answer = _ask(
            f"{BOLD}[dev]{RESET} {tag} .env has custom values. Overwrite with defaults? [y/N, Enter=N] "
        )
        if answer == "y":
            env_path.write_text(svc["default_env"], encoding="utf-8")
            _info(f"{tag} .env overwritten")
        else:
            _info(f"{tag} keeping existing .env")


def _warn_placeholders(services: list[dict]) -> None:
    for svc in services:
        env = _parse_env(svc["env_path"].read_text(encoding="utf-8"))
        unfilled = [key for key, val in env.items() if val == PLACEHOLDER]
        if unfilled:
            _warn(
                f"{_tag(svc)} fill in these values in {svc['env_path']}: {', '.join(unfilled)}"
            )


def _deps_exist(svc: dict) -> bool:
    return (svc["cwd"] / svc["deps_dir"]).exists()


def _install_deps(services: list[dict]) -> None:
    all_installed = all(_deps_exist(svc) for svc in services)
    if (
        all_installed
        and _ask(f"{BOLD}[dev]{RESET} Reinstall all dependencies? [y/N, Enter=N] ")
        != "y"
    ):
        _info("Skipping dependency install")
        return
    for svc in services:
        tag = _tag(svc)
        _info(f"{tag} installing dependencies...")
        cmd = svc["install_cmd"]
        try:
            subprocess.run(
                " ".join(cmd) if WIN else cmd, cwd=svc["cwd"], shell=WIN, check=True
            )
        except subprocess.CalledProcessError:
            _error(
                f"{tag} install failed — try deleting {svc['cwd'] / svc['deps_dir']} and running again"
            )


def _start_mongo() -> None:
    """Start the local MongoDB that dev and tests share, creating its container the first time."""
    started = subprocess.run(
        ["docker", "start", MONGO_CONTAINER], check=False, capture_output=True
    )
    if started.returncode == 0:
        _info(f"MongoDB running in Docker container '{MONGO_CONTAINER}'")
        return
    _info(f"Creating MongoDB Docker container '{MONGO_CONTAINER}'...")
    try:
        subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                MONGO_CONTAINER,
                "-p",
                "127.0.0.1:27017:27017",
                "mongo:7",
            ],
            check=True,
        )
    except subprocess.CalledProcessError:
        _error(
            "Could not start MongoDB in Docker — is Docker running, and is port 27017 free?"
            " (Stop any older container on it, e.g. docker stop quantaid-test-mongo)"
        )
        sys.exit(1)


def _stream(stream, prefix: str) -> None:
    try:
        for line in stream:
            print(prefix + line.rstrip(), flush=True)
    except (ValueError, OSError):
        pass


def _terminate(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if WIN:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            check=False,
            capture_output=True,
        )
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass


def _launch(services: list[dict]) -> None:
    for svc in services:
        if _port_in_use(svc["port"]):
            _warn(
                f"Port {svc['port']} already in use — {svc['label']} may fail to start"
            )

    procs: list[subprocess.Popen] = []
    for svc in services:
        cmd = svc["run_cmd"]
        kwargs: dict = {
            "cwd": svc["cwd"],
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
        }
        if WIN:
            proc = subprocess.Popen(
                " ".join(cmd),
                shell=True,
                stdin=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                **kwargs,
            )
        else:
            proc = subprocess.Popen(cmd, start_new_session=True, **kwargs)

        threading.Thread(
            target=_stream, args=(proc.stdout, f"{_tag(svc)} "), daemon=True
        ).start()
        procs.append(proc)
        _info(f"{_tag(svc)} started on http://localhost:{svc['port']}")

    _info(
        f"{BOLD}All servers running. API docs at http://localhost:8000/docs. Ctrl+C to stop.{RESET}"
    )

    exited: set[int] = set()
    try:
        while True:
            for i, proc in enumerate(procs):
                if i not in exited and proc.poll() is not None:
                    exited.add(i)
                    _warn(
                        f"[{services[i]['label']}] exited with code {proc.returncode}"
                    )
            if len(exited) == len(procs):
                _warn("All servers have stopped.")
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        print()
        _info("Shutting down...")
    finally:
        for proc in procs:
            _terminate(proc)
        for proc in procs:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


def main() -> None:
    _enable_ansi()

    parser = argparse.ArgumentParser(
        description="Start the Quantaid backend and frontend dev servers"
    )
    parser.add_argument("-f", action="store_true", help="skip all changes and launch")
    args = parser.parse_args()

    if not _check_prerequisites():
        sys.exit(1)

    if not args.f:
        try:
            _clone_repos(SERVICES)
            _setup_envs(SERVICES)
            _install_deps(SERVICES)
        except KeyboardInterrupt:
            print()
            _info("Aborted.")
            sys.exit(0)

    _warn_placeholders(SERVICES)
    _start_mongo()
    _launch(SERVICES)


if __name__ == "__main__":
    main()
