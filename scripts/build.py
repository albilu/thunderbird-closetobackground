#!/usr/bin/env python3
"""Build reproducible XPI, runtime tarball, source archive, and Debian releases."""

import argparse
from datetime import datetime, timezone
from email.utils import format_datetime, parseaddr
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from urllib.parse import urlparse
import zipfile

sys.dont_write_bytecode = True
from integration import PACKAGE_NAME, NATIVE_FILES, SYSTEM_HELPER, SYSTEM_MANIFEST, host_manifest

ROOT = Path(__file__).resolve().parents[1]
FORMATS = ("xpi", "tar", "source", "deb")
EXTENSION_SUFFIXES = {".json", ".html", ".css", ".js", ".mjs", ".svg", ".png"}


def release_metadata(maintainer=None, homepage=None, revision=None):
    metadata = json.loads((ROOT / "packaging/release.json").read_text())
    for key, override in (("maintainer", maintainer), ("homepage", homepage), ("debian_revision", revision)):
        if override is not None:
            metadata[key] = override
    contact = metadata["maintainer"]
    if not isinstance(contact, str) or "\n" in contact or "\r" in contact or not re.fullmatch(r".+ <[^<>\s]+@[^<>\s]+>", contact):
        raise ValueError("Maintainer must be 'Name <email>' on one line")
    if not parseaddr(contact)[1]:
        raise ValueError("Invalid maintainer email")
    homepage = metadata.get("homepage")
    if homepage and (any(char.isspace() for char in homepage) or urlparse(homepage).scheme not in ("https", "http") or not urlparse(homepage).netloc):
        raise ValueError("Homepage must be an absolute HTTP(S) URL")
    if not re.fullmatch(r"[1-9][0-9]*", metadata["debian_revision"]):
        raise ValueError("Debian revision must be a positive integer")
    timestamp = datetime.fromisoformat(metadata["date"].replace("Z", "+00:00"))
    epoch = int(os.environ.get("SOURCE_DATE_EPOCH", int(timestamp.timestamp())))
    if not 315532800 <= epoch <= 4294967295:
        raise ValueError("SOURCE_DATE_EPOCH must be within the ZIP/gzip date range (1980–2106)")
    metadata["date"] = datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return metadata, epoch


def files_under(directory, suffixes):
    return [file for file in sorted((ROOT / directory).rglob("*"))
            if file.is_file() and not file.is_symlink() and file.suffix in suffixes and
            not any(part.startswith(".") or part == "__pycache__" for part in file.relative_to(ROOT).parts)]


def make_xpi(path, epoch):
    date = datetime.fromtimestamp(epoch, timezone.utc).timetuple()[:6]
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file in files_under("extension", EXTENSION_SUFFIXES):
            info = zipfile.ZipInfo(file.relative_to(ROOT / "extension").as_posix(), date)
            info.create_system = 3
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, file.read_bytes())


def make_tar(path, prefix, files, epoch):
    """files maps archive-relative paths to (bytes, mode), with fixed ownership."""
    with path.open("wb") as target, gzip.GzipFile(fileobj=target, mode="wb", filename="", mtime=epoch) as compressed:
        with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
            for name, (data, mode) in sorted(files.items()):
                info = tarfile.TarInfo(f"{prefix}/{name}")
                info.size, info.mode, info.mtime = len(data), mode, epoch
                info.uid = info.gid = 0
                info.uname = info.gname = "root"
                archive.addfile(info, io.BytesIO(data))


def runtime_readme(version, metadata):
    return (ROOT / "packaging/README.md").read_text().replace("@VERSION@", version).replace(
        "@DEBIAN_VERSION@", f"{version}-{metadata['debian_revision']}").encode()


def runtime_files(xpi, version, metadata):
    files = {xpi.name: (xpi.read_bytes(), 0o644)}
    files["README.md"] = (runtime_readme(version, metadata), 0o644)
    for name in ("LICENSE", "CHANGELOG.md", "docs/packaging.md", "docs/wayland.md", "docs/testing.md"):
        files[name] = ((ROOT / name).read_bytes(), 0o644)
    for name in NATIVE_FILES:
        files[f"native/{name}"] = ((ROOT / "native" / name).read_bytes(), 0o755 if name == "host.py" else 0o644)
    for name in ("install.py", "doctor.py", "integration.py", "policy.py"):
        files[f"scripts/{name}"] = ((ROOT / "scripts" / name).read_bytes(), 0o644)
    for name in ("install.sh", "uninstall.sh"):
        files[name] = ((ROOT / "packaging" / name).read_bytes(), 0o755)
    return files


def source_files(metadata):
    files = {}
    for name in ("README.md", "LICENSE", "CHANGELOG.md", "Makefile", "package.json", ".gitignore"):
        files[name] = ((ROOT / name).read_bytes(), 0o644)
    for directory, suffixes in (("extension", EXTENSION_SUFFIXES), ("native", {".py", ".xml"}),
                                ("scripts", {".py"}), ("tests", {".py", ".mjs", ".js", ".json"}),
                                ("docs", {".md"}), ("packaging", {".json", ".sh", ".in", ".Debian", ".1", ".md"})):
        for file in files_under(directory, suffixes):
            name = file.relative_to(ROOT).as_posix()
            files[name] = (file.read_bytes(), 0o755 if file.suffix == ".sh" or file.name == "host.py" else 0o644)
    files["packaging/debian/copyright"] = ((ROOT / "packaging/debian/copyright").read_bytes(), 0o644)
    # Embed effective build parameters so the extracted source reproduces a release
    # even when maintainer, homepage, revision, or epoch were overridden on the CLI.
    files["packaging/release.json"] = ((json.dumps(metadata, sort_keys=True, indent=2) + "\n").encode(), 0o644)
    return files


def write_file(path, data, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(mode)


def make_deb(path, xpi, version, metadata, epoch, staging):
    root = staging / "debian-root"
    share = root / "usr/share" / PACKAGE_NAME
    for name in NATIVE_FILES:
        write_file(share / "native" / name, (ROOT / "native" / name).read_bytes(), 0o755 if name == "host.py" else 0o644)
    for name in ("doctor.py", "integration.py", "policy.py"):
        write_file(share / "tools" / name, (ROOT / "scripts" / name).read_bytes(), 0o755 if name == "doctor.py" else 0o644)
    write_file(share / f"{PACKAGE_NAME}.xpi", xpi.read_bytes())
    command = root / "usr/bin" / f"{PACKAGE_NAME}-doctor"
    command.parent.mkdir(parents=True, exist_ok=True)
    command.symlink_to(f"../share/{PACKAGE_NAME}/tools/doctor.py")
    write_file(root / SYSTEM_MANIFEST.relative_to("/"), (json.dumps(host_manifest(SYSTEM_HELPER), indent=2) + "\n").encode())
    docs = root / "usr/share/doc" / PACKAGE_NAME
    write_file(docs / "README.md", runtime_readme(version, metadata))
    for name in ("CHANGELOG.md", "LICENSE"):
        write_file(docs / name, (ROOT / name).read_bytes())
    for name in ("packaging.md", "wayland.md", "testing.md"):
        write_file(docs / "docs" / name, (ROOT / "docs" / name).read_bytes())
    for name in ("copyright", "README.Debian"):
        write_file(docs / name, (ROOT / "packaging/debian" / name).read_bytes())
    debian_version = f"{version}-{metadata['debian_revision']}"
    changelog = (f"{PACKAGE_NAME} ({debian_version}) unstable; urgency=medium\n\n"
                 "  * Package the tray helper, matching XPI, and setup diagnostics.\n\n"
                 f" -- {metadata['maintainer']}  {format_datetime(datetime.fromtimestamp(epoch, timezone.utc))}\n")
    write_file(docs / "changelog.Debian.gz", gzip.compress(changelog.encode(), mtime=epoch))
    manual = ROOT / "packaging/debian" / f"{PACKAGE_NAME}-doctor.1"
    write_file(root / "usr/share/man/man1" / f"{manual.name}.gz", gzip.compress(manual.read_bytes(), mtime=epoch))
    payload = sorted(file for file in root.rglob("*") if file.is_file() and not file.is_symlink())
    size = sum((file.stat().st_size + 1023) // 1024 for file in payload)
    control = (ROOT / "packaging/debian/control.in").read_text()
    for key, value in {"DEBIAN_VERSION": debian_version, "MAINTAINER": metadata["maintainer"],
                       "INSTALLED_SIZE": str(size), "HOMEPAGE": f"Homepage: {metadata['homepage']}\n" if metadata.get("homepage") else ""}.items():
        control = control.replace(f"@{key}@", value)
    write_file(root / "DEBIAN/control", control.encode())
    for name in ('postinst', 'prerm'):
        write_file(root / 'DEBIAN' / name, (ROOT / 'packaging/debian' / f'{name}.sh').read_bytes(), 0o755)
    md5sums = "".join(f"{hashlib.md5(file.read_bytes(), usedforsecurity=False).hexdigest()}  {file.relative_to(root).as_posix()}\n" for file in payload)
    write_file(root / "DEBIAN/md5sums", md5sums.encode())
    for file in [root, *root.rglob("*")]:
        if file.is_dir():
            file.chmod(0o755)
        os.utime(file, (epoch, epoch), follow_symlinks=False)
    subprocess.run(["dpkg-deb", "--root-owner-group", "--uniform-compression", "-Zxz", "-z9",
                    "--build", str(root), str(path)], check=True, stdout=subprocess.DEVNULL,
                   env={**os.environ, "SOURCE_DATE_EPOCH": str(epoch), "LC_ALL": "C", "TZ": "UTC"})


def build(output=None, *, formats=FORMATS, maintainer=None, homepage=None, revision=None):
    formats = tuple(formats)
    if not formats or set(formats) - set(FORMATS):
        raise ValueError(f"Formats must be selected from {', '.join(FORMATS)}")
    if "deb" in formats and not shutil.which("dpkg-deb"):
        raise ValueError("Install dpkg to build .deb files, or use --formats xpi,tar,source")
    manifest = json.loads((ROOT / "extension/manifest.json").read_text())
    version = manifest["version"]
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("Release version must have the form X.Y.Z")
    if json.loads((ROOT / "package.json").read_text())["version"] != version:
        raise ValueError("package.json and extension/manifest.json versions differ")
    metadata, epoch = release_metadata(maintainer, homepage, revision)
    output = (output or ROOT / "dist" / version).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    # Build everything before exposing a new set of release artifacts.
    with tempfile.TemporaryDirectory(prefix=".release-", dir=output.parent) as directory:
        stage = Path(directory)
        prefix = f"{PACKAGE_NAME}-{version}"
        xpi = stage / f"{prefix}.xpi"
        make_xpi(xpi, epoch)
        artifacts = {"xpi": xpi} if "xpi" in formats else {}
        if "tar" in formats:
            artifacts["tar"] = stage / f"{prefix}-linux.tar.gz"
            make_tar(artifacts["tar"], prefix, runtime_files(xpi, version, metadata), epoch)
        if "source" in formats:
            artifacts["source"] = stage / f"{prefix}-source.tar.gz"
            make_tar(artifacts["source"], prefix, source_files(metadata), epoch)
        if "deb" in formats:
            artifacts["deb"] = stage / f"{PACKAGE_NAME}_{version}-{metadata['debian_revision']}_all.deb"
            make_deb(artifacts["deb"], xpi, version, metadata, epoch, stage)
        checksums = stage / "SHA256SUMS"
        checksums.write_text("".join(f"{hashlib.sha256(file.read_bytes()).hexdigest()}  {file.name}\n"
                                     for file in sorted(artifacts.values())))
        artifacts["checksums"] = checksums
        output.mkdir(parents=True, exist_ok=True)
        for key, file in artifacts.items():
            destination = output / file.name
            file.replace(destination)
            artifacts[key] = destination
    return artifacts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Release directory (default: dist/<version>)")
    parser.add_argument("--formats", default=",".join(FORMATS), help="Comma-separated subset of xpi,tar,source,deb")
    parser.add_argument("--maintainer", help="Debian maintainer: Name <email>")
    parser.add_argument("--homepage", help="Public project URL for release metadata")
    parser.add_argument("--debian-revision", help="Debian package revision (default: 1)")
    args = parser.parse_args()
    try:
        artifacts = build(args.output, formats=args.formats.split(","), maintainer=args.maintainer,
                          homepage=args.homepage, revision=args.debian_revision)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Build failed: {error}\n")
    for file in artifacts.values():
        print(file)


if __name__ == "__main__":
    main()
