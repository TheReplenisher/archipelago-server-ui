"""Open or update one issue per Archipelago version newer than the one we pin.

Run by .github/workflows/archipelago-releases.yml. The pinned version is the Dockerfile's
`ARG AP_VERSION=`. Release candidates count, so an upgrade can be tested before the final
release ships. Uses the `gh` CLI (GH_TOKEN in the environment).

    python3 .github/scripts/archipelago_releases.py [--dry-run] [--pinned 0.6.7]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

UPSTREAM = "ArchipelagoMW/Archipelago"
LABELS = ["upstream", "area:install"]
ASSIGNEE = "TheReplenisher"
DOCKERFILE = Path(__file__).resolve().parents[2] / "Dockerfile"
TAG_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-rc(\d+))?$")


@dataclass(frozen=True)
class Release:
    tag: str
    url: str
    published: str
    base: str  # "0.6.9" for both 0.6.9-rc1 and 0.6.9
    key: tuple[int, int, int, int]  # rc N sorts as N, the final release above every rc

    @property
    def is_rc(self) -> bool:
        return "-rc" in self.tag

    @property
    def marker(self) -> str:
        return f"<!-- ap-release:{self.tag} -->"

    def line(self) -> str:
        kind = "release candidate" if self.is_rc else "**release**"
        return f"- [{self.tag}]({self.url}): {kind}, {self.published[:10]} {self.marker}"


def version_key(tag: str) -> tuple[int, int, int, int] | None:
    m = TAG_RE.match(tag)
    if not m:
        return None
    major, minor, patch, rc = m.groups()
    return (int(major), int(minor), int(patch), int(rc) if rc else 10**6)


def gh(*args: str) -> str:
    # Fixed argv, no shell; args come from this script and the GitHub API.
    return subprocess.run(  # noqa: S603
        ["gh", *args],  # noqa: S607 - gh is on PATH on GitHub runners
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def pinned_version() -> str:
    m = re.search(r"^ARG AP_VERSION=(\S+)$", DOCKERFILE.read_text(), re.MULTILINE)
    if not m:
        sys.exit(f"no 'ARG AP_VERSION=' in {DOCKERFILE}")
    return m.group(1)


def upstream_releases() -> list[Release]:
    raw = json.loads(gh("api", f"repos/{UPSTREAM}/releases?per_page=30"))
    releases = []
    for r in raw:
        key = version_key(r["tag_name"])
        if key is None or r["draft"]:
            continue
        base = r["tag_name"].split("-")[0]
        releases.append(Release(r["tag_name"], r["html_url"], r["published_at"], base, key))
    return sorted(releases, key=lambda r: r.key)


def version_marker(base: str) -> str:
    return f"<!-- ap-version:{base} -->"


def issue_body(base: str, pinned: str, releases: list[Release]) -> str:
    seen = "\n".join(r.line() for r in releases)
    return f"""{version_marker(base)}
Archipelago **{base}** is on its way or out. We pin **{pinned}** (the Dockerfile's \
`ARG AP_VERSION`). This issue is opened and updated by the *Archipelago releases* workflow.

### Seen so far
{seen}

### Upgrade checklist
- [ ] Read the release notes for server, protocol, command, host.yaml and world changes
- [ ] Set `ARG AP_VERSION` in the Dockerfile; CI's smoke test must show every built-in \
world loading on amd64 and arm64
- [ ] Re-check `docker/install-archipelago.sh`: new or changed world requirements, arm64 \
wheels, and whether the exclusions still hold
- [ ] Command catalog (#7, #26) and host.yaml settings (#9, #25) still match
- [ ] Update "currently targeting" in DESIGN.md
- [ ] Emulated arm64 run (#60) before the next release of this project
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="print, don't touch issues")
    parser.add_argument("--pinned", help="pretend this version is pinned (for testing)")
    args = parser.parse_args()

    pinned = args.pinned or pinned_version()
    pinned_key = version_key(pinned)
    if pinned_key is None:
        sys.exit(f"pinned version {pinned!r} isn't an Archipelago release tag")

    newer = [r for r in upstream_releases() if r.key > pinned_key]
    if not newer:
        print(f"pinned {pinned} is current")
        return

    issues = json.loads(
        gh(
            "issue",
            "list",
            "--label",
            "upstream",
            "--state",
            "all",
            "--limit",
            "200",
            "--json",
            "number,body,state",
        )
    )

    for base in sorted({r.base for r in newer}, key=lambda b: version_key(b) or ()):
        releases = [r for r in newer if r.base == base]
        issue = next((i for i in issues if version_marker(base) in i["body"]), None)

        if issue is None:
            title = f"Upgrade to Archipelago {base}"
            print(f"create: {title} ({', '.join(r.tag for r in releases)})")
            if not args.dry_run:
                command = [
                    "issue",
                    "create",
                    "--title",
                    title,
                    "--assignee",
                    ASSIGNEE,
                    "--body",
                    issue_body(base, pinned, releases),
                ]
                for label in LABELS:
                    command += ["--label", label]
                gh(*command)
            continue

        known = issue["body"] + "".join(
            c["body"]
            for c in json.loads(gh("issue", "view", str(issue["number"]), "--json", "comments"))[
                "comments"
            ]
        )
        for release in releases:
            if release.marker in known:
                continue
            print(f"comment on #{issue['number']}: {release.tag}")
            if not args.dry_run:
                gh(
                    "issue",
                    "comment",
                    str(issue["number"]),
                    "--body",
                    f"New upstream {release.line()[2:]}",
                )


if __name__ == "__main__":
    main()
