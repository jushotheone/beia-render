#!/usr/bin/env python3
"""Trim the letterbox off a HeyGen presenter clip.

HeyGen renders whatever aspect the avatar look happens to be into the frame
size we ask for.  A full-body vertical avatar fills a 1080x1920 render; a
photo-avatar look is 16:9 and comes back as a band with black above and below.

ffmpeg's own cropdetect does not find that band.  The studio backdrop we use
(#12100F) is darker than its lowest usable threshold, so it reads the whole
frame as content and returns the full frame at every limit that was tried.  The
bars are therefore measured directly: downscale to a small greyscale image and
walk in from the top and bottom edges for as long as the rows stay flat.

Prints the ffmpeg crop expression on stdout, or nothing if the clip already
fills its frame.
"""

import subprocess
import sys

# How far above the letterbox level a row has to sit before it counts as
# content.  There is no usable absolute floor: these clips are limited-range, so
# their black is luma 16 rather than 0, and the studio backdrop only reaches the
# mid 20s.  The reference is taken from the frame's own outermost rows instead.
LUMA_MARGIN = 6.0
# A letterbox bar is always near-black. Limited-range black lands on 16, so the
# ceiling sits just above it; anything lighter is the avatar's own backdrop and
# must be left alone (an early white-background clip measured 246 at the edge).
BAR_MAX_LUMA = 24.0
# Ignore a band thinner than this -- a stray light row is not a crop.
MIN_BAND_FRACTION = 0.02
GRID_W, GRID_H = 32, 192


def probe_size(path: str) -> tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True,
    ).stdout.strip().split("\n")[0]
    w, h = out.split(",")[:2]
    return int(w), int(h)


def luma_grid(path: str, at_seconds: float) -> list[int]:
    """A GRID_W x GRID_H greyscale sample of one frame, as a flat byte list."""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(at_seconds), "-i", path,
         "-frames:v", "1",
         # area scaling, so a bright band cannot bleed into the bars beside it
         "-vf", f"scale={GRID_W}:{GRID_H}:flags=area,format=gray",
         "-f", "rawvideo", "-"],
        capture_output=True, check=True,
    ).stdout
    return list(raw[: GRID_W * GRID_H])


def content_box(path: str) -> tuple[int, int, int, int] | None:
    width, height = probe_size(path)

    # Sample a few points so a dark opening frame cannot decide the whole clip.
    rows = [0.0] * GRID_H
    cols = [0.0] * GRID_W
    samples = 0
    for at in (1.0, 2.0, 3.0):
        try:
            grid = luma_grid(path, at)
        except subprocess.CalledProcessError:
            continue
        if len(grid) < GRID_W * GRID_H:
            continue
        samples += 1
        for y in range(GRID_H):
            row = grid[y * GRID_W:(y + 1) * GRID_W]
            rows[y] = max(rows[y], sum(row) / GRID_W)
            for x in range(GRID_W):
                cols[x] = max(cols[x], row[x])
    if not samples:
        return None

    # Only the top and bottom bars are trimmed.  HeyGen letterboxes a wide
    # avatar; it has no reason to pillarbox one, and hunting for side bars as
    # well would let a presenter who happens to have a dark left or right edge
    # get shaved into.
    #
    # A bar has to be genuinely flat, not merely dark, or a dim scene would
    # register as one.  Rows are walked in from each edge only while they stay
    # level with the edge itself.
    def bar_depth(seq: list[float]) -> int:
        edge = seq[0]
        if edge > BAR_MAX_LUMA:
            return 0  # a light edge is the avatar's own backdrop, not a bar
        depth = 0
        for value in seq:
            if abs(value - edge) > LUMA_MARGIN:
                break
            depth += 1
        return depth

    top_rows = bar_depth(rows)
    bottom_rows = bar_depth(rows[::-1])
    if top_rows >= GRID_H or bottom_rows >= GRID_H:
        return None  # uniform all the way down: nothing to find

    top = int(top_rows / GRID_H * height)
    bottom = int((GRID_H - bottom_rows) / GRID_H * height)
    left, right = 0, width

    # Snap to even numbers -- yuv420 cannot encode an odd crop.
    top = top - (top % 2)
    bottom = min(height, bottom + (bottom % 2))

    trimmed_v = (top + (height - bottom)) / height
    trimmed_h = 0.0
    if trimmed_v < MIN_BAND_FRACTION and trimmed_h < MIN_BAND_FRACTION:
        return None  # already fills the frame

    return left, top, right - left, bottom - top


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: crop-presenter.py <clip.mp4>", file=sys.stderr)
        return 2
    box = content_box(sys.argv[1])
    if box:
        x, y, w, h = box
        print(f"crop={w}:{h}:{x}:{y}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
