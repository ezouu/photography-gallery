# Photography gallery

[Open the live gallery](https://ezouu.github.io/photography-gallery/).

A white page with one centered photograph, or the opening quote:

> the only advice that is objectively true is “take more pictures”

Left and right arrow keys move backward and forward. Navigation wraps through
the quote and all photographs. On touch screens, swipe horizontally. There are
no visible buttons, captions, counters, headers, or footers.

## Free cloud hosting with GitHub Pages

GitHub Pages is free for public repositories. The
[`Publish photography gallery` workflow](../.github/workflows/photography-pages.yml)
builds the gallery from the `photography` branch and publishes only the clean
website output, preserving the original image bytes. Other repository files
are excluded from the website.

Builds work while the repository is private: they save a downloadable
**photography-gallery** ZIP artifact and skip public deployment. When the
repository is public, the workflow also deploys to Pages. The public address
comes from the successful deployment output; a build alone does not mean
hosting is live.

One-time setup in the public repository's **Settings → Pages**: set the build
source to **GitHub Actions**. The connected cloud token can push code but cannot
perform this initial enablement. Then run **Publish photography gallery** from
**Actions → Run workflow**. Later pushes to the `photography` branch deploy
automatically. A visibility change to public also starts the workflow when its
definition is on the repository's default branch.

Download the **photography-gallery** ZIP from a successful run's **Artifacts**
section within seven days. It contains just the finished website and original
photographs, and can also be uploaded to another static host.

To add photographs, use GitHub's **Upload files** in
[`photography/originals/`](originals/) on the `photography` branch. Upload the
original JPEG, PNG, WebP, AVIF, GIF, or BMP files. The build imports them in
natural filename order. GitHub's browser upload limit is 25 MiB per file;
larger individual files require a Git upload.

The Pages published-site limit is 1 GB, with a soft bandwidth limit of 100 GB
per month. There is no resizing to fit these limits: originals are retained,
so a larger collection requires a different hosting arrangement.

Cloudflare Pages is an alternative that supports private GitHub repositories
on its free plan. Use production branch `photography`, framework **None**, a
blank root directory, build command `python3 photography/build.py`, and output
`photography/dist`. Disable preview deployments for other branches.

## Build and run in the cloud environment

From the repository root:

```sh
python3 photography/build.py
python3 -m http.server 8000 --bind 127.0.0.1 --directory photography/dist
```

This validates and stages a clean static website in `photography/dist/`.
No compilation toolchain or third-party dependencies are needed. Original
photographs are checksum-verified and copied unchanged. When `originals/` is
empty, the build uses the existing `photos.json` manifest; with no photographs,
it reports that the resulting site contains only the opening quote.

To build directly from ZIPs or photo folders without changing the source
gallery:

```sh
python3 photography/build.py --originals /path/to/candidates.zip
python3 photography/build.py --originals /path/to/part1.zip /path/to/part2.zip
```

The cloud environment's local server is for internal development checks.
GitHub Pages provides the publicly accessible hosted website.

## Add the photographs and run locally

From the repository root:

```sh
python3 photography/import_photos.py /path/to/candidates.zip
python3 -m http.server 8000 --bind 127.0.0.1 --directory photography
```

Open `http://localhost:8000` in your browser. No Node.js dependencies, build
step, or Python packages are required. The importer requires Python 3.9+.
The website is a plain static directory and can also be served by a static
hosting service.

Five original JPEGs are included in `originals/`. The cloud build imports them
automatically; use the build-and-run commands above to view that collection.
The initial ZIP exceeded the cloud transfer limit, so the photographs were
uploaded directly to the repository instead.

The importer accepts multiple ZIPs or directories, either together or on
successive runs:

```sh
python3 photography/import_photos.py /path/to/part1.zip /path/to/part2.zip
python3 photography/import_photos.py /path/to/a/photo/folder
```

Photographs appear in natural filename order. Repeated imports reuse identical
files instead of duplicating them. Generated `photos.json` lists the images,
and `.photo-import.json` retains their original filenames and import metadata.

## Photo quality

- Original photo bytes are copied unchanged, preserving resolution, EXIF
  orientation, and embedded color profiles.
- The browser loads each original directly. There are no thumbnails, resized
  variants, canvas conversions, quality settings, or image filters.
- Images fit within the viewport with a small white margin, keep their aspect
  ratio, and are never cropped. Browser scaling and color management depend
  on the device and browser.
- The next original is prefetched. The previous slide stays visible until the
  requested image is decoded, and rapid navigation cancels outdated loads.
- Pinch zoom is allowed; swiping is disabled while zoomed so images can be panned.

JPEG, PNG, WebP, AVIF, GIF, and BMP are supported. HEIC, TIFF, RAW, and other
formats that browsers cannot reliably display need conversion before import;
the importer reports these instead of silently dropping photographs. It does
not modify the source archive or photos.

To publish a gallery with photos, include `photos/`, `photos.json`, and the
site's HTML, CSS, and JavaScript in the static host's deployment.
