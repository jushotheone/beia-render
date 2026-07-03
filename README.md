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
