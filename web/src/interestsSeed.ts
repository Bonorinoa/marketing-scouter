// Closed Fit list for the x-brief handoff panel — parsed ONLY from data/xbrief-interests-seed.md.
// There is no free-form interest field anywhere in the shell.
import seedMd from "../../data/xbrief-interests-seed.md?raw";

export interface SeedInterest { slug: string; door: string }
export function parseSeed(md: string): SeedInterest[] {
  const active = md.split("## Active")[1]?.split("## Paused")[0] ?? "";
  const out: SeedInterest[] = [];
  for (const m of active.matchAll(/^- `([a-z0-9-]+)` \[([^\]]+)\]/gm)) out.push({ slug: m[1], door: m[2] });
  return out;
}
export const CLOSED_INTERESTS: SeedInterest[] = parseSeed(seedMd);
export const CLOSED_SLUGS = new Set(CLOSED_INTERESTS.map((i) => i.slug));
