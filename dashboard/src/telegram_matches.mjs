import { readFileSync } from "node:fs";
import { defaults, matchCatalog } from "../dist/match.js";

const {jobs, preferences, archived, applied, zeroExperienceOnly} = JSON.parse(readFileSync(0, "utf8"));
const candidates = zeroExperienceOnly ? jobs.filter(job => job.minYears === 0) : jobs;
const matches = matchCatalog(candidates, {...defaults, ...preferences}, {archived, applied})
  .filter(({match}) => !match.uncertain)
  .sort((a, b) => b.match.score - a.match.score ||
    (b.job.posted || "").localeCompare(a.job.posted || ""));
process.stdout.write(JSON.stringify(matches));
