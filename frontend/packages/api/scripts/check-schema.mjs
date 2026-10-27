// Fails if src/schema.ts is stale: regenerates it from openapi.json in
// memory and compares. Run `make web-types` to refresh both files from the
// API (docs/components/frontend.md, API types).
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';

const fresh = execFileSync('pnpm', ['exec', 'openapi-typescript', 'openapi.json'], { encoding: 'utf8' });
const committed = readFileSync('src/schema.ts', 'utf8');
if (fresh.trim() !== committed.trim()) {
  console.error('src/schema.ts is out of date with openapi.json. Run `make web-types`.');
  process.exit(1);
}
console.log('schema.ts matches openapi.json');
