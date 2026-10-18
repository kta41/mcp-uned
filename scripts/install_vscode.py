from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVER_NAME = "uned"
COPILOT_DIR = PROJECT_ROOT / "copilot"
PASSTHROUGH_ENV = ("UNED_MCP_CA_BUNDLE", "REQUESTS_CA_BUNDLE", "UNED_MCP_PROXY_CA_ORG", "UNED_STUDY_DIR", "UNED_MCP_HOME")


def main() -> None:
    parser = argparse.ArgumentParser(description="Install the UNED MCP server for VS Code.")
    parser.add_argument(
        "--with-copilot-customizations",
        action="store_true",
        help="Also install the uned-tutor agent, the /uned-* prompts and the estudio-uned skill.",
    )
    parser.add_argument("--vscode-user-dir", type=Path, default=default_vscode_user_dir(),
                        help="VS Code user profile directory containing mcp.json.")
    parser.add_argument("--skills-dir", type=Path, action="append",
                        help="Personal skills directory (repeatable). Default: ~/.copilot/skills (+ Windows profile on WSL).")
    args = parser.parse_args()

    install_mcp_config(args.vscode_user_dir, build_server_config())
    remote_dir = Path.home() / ".vscode-server" / "data" / "User"
    if remote_dir.exists() and remote_dir.resolve() != args.vscode_user_dir.resolve():
        install_mcp_config(remote_dir, build_local_server_config())

    if args.with_copilot_customizations:
        prompt_dirs = [args.vscode_user_dir / "prompts"]
        install_copilot_customizations(prompt_dirs, args.skills_dir or default_skill_dirs())

    print("UNED MCP VS Code installation completed.")
    print("First run: `uv run uned-mcp login` (SSO in the browser) and `uv run uned-mcp sync`.")


def default_vscode_user_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "Code" / "User"
    windows_user_dir = Path("/mnt/c/Users")
    username = os.environ.get("USER")
    if username and (windows_user_dir / username / "AppData" / "Roaming" / "Code" / "User").exists():
        return windows_user_dir / username / "AppData" / "Roaming" / "Code" / "User"
    return Path.home() / ".config" / "Code" / "User"


def default_skill_dirs() -> list[Path]:
    dirs = [Path.home() / ".copilot" / "skills"]
    username = os.environ.get("USER")
    win_home = Path("/mnt/c/Users") / username if username else None
    if win_home and win_home.exists():
        dirs.append(win_home / ".copilot" / "skills")
    return dirs


def install_mcp_config(vscode_user_dir: Path, server: dict[str, Any]) -> None:
    vscode_user_dir.mkdir(parents=True, exist_ok=True)
    mcp_file = vscode_user_dir / "mcp.json"
    config = read_json_object(mcp_file)
    config.setdefault("servers", {})[SERVER_NAME] = server
    write_json(mcp_file, config)
    print(f"Installed MCP server '{SERVER_NAME}' in {mcp_file}")


def runtime_env() -> dict[str, str]:
    env = {"UV_DEFAULT_INDEX": "https://pypi.org/simple"}
    for key in PASSTHROUGH_ENV:
        if os.environ.get(key):
            env[key] = os.environ[key]
    return env


def build_local_server_config() -> dict[str, Any]:
    return {
        "type": "stdio",
        "command": find_uv(),
        "args": ["--directory", str(PROJECT_ROOT), "run", "uned-mcp"],
        "env": runtime_env(),
    }


def build_server_config() -> dict[str, Any]:
    wsl_distro = detect_wsl_distro()
    if not wsl_distro:
        return build_local_server_config()
    env_args = [f"{k}={v}" for k, v in runtime_env().items()]
    return {
        "type": "stdio",
        "command": "wsl.exe",
        "args": ["-d", wsl_distro, "--", "env", *env_args, find_uv(), "--directory", str(PROJECT_ROOT), "run", "uned-mcp"],
    }


def find_uv() -> str:
    for candidate in (shutil.which("uv"), str(Path.home() / ".local" / "bin" / "uv")):
        if candidate and Path(candidate).exists():
            resolved = Path(candidate)
            # asdf shims need .tool-versions in the cwd; resolve to the real binary when possible.
            if ".asdf/shims" in str(resolved):
                try:
                    real = subprocess.run(["asdf", "which", "uv"], check=True, capture_output=True, text=True,
                                          cwd=PROJECT_ROOT).stdout.strip()
                    if real:
                        return real
                except (OSError, subprocess.CalledProcessError):
                    pass
            return str(resolved)
    return "uv"


def detect_wsl_distro() -> str | None:
    if os.environ.get("WSL_DISTRO_NAME"):
        return os.environ["WSL_DISTRO_NAME"]
    try:
        version = Path("/proc/version").read_text(encoding="utf-8").lower()
    except OSError:
        return None
    if "microsoft" not in version and "wsl" not in version:
        return None
    try:
        out = subprocess.run(["wsl.exe", "-l", "-q"], check=True, capture_output=True, text=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    distros = [line.strip().replace("\x00", "") for line in out.splitlines() if line.strip().replace("\x00", "")]
    return distros[0] if distros else None


def install_copilot_customizations(prompt_dirs: list[Path], skill_dirs: list[Path]) -> None:
    files = sorted((COPILOT_DIR / "agents").glob("*.agent.md")) + sorted((COPILOT_DIR / "prompts").glob("*.prompt.md"))
    for target_dir in prompt_dirs:
        target_dir.mkdir(parents=True, exist_ok=True)
        for source in files:
            shutil.copyfile(source, target_dir / source.name)
        print(f"Installed {len(files)} Copilot agent/prompt files in {target_dir}")
    for skills_dir in skill_dirs:
        for skill in (COPILOT_DIR / "skills").iterdir():
            if skill.is_dir():
                shutil.copytree(skill, skills_dir / skill.name, dirs_exist_ok=True)
        print(f"Installed Copilot skills in {skills_dir}")


def read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8") or "{}")
    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return data


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
