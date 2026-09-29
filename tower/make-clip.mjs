// tower/make-clip.mjs — the tower clip, locally, in one command:
//   export (tower/export-scene.mjs) → repair (tower/fix-glb.cjs) →
//   Blender (tower/render.py, GPU when there is one) → <out>/<shot>.mp4
//
//   node tower/make-clip.mjs --shot establishing-orbit [--samples 24]
//        [--url http://localhost:3000] [--out /tmp/tower-clip] [--headed]
//
// Needs Blender and ffmpeg on PATH, and Playwright resolvable from here
// (`npm i --no-save playwright` in this repo). The same steps run on GitHub
// Actions in .github/workflows/render-tower-clip.yml, split across 20 runners.

import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'

const arg = (k, d) => { const i = process.argv.indexOf(`--${k}`); return i > 0 ? process.argv[i + 1] : d }
const here = path.dirname(new URL(import.meta.url).pathname)
const shot = arg('shot', 'establishing-orbit')
const samples = arg('samples', '24')
const url = arg('url', 'http://localhost:3000')
const out = path.resolve(arg('out', `/tmp/tower-clip-${Date.now()}`))
fs.mkdirSync(out, { recursive: true })

const run = (cmd, args) => execFileSync(cmd, args, { stdio: 'inherit' })
run('node', [path.join(here, 'export-scene.mjs'), '--url', url, '--out', out, ...(process.argv.includes('--headed') ? ['--headed'] : [])])
run('node', [path.join(here, 'fix-glb.cjs'), path.join(out, 'tower.glb')])
const hdri = path.join(out, 'canary_wharf.hdr')
if (!fs.existsSync(hdri)) {
  const res = await fetch(`${url.replace(/\/$/, '')}/tower/hdri/canary_wharf.hdr`)
  if (!res.ok) throw new Error(`could not fetch the sky from the console: ${res.status}`)
  fs.writeFileSync(hdri, Buffer.from(await res.arrayBuffer()))
}
run('blender', ['-b', '-P', path.join(here, 'render.py'), '--', out, '--clip', shot, '--samples', samples, '--hdri', hdri, '--mp4'])
const mp4 = path.join(out, `${shot}.mp4`)
if (!fs.existsSync(mp4)) throw new Error('render finished without an mp4')
console.log(`clip: ${mp4}`)
