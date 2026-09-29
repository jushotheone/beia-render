// tower/export-scene.mjs — export the live BEIA Tower scene as a GLB.
//
// Opens the console's public office page (/broadcast/office?export=1), rides
// to a storey stop, and asks the page's export hook (scene3d/ExportHook.tsx in
// beia-console) for the scene. The clip therefore shows whatever the live
// tower shows at that moment — the data is beia_core's, not this repo's.
//
//   node tower/export-scene.mjs --url https://beia.lawrenceomolo.com --out <dir>
//        [--stop "R Roof garden"] [--headed]
//
// Writes <dir>/tower.glb and <dir>/camera.json.
//
// Headless by default so it runs on a CI runner with no GPU (SwiftShader).
// That is slow — about 8 minutes on 2026-09-29 — because the page draws its
// frames in software. Every wait below therefore polls on a timer: the default
// waitForFunction polls per animation frame, and a software renderer starves
// those, which is how the first attempts timed out on a page that was fine.

import { chromium } from 'playwright'
import fs from 'node:fs'
import path from 'node:path'

const arg = (k, d) => { const i = process.argv.indexOf(`--${k}`); return i > 0 ? process.argv[i + 1] : d }
const url = (arg('url', 'https://beia.lawrenceomolo.com') || '').replace(/\/$/, '')
const out = path.resolve(arg('out', 'tower-export'))
const stop = arg('stop', 'R Roof garden')
const headed = process.argv.includes('--headed')

const t0 = Date.now()
const log = (m) => console.log(`${((Date.now() - t0) / 1000).toFixed(1)}s ${m}`)
const POLL = { timeout: 300_000, polling: 1000 }

const browser = await chromium.launch({
  headless: !headed,
  args: headed ? [] : ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'],
})
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 720 } })
  page.on('pageerror', (e) => log(`page error: ${e.message.slice(0, 160)}`))
  await page.goto(`${url}/broadcast/office?export=1`, { waitUntil: 'domcontentloaded', timeout: 120_000 })
  await page.waitForSelector('[data-testid=tower-scene]', { timeout: 300_000 })
  log('scene mounted')
  await page.waitForFunction(() => typeof window.__towerExport === 'function', null, POLL)
  log('export hook present')

  // The storey list only appears once beia_core's data has arrived, and the
  // button is not "visible" to Playwright under software rendering, so it is
  // found and clicked through the DOM.
  await page.waitForFunction(
    (label) => [...document.querySelectorAll('button')].some((b) => b.textContent.trim() === label),
    stop, POLL,
  )
  await page.waitForTimeout(10_000)
  await page.evaluate(
    (label) => [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === label).click(),
    stop,
  )
  log(`riding to ${stop}`)
  // The ride is timed in wall-clock seconds, but a starved renderer steps it
  // in coarse frames; wait until the camera has stopped moving.
  let last = null
  for (let i = 0; i < 60; i++) {
    await page.waitForTimeout(5000)
    const p = (await page.evaluate(() => window.__towerCamera?.()))?.position
    if (p && last && p.every((v, k) => Math.abs(v - last[k]) < 0.01)) break
    last = p
  }
  const cam = await page.evaluate(() => window.__towerCamera())
  log(`camera settled at ${cam.position.map((v) => v.toFixed(1)).join(', ')}`)

  const b64 = await page.evaluate(() => window.__towerExport())
  if (!b64) throw new Error('export hook returned nothing')
  fs.mkdirSync(out, { recursive: true })
  fs.writeFileSync(path.join(out, 'tower.glb'), Buffer.from(b64, 'base64'))
  fs.writeFileSync(path.join(out, 'camera.json'), JSON.stringify({ ...cam, width: 1280, height: 720 }))
  log(`exported ${(b64.length * 0.75 / 1e6).toFixed(1)} MB to ${out}`)
} finally {
  await browser.close()
}
