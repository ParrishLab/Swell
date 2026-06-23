#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tomllib
import xml.etree.ElementTree as ET


SPARKLE_NS = "http://www.andymatuschak.org/xml-namespaces/sparkle"
ET.register_namespace("sparkle", SPARKLE_NS)


@dataclass(frozen=True)
class ArtifactSpec:
    platform: str
    artifact_path: Path
    output_path: Path
    download_url: str
    signature_path: Path | None = None


def _load_project_version(repo_root: Path) -> str:
    pyproject_path = repo_root / "pyproject.toml"
    with pyproject_path.open("rb") as handle:
        payload = tomllib.load(handle)
    return str(payload["project"]["version"])


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_signature(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        "ed_signature": str(payload["ed_signature"]),
        "length": int(payload["length"]),
    }


def _build_item(
    *,
    title: str,
    version: str,
    notes_url: str,
    download_url: str,
    artifact_path: Path,
    published_at: str,
    signature_path: Path | None = None,
) -> ET.Element:
    item = ET.Element("item")
    ET.SubElement(item, "title").text = title
    ET.SubElement(item, "pubDate").text = published_at
    ET.SubElement(item, f"{{{SPARKLE_NS}}}releaseNotesLink").text = notes_url
    enclosure_attrs = {
        "url": download_url,
        "length": str(artifact_path.stat().st_size),
        "type": "application/octet-stream",
        f"{{{SPARKLE_NS}}}version": version,
        f"{{{SPARKLE_NS}}}shortVersionString": version,
        f"{{{SPARKLE_NS}}}sha256": _sha256(artifact_path),
    }
    if signature_path is not None:
        signature = _load_signature(signature_path)
        enclosure_attrs["length"] = str(signature["length"])
        enclosure_attrs[f"{{{SPARKLE_NS}}}edSignature"] = str(signature["ed_signature"])
    ET.SubElement(
        item,
        "enclosure",
        attrib=enclosure_attrs,
    )
    return item


def generate_appcasts(
    *,
    repo_root: Path,
    release_tag: str,
    github_repo: str,
    dist_dir: Path,
    output_dir: Path,
    published_at: str | None = None,
) -> list[Path]:
    version = _load_project_version(repo_root)
    stable_tag = str(release_tag).strip()
    if stable_tag != f"v{version}":
        raise RuntimeError(f"Release tag/version mismatch: tag={stable_tag} version={version}")

    release_page_url = f"https://github.com/{github_repo}/releases/tag/{stable_tag}"
    download_base_url = f"https://github.com/{github_repo}/releases/download/{stable_tag}"
    published = published_at or datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
    windows_installer = next(iter(sorted(dist_dir.glob("Swell-Setup-*.exe"))), None)

    specs = [
        ArtifactSpec(
            platform="macos",
            artifact_path=dist_dir / "swell-macos-arm64.zip",
            output_path=output_dir / "appcast-macos.xml",
            download_url=f"{download_base_url}/swell-macos-arm64.zip",
            signature_path=dist_dir / "swell-macos-arm64-signature.json",
        ),
        ArtifactSpec(
            platform="windows",
            artifact_path=windows_installer or (dist_dir / "Swell-Setup-missing.exe"),
            output_path=output_dir / "appcast-windows.xml",
            download_url=f"{download_base_url}/{windows_installer.name if windows_installer else 'Swell-Setup-missing.exe'}",
        ),
    ]

    outputs: list[Path] = []
    for spec in specs:
        if not spec.artifact_path.exists():
            raise RuntimeError(f"Missing updater artifact for {spec.platform}: {spec.artifact_path}")
        if spec.signature_path is not None and not spec.signature_path.exists():
            raise RuntimeError(f"Missing signature metadata for {spec.platform}: {spec.signature_path}")
        rss = ET.Element("rss", attrib={"version": "2.0"})
        channel = ET.SubElement(rss, "channel")
        ET.SubElement(channel, "title").text = f"Swell {spec.platform} stable releases"
        ET.SubElement(channel, "link").text = release_page_url
        channel.append(
            _build_item(
                title=f"Swell {version}",
                version=version,
                notes_url=release_page_url,
                download_url=spec.download_url,
                artifact_path=spec.artifact_path,
                published_at=published,
                signature_path=spec.signature_path,
            )
        )
        tree = ET.ElementTree(rss)
        spec.output_path.parent.mkdir(parents=True, exist_ok=True)
        tree.write(spec.output_path, encoding="utf-8", xml_declaration=True)
        outputs.append(spec.output_path)
    return outputs


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate stable appcast feeds for packaged release artifacts.")
    parser.add_argument("--repo-root", default=None, help="Repository root path.")
    parser.add_argument("--dist-dir", default="dist", help="Directory containing release artifacts.")
    parser.add_argument("--output-dir", default="dist", help="Directory for generated appcasts.")
    parser.add_argument("--release-tag", required=True, help="Release tag in vX.Y.Z format.")
    parser.add_argument("--github-repo", required=True, help="GitHub repo in owner/name form.")
    parser.add_argument("--published-at", default=None, help="RFC-2822 publication timestamp.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = Path(args.repo_root).expanduser().resolve() if args.repo_root else Path(__file__).resolve().parents[2]
    outputs = generate_appcasts(
        repo_root=repo_root,
        release_tag=str(args.release_tag),
        github_repo=str(args.github_repo),
        dist_dir=(repo_root / str(args.dist_dir)).resolve(),
        output_dir=(repo_root / str(args.output_dir)).resolve(),
        published_at=str(args.published_at) if args.published_at else None,
    )
    for output in outputs:
        print(f"APPCAST_WRITTEN:{output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
