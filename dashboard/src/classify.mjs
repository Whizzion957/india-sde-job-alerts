import { createInterface } from "node:readline";
import { classifyJob } from "../dist/match.js";

for await (const line of createInterface({
  input: process.stdin,
  crlfDelay: Infinity,
})) {
  const jobs = JSON.parse(line);
  for (const job of jobs) {
    Object.assign(job, classifyJob(job.title, job.description));
    delete job.description;
  }
  console.log(JSON.stringify(jobs.filter((job) => job.families.length)));
}
