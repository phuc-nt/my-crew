// Report-only scan for i18n keys the UI no longer asks for.
//
// Dev tool, never imported by the app. It prints candidates; it does NOT delete.
// A key is a candidate only when its exact quoted literal appears nowhere in src/.
// That is deliberately conservative and still not proof: several call sites build the
// key at runtime (`t(\`taskStatus.${status}\`)`), so those families are whitelisted by
// prefix below. Always eyeball a candidate before removing it — a wrongly deleted key
// does not fail the build, it renders the raw key string to the user.
//
//   node scripts/find-dead-dictionary-keys.mjs
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'

const SRC = new URL('../src/', import.meta.url).pathname
const DICT_FILE = join(SRC, 'i18n/dictionary.ts')

// Key families assembled at runtime. Everything under these prefixes is kept.
const DYNAMIC_PREFIXES = [
  'taskStatus.',
  'stepStatus.',
  'verdict.',
  'officeState.',
  'eventKind.',
  'trustMode.',
  'lane.',
  'workroomList.filter.',
]

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p, out)
    else if (/\.tsx?$/.test(name)) out.push(p)
  }
  return out
}

const files = walk(SRC).filter((f) => f !== DICT_FILE)
const haystack = files.map((f) => readFileSync(f, 'utf8')).join('\n')

// Keys live in the `vi` block as `'some.key': '...'`. One block is enough: the
// `satisfies` clause in dictionary.ts already forces en to carry the same set.
const dict = readFileSync(DICT_FILE, 'utf8')
const viStart = dict.indexOf('const vi = {')
const enStart = dict.indexOf('const en = {', viStart)
const viBlock = dict.slice(viStart, enStart > 0 ? enStart : undefined)
const keys = [...viBlock.matchAll(/^\s*'([\w.-]+)':/gm)].map((m) => m[1])

const dead = keys.filter((k) => {
  if (DYNAMIC_PREFIXES.some((p) => k.startsWith(p))) return false
  return !haystack.includes(`'${k}'`) && !haystack.includes(`"${k}"`) && !haystack.includes(`\`${k}\``)
})

console.log(`${keys.length} keys scanned, ${dead.length} with no literal use in src/`)
for (const k of dead) console.log(`  ${k}`)
if (dead.length) console.log('\nReview each one by hand before deleting.')
