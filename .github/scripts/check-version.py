from __future__ import annotations

import json
import os
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEMVER_PATTERN = re.compile(r"\d+\.\d+\.\d+")


def read_json(relative_path: str) -> dict[str, object]:
    with (ROOT / relative_path).open(encoding="utf-8") as handle:
        return json.load(handle)


def require_string(value: object, source: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{source} does not contain a valid version string")
    return value


def collect_versions() -> dict[str, str]:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)

    plugin_source = (ROOT / "src/endstone_stoneperms/version.py").read_text(encoding="utf-8")
    plugin_match = re.fullmatch(r'\s*VERSION\s*=\s*["\']([^"\']+)["\']\s*', plugin_source)
    if plugin_match is None:
        raise ValueError("src/endstone_stoneperms/version.py must contain only VERSION = \"<version>\"")

    api_package = read_json("api/package.json")
    api_lock = read_json("api/package-lock.json")
    dashboard_package = read_json("dashboard/package.json")
    dashboard_lock = read_json("dashboard/package-lock.json")

    api_lock_packages = api_lock.get("packages")
    dashboard_lock_packages = dashboard_lock.get("packages")
    if not isinstance(api_lock_packages, dict) or not isinstance(api_lock_packages.get(""), dict):
        raise ValueError("api/package-lock.json is missing the root package metadata")
    if not isinstance(dashboard_lock_packages, dict) or not isinstance(
        dashboard_lock_packages.get(""), dict
    ):
        raise ValueError("dashboard/package-lock.json is missing the root package metadata")

    project_metadata = project.get("project")
    if not isinstance(project_metadata, dict):
        raise ValueError("pyproject.toml is missing [project] metadata")

    return {
        "pyproject.toml": require_string(project_metadata.get("version"), "pyproject.toml"),
        "src/endstone_stoneperms/version.py": plugin_match.group(1),
        "api/package.json": require_string(api_package.get("version"), "api/package.json"),
        "api/package-lock.json": require_string(api_lock.get("version"), "api/package-lock.json"),
        "api/package-lock.json packages root": require_string(
            api_lock_packages[""].get("version"), "api/package-lock.json packages root"
        ),
        "dashboard/package.json": require_string(
            dashboard_package.get("version"), "dashboard/package.json"
        ),
        "dashboard/package-lock.json": require_string(
            dashboard_lock.get("version"), "dashboard/package-lock.json"
        ),
        "dashboard/package-lock.json packages root": require_string(
            dashboard_lock_packages[""].get("version"),
            "dashboard/package-lock.json packages root",
        ),
    }


def write_github_outputs(version: str) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return

    with Path(output_path).open("a", encoding="utf-8") as handle:
        handle.write(f"version={version}\n")
        handle.write(f"tag=v{version}\n")


def main() -> int:
    try:
        versions = collect_versions()
        canonical_version = versions["pyproject.toml"]

        if SEMVER_PATTERN.fullmatch(canonical_version) is None:
            raise ValueError(
                f"Version {canonical_version!r} is not release-compatible SemVer (expected X.Y.Z)"
            )

        mismatches = {
            source: version for source, version in versions.items() if version != canonical_version
        }
        if mismatches:
            details = "\n".join(
                f"  - {source}: {version}" for source, version in sorted(versions.items())
            )
            raise ValueError(f"StonePerms versions are not synchronized:\n{details}")

        write_github_outputs(canonical_version)
        print(f"StonePerms version {canonical_version} is synchronized across all package metadata.")
        return 0
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        tomllib.TOMLDecodeError,
    ) as error:
        print(f"Version check failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
