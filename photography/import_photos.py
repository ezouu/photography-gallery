#!/usr/bin/env python3
"""Import untouched image files into the gallery. Requires only Python 3.9+."""

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import zipfile
from contextlib import ExitStack
from pathlib import Path, PurePosixPath

SUPPORTED = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif", ".bmp"}
NEEDS_CONVERSION = {
    ".heic", ".heif", ".tif", ".tiff", ".raw", ".dng", ".cr2", ".cr3",
    ".nef", ".nrw", ".arw", ".srf", ".sr2", ".orf", ".rw2", ".raf",
    ".pef", ".ptx", ".rwl", ".3fr", ".fff", ".iiq", ".kdc", ".dcr",
    ".mrw", ".mos", ".mef", ".srw", ".x3f", ".erf", ".jxl", ".psd", ".psb",
}


class ImportErrorMessage(Exception):
    pass


def natural_key(name):
    """Sort 2 before 10, with stable case-sensitive tie breaking."""
    parts = re.split(r"(\d+)", name.casefold())
    return tuple((1, int(part)) if part.isdigit() else (0, part) for part in parts), name


def hidden(name):
    return any(part == "__MACOSX" or part.startswith(".") for part in PurePosixPath(name).parts)


def safe_archive_name(name):
    normalized = name.replace("\\", "/")
    parts = PurePosixPath(normalized).parts
    if (
        not normalized or "\x00" in normalized or normalized.startswith("/")
        or any(part == ".." for part in parts)
        or (parts and re.match(r"^[a-zA-Z]:", parts[0]))
    ):
        raise ImportErrorMessage(f"Unsafe archive path: {name!r}. No files were imported.")
    return normalized


def discover(source, stack, gallery):
    """Return (relative name, opener) pairs without extracting archive paths."""
    found = []
    unsupported = []
    if source.is_dir():
        if source.resolve() == gallery.resolve():
            raise ImportErrorMessage("Choose the original photo directory, not the gallery directory.")
        for directory, dirs, files in os.walk(source, followlinks=False):
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d != "__MACOSX")
            for d in dirs:
                if (Path(directory) / d).is_symlink():
                    raise ImportErrorMessage(f"Symbolic links are not accepted: {Path(directory) / d}")
            for filename in sorted(files):
                path = Path(directory) / filename
                name = path.relative_to(source).as_posix()
                if hidden(name):
                    continue
                suffix = path.suffix.lower()
                if suffix not in SUPPORTED | NEEDS_CONVERSION:
                    continue
                if path.is_symlink():
                    raise ImportErrorMessage(f"Symbolic links are not accepted: {path}")
                if not path.is_file():
                    raise ImportErrorMessage(f"Only regular photo files are accepted: {path}")
                if suffix in NEEDS_CONVERSION:
                    unsupported.append(name)
                else:
                    found.append((name, lambda p=path: p.open("rb")))
    elif source.is_file() and zipfile.is_zipfile(source):
        archive = stack.enter_context(zipfile.ZipFile(source))
        names = set()
        for member in archive.infolist():
            name = safe_archive_name(member.filename)
            mode = member.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ImportErrorMessage(f"Symbolic links are not accepted in archives: {name!r}")
            if member.is_dir() or hidden(name):
                continue
            suffix = PurePosixPath(name).suffix.lower()
            if suffix not in SUPPORTED | NEEDS_CONVERSION:
                continue
            if name in names:
                raise ImportErrorMessage(f"Duplicate archive path: {name!r}. Re-create the archive with unique paths.")
            names.add(name)
            if mode and stat.S_IFMT(mode) not in (0, stat.S_IFREG):
                raise ImportErrorMessage(f"Only regular photo files are accepted: {name!r}")
            if suffix in NEEDS_CONVERSION:
                unsupported.append(name)
            else:
                found.append((name, lambda a=archive, m=member: a.open(m, "r")))
    else:
        raise ImportErrorMessage(f"Expected a ZIP archive or photo directory: {source}")
    return found, unsupported


def digest_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checked_photo_path(gallery, src):
    if not isinstance(src, str):
        raise ImportErrorMessage("Existing manifest has an invalid photo path.")
    path = PurePosixPath(src)
    if path.is_absolute() or len(path.parts) != 2 or path.parts[0] != "photos" or ".." in path.parts:
        raise ImportErrorMessage(f"Existing manifest has an unsafe photo path: {src!r}")
    local = gallery / src
    if local.is_symlink() or not local.is_file() or local.resolve().parent != (gallery / "photos").resolve():
        raise ImportErrorMessage(f"Existing gallery photo is missing or unsafe: {src}")
    return local


def existing_photos(gallery):
    manifest_path = gallery / "photos.json"
    state_path = gallery / ".photo-import.json"
    manifest = json.loads(manifest_path.read_text("utf-8")) if manifest_path.exists() else []
    if not isinstance(manifest, list) or any(not isinstance(item, dict) for item in manifest):
        raise ImportErrorMessage("Existing photos.json must contain an array of photo objects.")
    if state_path.exists():
        state = json.loads(state_path.read_text("utf-8"))
        if not isinstance(state, dict) or state.get("version") != 1 or not isinstance(state.get("photos"), list):
            raise ImportErrorMessage("Existing .photo-import.json has an unsupported format.")
        records = state["photos"]
        if any(not isinstance(item, dict) for item in records):
            raise ImportErrorMessage("Existing import metadata contains an invalid photo object.")
        expected = [{"src": item.get("src"), "alt": item.get("alt")} for item in records]
        if manifest != expected:
            raise ImportErrorMessage("photos.json differs from its import metadata. Restore the matching files before importing.")
    else:
        records = [dict(item, source_name=PurePosixPath(item.get("src", "")).name) for item in manifest]
    result = []
    seen = set()
    for item in records:
        src = item.get("src")
        if src in seen:
            raise ImportErrorMessage("Existing photos.json contains duplicate paths.")
        seen.add(src)
        if not isinstance(item.get("alt"), str) or not isinstance(item.get("source_name"), str):
            raise ImportErrorMessage("Existing gallery metadata has invalid text fields.")
        digest = digest_file(checked_photo_path(gallery, src))
        if item.get("sha256", digest) != digest:
            raise ImportErrorMessage(f"Existing photo has changed: {src}. Restore it before importing.")
        result.append(dict(item, sha256=digest))
    return result


def file_name(source_name, digest):
    path = PurePosixPath(source_name)
    stem = re.sub(r"[^\w.-]+", "-", path.stem, flags=re.UNICODE).strip(".-")[:80] or "photo"
    # File-system limits count bytes; long CJK names need a shorter stem.
    stem = stem.encode("utf-8")[:160].decode("utf-8", errors="ignore").strip(".-") or "photo"
    return f"{stem}-{digest}{path.suffix.lower()}"


def encode_json(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def import_photos(sources, gallery):
    if (gallery / "photos").is_symlink():
        raise ImportErrorMessage("The gallery photos directory must not be a symbolic link.")
    for name in ("photos.json", ".photo-import.json"):
        if (gallery / name).is_symlink():
            raise ImportErrorMessage(f"The gallery {name} file must not be a symbolic link.")
    with ExitStack() as stack:
        candidates = []
        unsupported = []
        for source in sources:
            found, needs_conversion = discover(source, stack, gallery)
            candidates.extend(found)
            unsupported.extend(needs_conversion)
        if unsupported:
            listing = "\n".join(f"  {name}" for name in sorted(unsupported, key=natural_key))
            raise ImportErrorMessage(
                "These photographic formats need conversion to JPEG, PNG, WebP, or AVIF before browser display:\n"
                + listing + "\nNo gallery files were changed. Export at full resolution and highest quality."
            )
        if not candidates:
            raise ImportErrorMessage("No supported photos were found. Accepted formats: JPEG, PNG, WebP, AVIF, GIF, BMP.")
        records = existing_photos(gallery)
        known = {item["sha256"] for item in records}
        gallery.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".photo-import-", dir=gallery) as temporary:
            staging = Path(temporary)
            additions = []
            for index, (name, opener) in enumerate(sorted(candidates, key=lambda item: natural_key(item[0]))):
                staged = staging / str(index)
                digest = hashlib.sha256()
                with opener() as original, staged.open("wb") as output:
                    for chunk in iter(lambda: original.read(1024 * 1024), b""):
                        digest.update(chunk)
                        output.write(chunk)
                checksum = digest.hexdigest()
                if checksum in known:
                    staged.unlink()
                    continue
                src = "photos/" + file_name(name, checksum)
                destination = gallery / src
                if destination.exists():
                    if destination.is_symlink() or not destination.is_file() or digest_file(destination) != checksum:
                        raise ImportErrorMessage(f"An existing file would be overwritten: {src}")
                    staged.unlink()
                else:
                    additions.append((staged, destination))
                known.add(checksum)
                records.append({"src": src, "alt": PurePosixPath(name).stem, "source_name": name, "sha256": checksum})
            records.sort(key=lambda item: (natural_key(item["source_name"]), item["sha256"]))
            manifest = [{"src": item["src"], "alt": item["alt"]} for item in records]
            updates = {
                gallery / ".photo-import.json": encode_json({"version": 1, "photos": records}),
                gallery / "photos.json": encode_json(manifest),
            }
            # Stage and validate everything before making any gallery changes.
            updates = {path: data for path, data in updates.items() if not path.exists() or path.read_bytes() != data}
            backups = {path: path.read_bytes() if path.exists() else None for path in updates}
            for index, (path, data) in enumerate(updates.items()):
                (staging / f"metadata-{index}").write_bytes(data)
            installed = []
            changed = []
            photos_dir = gallery / "photos"
            created_photos_dir = not photos_dir.exists()
            try:
                photos_dir.mkdir(exist_ok=True)
                for staged, destination in additions:
                    # Hard links fail if another importer created this name: never overwrite.
                    os.link(staged, destination)
                    installed.append(destination)
                for index, path in enumerate(updates):
                    os.replace(staging / f"metadata-{index}", path)
                    changed.append(path)
            except BaseException:
                for path in reversed(changed):
                    data = backups[path]
                    if data is None:
                        path.unlink(missing_ok=True)
                    else:
                        rollback = staging / "rollback"
                        rollback.write_bytes(data)
                        os.replace(rollback, path)
                for path in installed:
                    path.unlink(missing_ok=True)
                if created_photos_dir:
                    photos_dir.rmdir()
                raise
        return len(manifest), len(additions)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", nargs="+", type=Path, help="ZIP archives and/or directories containing original photos")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent, help="gallery directory (default: beside this script)")
    args = parser.parse_args()
    try:
        total, added = import_photos(args.sources, args.output)
    except (ImportErrorMessage, OSError, ValueError, KeyError, TypeError, RuntimeError, zipfile.BadZipFile) as error:
        print(f"Import failed: {error}", file=sys.stderr)
        return 1
    print(f"Imported {added} new original photo(s); gallery contains {total}. No image bytes were changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
