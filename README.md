# beia-render

Shared BEIA OS video render service (Remotion). **Generic across all brands.**

- One composition (`QuoteReel`) renders a vertical 1080×1920 reel from a list of
  card image URLs. Brand look (`brandName`, `accentColor`) comes in as props from
  `beia_core` at render time — nothing here is brand-specific.
- Rendering runs on **GitHub Actions** (free CI compute), triggered by
  `beia_core`'s `remotion_video_tool` via `workflow_dispatch`.
- The workflow is **storage-blind**: it renders the mp4 and uploads it as a
  GitHub artifact. `beia_core` downloads the artifact and stores it in the
  correct brand's own R2 bucket (per-brand isolation).

## Local dev

```
npm install
npm run dev        # Remotion studio
npx remotion render QuoteReel out/reel.mp4 --props='{"images":["https://.../card1.png"]}'
```

## How it's driven in production

`beia_core` → GitHub API `workflow_dispatch` (`render-video.yml`) with inputs
`images`, `task_id`, `brand_name`, `accent_color` → render → artifact
`reel-<task_id>` → `beia_core` downloads it → uploads to the brand's R2.

## Tower clips (Blender, not Remotion)

`render-tower-clip.yml` renders a cinematic clip of the live BEIA Tower — the
console's public 3D office — in Blender Cycles:

1. **export**: headless Chrome opens `<console>/broadcast/office?export=1`,
   rides to the roof stop and exports the scene as a GLB (`tower/export-scene.mjs`,
   repaired by `tower/fix-glb.cjs`).
2. **render**: 20 runners each draw every 20th frame on the CPU (`tower/render.py`).
3. **assemble**: ffmpeg stitches `clip.mp4` plus three QA stills into the artifact
   `towerclip-<task_id>`.

Camera moves live in `tower/shots.json`. Locally, with a GPU:
`node tower/make-clip.mjs --shot establishing-orbit --url http://localhost:3000`.
