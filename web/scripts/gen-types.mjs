// Generate TypeScript read-model types from ../schemas/*.json (Pydantic model_json_schema exports).
// The UI is a read-only consumer: no business logic is duplicated, only types.
import { compile } from 'json-schema-to-typescript'
import { mkdirSync, readdirSync, readFileSync, writeFileSync, unlinkSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const schemas = resolve(here, '..', '..', 'schemas')
const out = resolve(here, '..', 'src', 'types')
const check = process.argv.includes('--check')
if (!check) mkdirSync(out, { recursive: true })

const files = readdirSync(schemas).filter((f) => f.endsWith('.json')).sort((a,b)=>a.localeCompare(b,undefined,{numeric:true}))
const families = files.map(f => f.replace(/\.v\d+\.json$/, ''))
if (new Set(families).size !== families.length) throw new Error('Duplicate schema family: retain exactly one version per contract')
for (const existing of readdirSync(out)) {
  if (existing.endsWith('.ts') && !families.includes(existing.slice(0, -3))) {
    if (check) throw new Error('Obsolete generated type: ' + existing)
    unlinkSync(join(out, existing))
  }
}
for (const f of files) {
  const base = f.replace(/\.v\d+\.json$/, '')
  const schema = JSON.parse(readFileSync(join(schemas, f), 'utf8'))
  const ts = await compile(schema, base, {
    bannerComment: `/* generated from schemas/${f} — do not edit */`,
    additionalProperties: false,
    style: { semi: false, singleQuote: true },
  })
  const target = join(out, `${base}.ts`)
  if (check) {
    if (readFileSync(target, 'utf8') !== ts) throw new Error('Generated type differs: ' + base)
  } else writeFileSync(target, ts)
}
console.log(`${check ? 'verified' : 'generated'} ${files.length} type modules into src/types/`)
