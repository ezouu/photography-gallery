#!/usr/bin/env python3
"""Build a clean static gallery without resizing or recompressing photographs.

Only the site's HTML, CSS, JavaScript, manifest, and referenced photos are
published. Optional originals are imported into temporary staging; the source
gallery is never changed. The output directory is replaced after validation.
Requires Python 3.9+ and no third-party packages.
"""

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import zipfile
from contextlib import ExitStack
from pathlib import Path, PurePosixPath


SITE_FILES = ("index.html", "styles.css", "gallery.js", "photos.json")
PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif", ".bmp"}


class BuildError(Exception):
    pass


def regular_file(gallery, relative):
    """Reject symbolic links, including links in any path component."""
    path = gallery
    for part in PurePosixPath(relative).parts:
        path = path / part
        if path.is_symlink():
            raise BuildError(f"Symbolic links cannot be published: {relative}")
    if not path.is_file() or not path.resolve().is_relative_to(gallery.resolve()):
        raise BuildError(f"Required file is missing or unsafe: {relative}")
    return path


def photo_manifest(gallery):
    manifest_file = regular_file(gallery, "photos.json")
    manifest = json.loads(manifest_file.read_text("utf-8"))
    if not isinstance(manifest, list):
        raise BuildError("photos.json must contain an array of photo objects.")
    seen = set()
    for photo in manifest:
        if not isinstance(photo, dict) or not isinstance(photo.get("alt"), str):
            raise BuildError("Every photograph needs string src and alt fields.")
        src = photo.get("src")
        if not isinstance(src, str) or not src:
            raise BuildError("Every photograph needs string src and alt fields.")
        path = PurePosixPath(src)
        if (
            path.is_absolute() or len(path.parts) < 2 or path.parts[0] != "photos"
            or path.as_posix() != src or any(part.startswith(".") for part in path.parts)
            or any(character in src for character in "\\%?#:")
            or any(ord(character) < 32 or ord(character) == 127 for character in src)
            or path.suffix.lower() not in PHOTO_EXTENSIONS
        ):
            raise BuildError(f"Unsafe or unsupported photograph path: {src!r}")
        if src in seen:
            raise BuildError(f"Duplicate photograph path: {src}")
        seen.add(src)
        regular_file(gallery, src)
    return manifest


def digest(path):
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.digest()


def checked_copy(gallery, relative, destination):
    original = regular_file(gallery, relative)
    before = digest(original)
    target = destination / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(original, target)
    if digest(target) != before or digest(original) != before:
        raise BuildError(f"Byte verification failed for {relative}; build not published.")
    return target.stat().st_size


def build(gallery, output, originals=None):
    gallery = gallery.resolve()
    output = output.absolute()
    resolved_output = output.resolve()
    if gallery.is_relative_to(resolved_output):
        raise BuildError("The output directory cannot replace the source gallery or its ancestors.")
    for protected in (gallery / "photos", gallery / "originals"):
        if resolved_output.is_relative_to(protected):
            raise BuildError("The output directory cannot replace source photos or originals.")
    if output.is_symlink() or (output.exists() and not output.is_dir()):
        raise BuildError("The output must be a directory, not a file or symbolic link.")
    automatic_originals = originals is None
    sources = [Path(source).resolve() for source in (originals or [])]
    if originals is None and (gallery / "originals").exists():
        sources = [(gallery / "originals").resolve()]
    for source in sources:
        if source.is_relative_to(resolved_output) or resolved_output.is_relative_to(source):
            raise BuildError("The output directory and original-photo sources cannot overlap.")

    # Validate the source before touching any existing deployment artifact.
    manifest = photo_manifest(gallery)
    for name in SITE_FILES:
        regular_file(gallery, name)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".photography-build-", dir=output.parent) as temporary:
        temporary = Path(temporary)
        site = temporary / "site"
        site.mkdir()
        for name in SITE_FILES:
            checked_copy(gallery, name, site)
        for photo in manifest:
            checked_copy(gallery, photo["src"], site)

        if sources:
            checked_copy(gallery, "import_photos.py", temporary)
            importer_path = temporary / "import_photos.py"
            spec = importlib.util.spec_from_file_location("photography_import", importer_path)
            importer = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(importer)
            try:
                if automatic_originals:
                    with ExitStack() as stack:
                        found, unsupported = importer.discover(sources[0], stack, site)
                    if not found and not unsupported:
                        print("No photographs found in photography/originals; using the existing gallery manifest.")
                        sources = []
                if sources:
                    importer.import_photos(sources, site)
            except (importer.ImportErrorMessage, zipfile.BadZipFile, KeyError, TypeError) as error:
                raise BuildError(str(error)) from error
            # This local import metadata is not part of the public website.
            (site / ".photo-import.json").unlink(missing_ok=True)

        manifest = photo_manifest(site)
        byte_count = sum((site / name).stat().st_size for name in SITE_FILES)
        for photo in manifest:
            path = regular_file(site, photo["src"])
            byte_count += path.stat().st_size
            # Imported filenames contain their original SHA-256 checksum.
            if sources:
                checksum = path.stem.rsplit("-", 1)[-1]
                if len(checksum) == 64 and all(c in "0123456789abcdef" for c in checksum):
                    if digest(path).hex() != checksum:
                        raise BuildError(f"Original-photo checksum mismatch: {photo['src']}")

        backup = temporary / "previous-output"
        had_output = output.exists()
        if had_output:
            os.replace(output, backup)
        try:
            os.replace(site, output)
        except BaseException:
            if had_output:
                os.replace(backup, output)
            raise

    if not manifest:
        print("WARNING: No photos are available; this build shows only the opening quote.", file=sys.stderr)
    print(f"Built {output}: {len(manifest)} original photo(s), {byte_count:,} bytes. Photo bytes verified unchanged.")
    return len(manifest)


def main():
    gallery = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=gallery / "dist", help="deployment directory; replaced after validation (default: photography/dist)")
    parser.add_argument("--originals", type=Path, nargs="+", help="ZIP archives or photo directories to import into staging (default: photography/originals if present)")
    args = parser.parse_args()
    try:
        build(gallery, args.output, args.originals)
    except (BuildError, OSError, ValueError, RuntimeError) as error:
        print(f"Build failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
