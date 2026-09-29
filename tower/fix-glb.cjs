// tower/fix-glb.cjs — make a GLTFExporter export of the tower loadable
// in Blender. Two things the browser tolerates and Blender's importer does not:
//   1. accessor min/max holding null / non-finite values (empty geometry)
//   2. a primitive whose indices point past the end of one of its attributes
//      (seen in headless SwiftShader exports; one bad primitive aborts the
//      whole import). Those primitives are dropped — they draw nothing valid.
//   node tower/fix-glb.cjs <file.glb>
const fs = require('fs')
const f = process.argv[2]
const b = fs.readFileSync(f)
const jl = b.readUInt32LE(12)
const json = JSON.parse(b.slice(20, 20 + jl).toString())
const rest = b.slice(20 + jl)
// BIN chunk: [len u32][type u32][data]
const bin = rest.length >= 8 ? rest.slice(8, 8 + rest.readUInt32LE(0)) : Buffer.alloc(0)

let fixed = 0
for (const a of json.accessors || []) {
  for (const k of ['min', 'max']) {
    if (a[k] && a[k].some((v) => v === null || !Number.isFinite(v))) {
      a[k] = a[k].map((v) => (Number.isFinite(v) ? v : 0)); fixed++
    }
  }
}

const READ = { 5121: ['readUInt8', 1], 5123: ['readUInt16LE', 2], 5125: ['readUInt32LE', 4] }
function maxIndex(ai) {
  const a = json.accessors[ai]
  if (a.bufferView === undefined) return -1
  const bv = json.bufferViews[a.bufferView]
  const [fn, size] = READ[a.componentType]
  const start = (bv.byteOffset || 0) + (a.byteOffset || 0)
  let m = -1
  for (let i = 0; i < a.count; i++) m = Math.max(m, bin[fn](start + i * size))
  return m
}

let dropped = 0
for (const mesh of json.meshes || []) {
  mesh.primitives = mesh.primitives.filter((p) => {
    const counts = Object.values(p.attributes || {}).map((ai) => json.accessors[ai].count)
    const shortest = counts.length ? Math.min(...counts) : 0
    const top = p.indices !== undefined ? maxIndex(p.indices) : shortest - 1
    const ok = shortest > 0 && top < shortest
    if (!ok) dropped++
    return ok
  })
}
// A mesh left with no primitives is invalid glTF; detach it from its nodes.
const empty = new Set((json.meshes || []).map((m, i) => (m.primitives.length ? -1 : i)).filter((i) => i >= 0))
for (const n of json.nodes || []) if (empty.has(n.mesh)) delete n.mesh
for (const m of json.meshes || []) if (!m.primitives.length) m.primitives = [{ attributes: {} }]
// Keep the (now unreferenced) placeholder meshes rather than renumber every index.

let s = Buffer.from(JSON.stringify(json))
const pad = (4 - (s.length % 4)) % 4
s = Buffer.concat([s, Buffer.alloc(pad, 0x20)])
const head = Buffer.alloc(20)
head.writeUInt32LE(0x46546c67, 0); head.writeUInt32LE(2, 4)
head.writeUInt32LE(20 + s.length + rest.length, 8)
head.writeUInt32LE(s.length, 12); head.writeUInt32LE(0x4e4f534a, 16)
fs.writeFileSync(f, Buffer.concat([head, s, rest]))
console.log('fixed', fixed, 'dropped', dropped)
