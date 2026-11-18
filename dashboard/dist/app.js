import { defaults, families, matchCatalog } from "./match.js";

const $ = (id) => document.getElementById(id);
const pageSize = 15;
const stages = {
  applied: "Applied", screening: "Screening", interview: "Interview",
  offer: "Offer", accepted: "Accepted", rejected: "Rejected", withdrawn: "Withdrawn",
};
const terminalStages = new Set(["accepted", "rejected", "withdrawn"]);
const levelLabels = {
  intern: "Intern",
  entry: "Entry-level",
  mid: "Mid-level",
  senior: "Senior",
  lead: "Lead",
};
const sourceLabels = {
  ok: "Checked",
  stale: "Earlier results",
  partial: "Partial results",
  error: "Unavailable",
  pending: "Awaiting scan",
};
const state = {
  jobs: [],
  sources: [],
  updatedAt: null,
  user: null,
  preferences: { ...defaults },
  applied: new Map(),
  archived: new Map(),
  saved: new Map(),
  jobIds: new Set(),
  matches: [],
  busy: new Set(),
  ready: false,
  jobsError: false,
  sessionError: false,
  page: 1,
  query: "",
  sort: "match",
  tracker: false,
  archive: false,
  shortlist: false,
  sourceByKey: new Map(),
};
const number = new Intl.NumberFormat();
const dateFormat = new Intl.DateTimeFormat(undefined, {
  day: "numeric",
  month: "short",
  year: "numeric",
});
const timeFormat = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
});
const collate = new Intl.Collator(undefined, {
  sensitivity: "base",
  numeric: true,
});
const missing = (text) => String(text || "").trim();
const lower = (text) => missing(text).toLowerCase();
let toastTimer;
let queryTimer;
let catalogTag = "";
let refreshing = false;
let editingApplication;

function followUpState(record) {
  if (!record.followUp || terminalStages.has(record.stage)) return "";
  const today = new Date();
  const localDate = new Date(today.getTime() - today.getTimezoneOffset() * 60000)
    .toISOString().slice(0, 10);
  return record.followUp <= localDate ? "due" : "planned";
}

function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}
function button(text, cls, action) {
  const node = el("button", text, cls);
  node.type = "button";
  node.addEventListener("click", action);
  return node;
}
function signInLink() {
  const link = el("a", "Sign in");
  link.href = "/account";
  link.target = "_top";
  return link;
}
function dateText(value, withTime = false) {
  if (!value) return "";
  // A board's date-only field is a calendar date, independent of the browser time zone.
  const date = /^\d{4}-\d{2}-\d{2}$/.test(value)
    ? new Date(value + "T12:00:00")
    : new Date(value);
  return Number.isNaN(date.getTime())
    ? ""
    : (withTime ? timeFormat : dateFormat).format(date);
}
function toast(message, undo) {
  clearTimeout(toastTimer);
  $("toast").textContent = message;
  if (undo) $("toast").append(button("Undo", "toast-action", undo));
  toastTimer = setTimeout(() => {
    $("toast").textContent = "";
  }, undo ? 12000 : 4200);
}

async function api(path, method = "GET", data) {
  const response = await fetch("/api/" + path, {
    method,
    credentials: "same-origin",
    cache: "no-store",
    ...(data
      ? {
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data),
        }
      : {}),
  });
  if (!response.ok) {
    const error = new Error("Request failed");
    error.status = response.status;
    throw error;
  }
  if (response.status === 204) return {};
  const body = await response.text();
  return body ? JSON.parse(body) : {};
}

async function readCatalog() {
  const response = await fetch("/api/jobs", {
    cache: "no-cache",
    headers: catalogTag ? { "If-None-Match": catalogTag } : {},
  });
  if (response.status === 304) return false;
  if (!response.ok) throw new Error("Feed unavailable");
  const tag = response.headers.get("ETag");
  if (tag && tag === catalogTag) return false;
  const catalog = await response.json();
  if (!Array.isArray(catalog.jobs)) throw new Error("Invalid catalog");
  state.jobs = catalog.jobs;
  state.jobIds = new Set(state.jobs.map((job) => String(job.id)));
  state.sources = catalog.sources || [];
  state.sourceByKey = new Map(
    state.sources.map((source) => [source.key, source]),
  );
  state.updatedAt = catalog.updatedAt;
  catalogTag = tag || "";
  return true;
}

async function refreshCatalog(manual = false) {
  if (!state.ready || refreshing) return;
  refreshing = true;
  $("refresh").disabled = true;
  try {
    const changed = await readCatalog();
    const recovered = state.jobsError;
    state.jobsError = false;
    if (changed || recovered) {
      rebuildMatches();
      renderPage();
    }
    if (manual)
      toast(changed ? "Feed refreshed." : "You have the latest feed.");
  } catch {
    state.jobsError = true;
    renderNotices();
  } finally {
    refreshing = false;
    $("refresh").disabled = false;
  }
}

async function readScanStatus() {
  try {
    const { active, last, nextCheckAt } = await api("scan");
    const next = dateText(nextCheckAt, true);
    const started = dateText(active?.startedAt, true);
    const due = nextCheckAt && Date.parse(nextCheckAt) <= Date.now();
    const progress = active
      ? "Scanning · " + number.format(active.checked) + " of " + number.format(active.total) +
        " boards checked (started " + started + ")"
      : due ? "Boards are due for a check." : next ? "Next board check around " + next : "";
    if ($("scan-progress").textContent !== progress) $("scan-progress").textContent = progress;
    if (last) {
      const seconds = Math.max(0, last.seconds);
      const duration = seconds < 60 ? seconds + "s" :
        Math.floor(seconds / 60) + "m " + (seconds % 60) + "s";
      $("scan-timing").textContent = "Last run took " + duration + " for " +
        number.format(last.checked) + " boards.";
    }
  } catch {
    $("scan-progress").textContent = "Scan status unavailable.";
  }
}

function mergePreferences(prefs) {
  return {
    maxAgeDays: null,
    includeUndated: true,
    ...defaults,
    ...prefs,
    families: Array.isArray(prefs?.families)
      ? prefs.families
      : defaults.families,
    skills: Array.isArray(prefs?.skills) ? prefs.skills : defaults.skills,
    levels: Array.isArray(prefs?.levels) ? prefs.levels : [],
  };
}

async function load() {
  $("cards").setAttribute("aria-busy", "true");
  const [catalog, session] = await Promise.allSettled([
    readCatalog(),
    api("session"),
  ]);
  state.jobsError = catalog.status === "rejected";
  state.sessionError =
    session.status === "rejected" && session.reason.status !== 401;
  if (session.status === "fulfilled") {
    state.user = session.value.user;
    state.preferences = mergePreferences(session.value.preferences);
    state.applied = new Map(
      (session.value.applications || [])
        .filter((record) => record.job)
        .map((record) => [String(record.job.id), record]),
    );
    state.archived = new Map(
      (session.value.archives || [])
        .filter((record) => record.job)
        .map((record) => [String(record.job.id), record]),
    );
    state.saved = new Map(
      (session.value.shortlist || []).map((record) => [String(record.job.id), record]),
    );
  } else if (session.reason.status === 401) {
    state.user = null;
    state.applied.clear();
    state.archived.clear();
    state.saved.clear();
    state.preferences = mergePreferences(defaults);
  }
  state.ready = true;
  $("edit-top").disabled = $("edit-side").disabled = false;
  rebuildMatches();
  renderPage();
  readScanStatus();
}

function rebuildMatches() {
  state.matches = matchCatalog(state.jobs, state.preferences, {
    archived: [...state.archived.keys()],
    applied: [...state.applied.keys()],
  });
}
function renderNotices() {
  const area = $("notices");
  area.replaceChildren();
  function notice(message, action) {
    const row = el("p", message, "notice");
    if (action) row.append(action);
    area.append(row);
  }
  if (state.jobsError)
    notice(
      "The latest job feed could not be loaded.",
      button("Retry", "", () => refreshCatalog(true)),
    );
  if (state.sessionError)
    notice(
      "Your account information could not be loaded.",
      button("Retry", "", load),
    );
  else if (!state.user && (state.tracker || state.archive || state.shortlist))
    notice(state.archive ? "Sign in to open your archive." :
      state.shortlist ? "Sign in to open your shortlist." :
      "Sign in to open your personal application tracker.", signInLink());
  if (state.user && !state.tracker && !state.archive && !state.shortlist) {
    const due = [...state.applied.values()].filter((record) => followUpState(record) === "due").length;
    if (due) {
      notice(number.format(due) + (due === 1 ? " application follow-up is due." : " application follow-ups are due."),
        button("See follow-ups", "", () => {
          $("tracker-filter").value = "due";
          location.hash = "applications";
        }));
    }
  }
  const problems = state.sources.filter((s) =>
    ["stale", "error", "partial"].includes(s.status),
  ).length;
  if (problems)
    notice(
      number.format(problems) +
        " company board" +
        (problems === 1 ? " needs" : "s need") +
        " another check. Some listings may have changed.",
      button("View scan status", "", openSources),
    );
}
function renderAccount() {
  const account = $("account");
  $("identity").hidden = !state.user?.name;
  $("identity").textContent = state.user?.name || "";
  $("identity").title = state.user?.name || "";
  if (!state.user) {
    account.textContent = "Sign in";
    account.href = "/account";
    account.onclick = null;
    return;
  }
  account.textContent = "Sign out";
  account.href = "/account";
  account.onclick = async (event) => {
    event.preventDefault();
    try {
      const result = await api("logout", "POST", {});
      const dest = new URL(result.redirect || "/", location.origin);
      location.assign(dest.origin === location.origin ? dest.href : "/");
    } catch {
      toast("Could not sign out. Please try again.");
    }
  };
}
function workplaceLabel(value) {
  return (
    { remote: "Remote", onsite: "On-site", hybrid: "Hybrid" }[lower(value)] ||
    ""
  );
}
function preferenceSummary() {
  const p = state.preferences;
  const summary = $("pref-summary");
  summary.replaceChildren();
  const groups =
    p.families.length === families.length
      ? "All tech role families"
      : p.families.join(", ");
  if (!state.tracker && !state.archive && !state.shortlist) {
    const profile = [
      p.location || "Any location",
      p.years == null
        ? "any experience level"
        : "up to " +
          p.years +
          (p.years === 1 ? " year" : " years") +
          " of experience",
      workplaceLabel(p.workplace),
    ].filter(Boolean);
    $("subtitle").textContent = profile.join(" · ");
  }
  for (const [label, value] of [
    ["Role families", groups || "All tech role families"],
    ...(p.levels?.length
      ? [["Seniority", p.levels.map((level) => levelLabels[level] || level).join(", ")]]
      : []),
    ["Location", p.location || "Anywhere"],
    [
      "Experience",
      p.years == null
        ? "Any experience"
        : p.years + (p.years === 1 ? " year" : " years"),
    ],
    ["Work arrangement", workplaceLabel(p.workplace) || "Any arrangement"],
    [
      "Posting date",
      (p.maxAgeDays === 1
        ? "Today"
        : p.maxAgeDays
          ? "Past " + p.maxAgeDays + " days"
          : "Any date") +
        (p.includeUndated === false
          ? " · dated roles only"
          : " · includes undated roles"),
    ],
    ...(p.skills.length ? [["Preferred skills", p.skills.join(", ")]] : []),
  ]) {
    const group = el("div");
    group.append(el("dt", label), el("dd", value));
    summary.append(group);
  }
}
function renderCoverage() {
  const ok = state.sources.filter((s) => s.status === "ok").length;
  const integrated = state.sources.filter((s) => s.status !== "manual").length;
  $("coverage").textContent = state.sources.length
    ? number.format(ok) +
      " of " +
      number.format(integrated) +
      " boards checked successfully."
    : "Company board activity is unavailable.";
  const when = dateText(state.updatedAt, true);
  $("scan-kicker").hidden = !when;
  $("scan-kicker").textContent = when ? "Catalog updated · " + when : "";
  $("last-scan").textContent = when ? "Last catalog update · " + when : "";
  $("view-sources").disabled = !state.sources.length;
}
function openSources() {
  const list = $("source-list");
  list.replaceChildren();
  const sorted = [...state.sources].sort((a, b) => {
    const priority = { error: 0, stale: 1, partial: 2, pending: 3, ok: 4, manual: 5 };
    return (
      (priority[a.status] ?? 4) - (priority[b.status] ?? 4) ||
      collate.compare(a.company, b.company)
    );
  });
  $("source-overview").textContent =
    $("coverage").textContent + " " + $("last-scan").textContent;
  for (const s of sorted) {
    const row = el("li"),
      label = el("span", s.company || "Company board");
    if (s.careers?.startsWith("https://")) {
      const link = el("a", s.company);
      link.href = s.careers;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      label.replaceChildren(link);
    }
    const details = [
      s.scope,
      s.checkedAt && dateText(s.checkedAt, true),
      s.status !== "manual" && s.count != null && number.format(s.count) + " roles",
    ].filter(Boolean);
    if (details.length) label.append(el("small", details.join(" · ")));
    row.append(
      label,
      el(
        "span",
        s.status === "manual" ? "Open careers site" : sourceLabels[s.status] || "Awaiting scan",
        s.status === "ok" ? "source-status" : "source-status issue",
      ),
    );
    list.append(row);
  }
  $("source-dialog").showModal();
}
function renderMetrics() {
  $("matches-total").textContent =
    state.jobsError && !state.jobs.length
      ? "—"
      : number.format(state.matches.length);
  $("companies-total").textContent =
    state.jobsError && !state.jobs.length
      ? "—"
      : number.format(new Set(state.matches.map((r) => r.job.company)).size);
  $("applied-total").textContent = state.user
    ? number.format(state.applied.size)
    : "—";
  $("nav-count").hidden = !state.applied.size;
  $("nav-count").textContent = number.format(state.applied.size);
  const due = [...state.applied.values()].filter((record) => followUpState(record) === "due").length;
  $("due-shortcut").hidden = due === 0;
  $("due-shortcut").textContent = number.format(due) + (due === 1 ? " follow-up due" : " follow-ups due");
}
function postingLink(job) {
  try {
    const url = new URL(job.url);
    if (!["http:", "https:"].includes(url.protocol)) return null;
    const link = el("a", "View posting ↗", "job-link");
    link.href = url.href;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.setAttribute(
      "aria-label",
      "View " + job.title + " at " + job.company + " in a new tab",
    );
    return link;
  } catch {
    return null;
  }
}
function companyMark(name) {
  const words = (name || "?").trim().split(/\s+/);
  const initials =
    words.length > 1 ? words[0][0] + words[1][0] : words[0].slice(0, 2);
  const mark = el(
    "span",
    initials.toUpperCase(),
    "company-mark tone-" + ((initials.codePointAt(0) || 0) % 4),
  );
  mark.setAttribute("aria-hidden", "true");
  return mark;
}
function jobCard(record) {
  const {job, match, appliedAt, archivedAt, savedAt} = record;
  const card = el("article", undefined, "job");
  const top = el("div", undefined, "job-top");
  const company = el("div", undefined, "company");
  company.append(
    companyMark(job.company),
    document.createTextNode(job.company || "Company"),
  );
  const date = dateText(state.archive ? archivedAt : state.tracker ? appliedAt : state.shortlist ? savedAt : job.posted);
  const dateLabel = state.archive ? "Archived " : state.tracker ? "Applied " : state.shortlist ? "Saved " : "Posted ";
  top.append(
    company,
    el(
      "span",
      date ? dateLabel + date : "Date unlisted",
      "date",
    ),
  );
  card.append(top, el("h3", job.title || "Untitled role"));
  const locationText = job.location || "Location unlisted";
  const meta = [
    locationText,
    workplaceLabel(job.workplace),
    job.minYears === 0 ? "No experience minimum" : job.minYears != null ? job.minYears + "+ years" : "Experience unverified",
  ].filter(Boolean);
  card.append(el("p", meta.join(" · "), "job-meta"));
  if (state.tracker) {
    const update = el("div", undefined, "application-summary");
    update.append(el("span", stages[record.stage] || stages.applied, "tag"));
    if (record.followUp) {
      const due = followUpState(record) === "due";
      update.append(el("span", (due ? "Follow-up due · " : "Follow-up · ") + dateText(record.followUp),
        due ? "follow-up-due" : "job-meta"));
    }
    card.append(update);
    if (record.notes) {
      const notes = el("details", undefined, "reasons");
      notes.append(el("summary", "Private notes"), el("p", record.notes, "application-notes"));
      card.append(notes);
    }
  }
  if (state.shortlist && !state.jobsError && !state.jobIds.has(String(job.id)))
    card.append(el("p", "This posting has left the live feed.", "job-meta"));
  const tags = el("div", undefined, "tags");
  for (const text of [
    ...new Set([...(job.families || []), ...(job.skills || [])]),
  ].slice(0, 5))
    tags.append(el("span", text, "tag"));
  if (tags.childElementCount) card.append(tags);
  if (match?.reasons?.length || job.experienceEvidence) {
    const details = el(
      "details",
      undefined,
      match?.uncertain ? "reasons uncertain" : "reasons",
    );
    details.append(
      el(
        "summary",
        match?.uncertain
          ? "Possible match · review details"
          : match?.reasons?.length ? "Why this matches" : "Experience requirement",
      ),
    );
    const list = el("ul");
    for (const reason of match?.reasons || []) list.append(el("li", reason));
    if (job.experienceEvidence) list.append(el("li", "From the posting: “" + job.experienceEvidence + "”"));
    details.append(list);
    card.append(details);
  }
  const actions = el("div", undefined, "actions");
  const link = postingLink(job);
  if (link) actions.append(link);
  const id = String(job.id),
    applied = state.applied.has(id);
  if (state.archive) {
    const restore = button("Restore", "track", () => changeArchive(job, true, restore));
    restore.disabled = state.busy.has(id);
    actions.append(restore);
    card.append(actions);
    return card;
  }
  const source = state.sourceByKey.get(id.split(":", 2).join(":"));
  if (source?.status === "stale")
    card.append(
      el(
        "p",
        "Showing the last successful board scan. Check the original posting for availability.",
        "reasons uncertain",
      ),
    );
  const label = applied
    ? state.tracker
      ? "Remove from tracker"
      : "✓ Applied"
    : state.user
      ? "Mark as applied"
      : "Sign in to track";
  const track = button(label, "track", () => {
    if (!state.user) {
      location.assign("/account");
      return;
    }
    if (applied && !state.tracker) {
      location.hash = "applications";
      return;
    }
    if (applied && !window.confirm("Remove this application and its saved details?")) return;
    toggleApplication(job, track);
  });
  track.dataset.job = id;
  track.disabled = state.busy.has(id) || state.sessionError;
  const controls = el("div", undefined, "job-controls");
  if (state.tracker) controls.append(button("Update", "track", () => openApplicationEditor(record)));
  controls.append(track);
  if (!state.tracker && !applied) {
    const saved = state.saved.has(id);
    const save = button(saved ? "Remove from shortlist" : "Save", "track", () => {
      if (state.user) changeShortlist(job, saved, save);
      else location.assign("/account");
    });
    save.disabled = state.busy.has(id) || state.sessionError;
    save.setAttribute("aria-label", (saved ? "Remove from shortlist " : "Save ") + job.title);
    controls.append(save);
  }
  if (!state.tracker && !state.shortlist) {
    const archive = button("Archive", "track", () => {
      if (state.user) changeArchive(job, false, archive);
      else location.assign("/account");
    });
    archive.disabled = state.busy.has(id) || state.sessionError;
    archive.setAttribute("aria-label", "Archive " + job.title);
    controls.append(archive);
  }
  actions.append(controls);
  card.append(actions);
  return card;
}
async function changeArchive(job, restore, control) {
  const id = String(job.id);
  if (state.busy.has(id)) return;
  state.busy.add(id);
  if (control) control.disabled = true;
  try {
    const record = await api("archive", restore ? "DELETE" : "PUT", { jobId: id });
    if (restore) state.archived.delete(id);
    else state.archived.set(id, record);
    state.busy.delete(id);
    rebuildMatches();
    renderMetrics();
    renderResults();
    $("query").focus({ preventScroll: true });
    if (restore) {
      const open = state.jobs.some((entry) => String(entry.id) === id);
      toast(open ? "Posting restored." : "Posting restored. It has left the live feed.");
    } else {
      toast("Posting archived.", () => changeArchive(job, true));
    }
  } catch (error) {
    if (error.status === 401) location.assign("/account");
    else toast(error.status === 404 ? "This posting has left the feed." : "Could not update the archive. Try again.");
  } finally {
    state.busy.delete(id);
    if (control?.isConnected) control.disabled = false;
  }
}
async function changeShortlist(job, remove, control) {
  const id = String(job.id);
  if (state.busy.has(id)) return;
  state.busy.add(id);
  control.disabled = true;
  try {
    const result = await api("shortlist", remove ? "DELETE" : "PUT", {jobId: id});
    if (remove) state.saved.delete(id);
    else state.saved.set(id, result);
    toast(remove ? "Removed from your shortlist." : "Saved to your shortlist.");
  } catch (error) {
    if (error.status === 401) location.assign("/account");
    else toast(error.status === 404 ? "This posting has left the live feed." : "Could not update the shortlist.");
  } finally {
    state.busy.delete(id);
    renderResults();
    $("query").focus({preventScroll:true});
  }
}

function openApplicationEditor(record) {
  editingApplication = String(record.job.id);
  $("application-role").textContent = record.job.title + " · " + record.job.company;
  $("application-stage").value = record.stage || "applied";
  $("application-follow-up").value = record.followUp || "";
  $("application-notes").value = record.notes || "";
  $("application-error").textContent = "";
  $("application-editor").showModal();
}

async function saveApplication(event) {
  event.preventDefault();
  const id = editingApplication;
  const dialog = $("application-editor");
  const save = $("save-application");
  save.disabled = true;
  try {
    const record = await api("applications/details", "PUT", {
      jobId:id,
      stage:$("application-stage").value,
      followUp:$("application-follow-up").value || null,
      notes:$("application-notes").value,
    });
    state.applied.set(id, record);
    dialog.close();
    renderMetrics();
    renderResults();
    $("tracker-filter").focus({preventScroll:true});
    toast("Application updated.");
  } catch (error) {
    if (error.status === 401) location.assign("/account");
    else $("application-error").textContent = error.status === 404
      ? "This application was removed. Reload to sync your tracker."
      : "Could not save your changes. Try again.";
  } finally {
    save.disabled = false;
  }
}

async function toggleApplication(job, control) {
  const id = String(job.id);
  if (state.busy.has(id)) return;
  const remove = state.applied.has(id);
  state.busy.add(id);
  control.disabled = true;
  try {
    const result = await api("applications", remove ? "DELETE" : "PUT", {
      jobId: job.id,
    });
    if (remove) state.applied.delete(id);
    else {
      state.applied.set(id, result);
      state.saved.delete(id);
    }
    toast(
      remove ? "Application removed." : "Application added to your tracker.",
    );
  } catch (error) {
    if (error.status === 401) {
      location.assign("/account");
      return;
    }
    toast(
      error.status === 404
        ? "This posting changed. Refresh the feed and try again."
        : "Could not update the tracker. Please try again.",
    );
  } finally {
    state.busy.delete(id);
    rebuildMatches();
    renderMetrics();
    renderResults();
    const next = [...$("cards").querySelectorAll("button[data-job]")].find(
      (b) => b.dataset.job === id,
    );
    (next || $("query")).focus({ preventScroll: true });
  }
}
function emptyState(title, message) {
  const panel = el("div", undefined, "empty");
  panel.append(el("h3", title), el("p", message));
  return panel;
}
function renderResults() {
  if (!state.ready) return;
  const query = lower(state.query).split(/\s+/).filter(Boolean);
  const src = state.archive ? [...state.archived.values()] :
    state.shortlist ? [...state.saved.values()].filter(({job}) => !state.archived.has(String(job.id))) :
    state.tracker ? [...state.applied.values()] : state.matches;
  const trackerFilter = state.tracker && $("tracker-filter").value;
  const visible = trackerFilter
    ? src.filter((record) => trackerFilter === "due" || trackerFilter === "planned"
      ? followUpState(record) === trackerFilter : (record.stage || "applied") === trackerFilter)
    : src;
  const items = query.length
    ? visible.filter(({ job }) => {
        const fields = [
          job.title,
          job.company,
          job.location,
          ...(job.families || []),
          ...(job.skills || []),
        ]
          .join(" ")
          .toLowerCase();
        return query.every((word) => fields.includes(word));
      })
    : [...visible];
  const sort = state.sort;
  items.sort((a, b) => {
    if (sort === "company")
      return (
        collate.compare(a.job.company, b.job.company) ||
        collate.compare(a.job.title, b.job.title)
      );
    if (sort === "match" && !state.tracker) {
      if (a.match.uncertain !== b.match.uncertain)
        return Number(a.match.uncertain) - Number(b.match.uncertain);
      if (a.match.score !== b.match.score) return b.match.score - a.match.score;
    }
    const dates =
      sort === "applied"
        ? [a.appliedAt, b.appliedAt]
        : sort === "archived" ? [a.archivedAt, b.archivedAt] :
          sort === "saved" ? [a.savedAt, b.savedAt] : [a.job.posted, b.job.posted];
    if (trackerFilter === "due" || trackerFilter === "planned") {
      const order = a.followUp.localeCompare(b.followUp);
      if (order) return order;
    }
    return (
      (Date.parse(dates[1]) || 0) - (Date.parse(dates[0]) || 0) ||
      collate.compare(a.job.title, b.job.title)
    );
  });
  const pages = Math.max(1, Math.ceil(items.length / pageSize));
  state.page = Math.max(1, Math.min(state.page, pages));
  const start = (state.page - 1) * pageSize;
  const cards = $("cards");
  cards.replaceChildren();
  if (items.length) {
    const slice = items.slice(start, start + pageSize);
    $("result-line").textContent =
      number.format(start + 1) +
      "–" +
      number.format(start + slice.length) +
      " of " +
      number.format(items.length) +
      (state.archive ? " archived postings" : state.shortlist ? " shortlisted roles" : state.tracker ? " tracked applications" : " matching roles");
    cards.append(...slice.map(jobCard));
  } else {
    $("result-line").textContent = "";
    if (state.shortlist && !src.length)
      cards.append(emptyState("No shortlisted roles", state.user
        ? "Choose Save on a promising role in Discover to keep it here."
        : "Sign in to save roles for later."));
    else if (state.archive && !state.archived.size)
      cards.append(emptyState("No archived postings", state.user
        ? "Choose Archive on a posting in Discover to hide it from your searches."
        : "Sign in to see your archived postings."));
    else if (state.tracker && !state.user)
      cards.append(
        emptyState(
          "Your application tracker",
          "Sign in to see roles you have marked as applied.",
        ),
      );
    else if (state.tracker && !state.applied.size)
      cards.append(
        emptyState(
          "Your first application goes here",
          "After applying on a company’s career page, choose “Mark as applied” in Discover.",
        ),
      );
    else if (state.tracker && trackerFilter && !visible.length)
      cards.append(emptyState("No applications in this view", "Choose another stage or follow-up filter."));
    else if (state.jobsError && !state.jobs.length && !state.tracker && !state.archive)
      cards.append(
        emptyState(
          "Feed unavailable",
          "Retry the feed when your connection is ready.",
        ),
      );
    else if (!state.jobs.length && !state.tracker && !state.archive)
      cards.append(
        emptyState(
          "Waiting for listings",
          "The next successful board update will populate your feed.",
        ),
      );
    else
      cards.append(
        emptyState(
          "No matching roles",
          query.length
            ? "Try another keyword or clear the search field."
            : state.archive ? "Archive a posting from Discover to find it here." :
              "Adjust your location, experience or role families to broaden this search.",
        ),
      );
  }
  cards.setAttribute("aria-busy", "false");
  $("pager").hidden = pages < 2;
  $("page-label").textContent =
    "Page " + state.page + " of " + number.format(pages);
  $("prev").disabled = state.page === 1;
  $("next").disabled = state.page === pages;
}
function renderPage() {
  renderNotices();
  renderAccount();
  preferenceSummary();
  renderCoverage();
  renderMetrics();
  renderResults();
}
function setView() {
  const tracker = location.hash === "#applications";
  const archive = location.hash === "#archive";
  const shortlist = location.hash === "#shortlist";
  state.tracker = tracker;
  state.archive = archive;
  state.shortlist = shortlist;
  state.sort = archive ? "archived" : shortlist ? "saved" : tracker ? "applied" : "match";
  $("tracker-tools").hidden = !tracker;
  state.page = 1;
  state.query = $("query").value = "";
  $("view-title").replaceChildren(
    archive ? "Archive" : shortlist ? "Shortlist" : tracker ? "Application tracker" : "Opportunity feed",
    el("span", "."),
  );
  $("subtitle").textContent = shortlist ? "Promising roles to revisit before you apply." :
    archive ? "Review hidden postings and restore them to Discover." : tracker
    ? "The roles you’ve applied to, including postings that have left the feed."
    : "Roles from company career boards, matched to your search preferences.";
  $("results-title").textContent = shortlist ? "Saved roles" : archive ? "Archived postings" : tracker
    ? "Tracked applications"
    : "Job matches";
  for (const [id, current] of [
    ["nav-feed", !tracker && !archive && !shortlist],
    ["nav-shortlist", shortlist],
    ["nav-apps", tracker],
    ["nav-archive", archive],
  ]) {
    if (current) $(id).setAttribute("aria-current", "page");
    else $(id).removeAttribute("aria-current");
  }
  $("sort").options[0] = new Option(
    archive ? "Recently archived" : shortlist ? "Recently saved" : tracker ? "Recently applied" : "Best match",
    state.sort,
  );
  $("sort").value = state.sort;
  document.title = (archive ? "Archive" : shortlist ? "Shortlist" : tracker ? "Applications" : "Discover") + " · Role Atlas";
  if (state.ready) {
    renderNotices();
    preferenceSummary();
  }
  renderResults();
}
function populateChoices(options, choices, selected) {
  options.replaceChildren();
  for (const [value, title] of choices) {
    const label = el("label");
    const box = el("input");
    box.type = "checkbox";
    box.value = value;
    box.checked = selected.includes(value);
    label.append(box, document.createTextNode(" " + title));
    options.append(label);
  }
}
function populateForm(p) {
  populateChoices($("family-options"), families.map((family) => [family, family]), p.families);
  populateChoices($("level-options"), Object.entries(levelLabels), p.levels || []);
  $("pref-location").value = p.location || "";
  $("pref-years").value = p.years ?? "";
  $("pref-skills").value = p.skills.join(", ");
  $("pref-workplace").value = p.workplace || "";
  $("pref-age").value = p.maxAgeDays || "";
  $("pref-undated").checked = p.includeUndated !== false;
  $("pref-uncertain").checked = Boolean(p.includeUncertain);
  $("hide-applied-option").hidden = !state.user;
  $("pref-hide-applied").checked = Boolean(p.hideApplied);
}
function openPreferences() {
  populateForm(state.preferences);
  $("pref-message").textContent = state.user
    ? ""
    : "Sign in to save preferences across visits.";
  $("save-prefs").textContent = state.user
    ? "Save preferences"
    : "Preview matches";
  $("pref-dialog").showModal();
}
async function savePreferences(event) {
  event.preventDefault();
  const prefs = {
    families: [...$("family-options").querySelectorAll(":checked")].map(
      (box) => box.value,
    ),
    levels: [...$("level-options").querySelectorAll(":checked")].map(
      (box) => box.value,
    ),
    location: $("pref-location").value.trim(),
    years: $("pref-years").value === "" ? null : Number($("pref-years").value),
    skills: [
      ...new Set(
        $("pref-skills")
          .value.split(",")
          .map((s) => s.trim())
          .filter(Boolean),
      ),
    ],
    workplace: $("pref-workplace").value,
    includeUncertain: $("pref-uncertain").checked,
    hideApplied: $("pref-hide-applied").checked,
    maxAgeDays: Number($("pref-age").value) || null,
    includeUndated: $("pref-undated").checked,
  };
  if (!prefs.families.length) {
    $("pref-message").textContent = "Choose at least one role family.";
    $("family-options").querySelector("input").focus();
    return;
  }
  $("save-prefs").disabled = true;
  try {
    if (state.user) await api("preferences", "PUT", prefs);
    state.preferences = prefs;
    state.page = 1;
    rebuildMatches();
    renderPage();
    $("pref-dialog").close();
    toast(
      state.user
        ? "Search preferences saved."
        : "Search preferences applied for this visit.",
    );
  } catch (error) {
    const message = $("pref-message");
    message.textContent =
      error.status === 401
        ? "Your session expired. "
        : "Could not save your preferences. Check the fields and try again.";
    if (error.status === 401) message.append(signInLink());
  } finally {
    $("save-prefs").disabled = false;
  }
}

$("query").addEventListener("input", () => {
  state.query = $("query").value;
  state.page = 1;
  clearTimeout(queryTimer);
  queryTimer = setTimeout(renderResults, 120);
});
$("sort").addEventListener("change", () => {
  state.sort = $("sort").value;
  state.page = 1;
  renderResults();
});
for (const [value, label] of Object.entries(stages)) {
  $("application-stage").add(new Option(label, value));
  $("tracker-filter").add(new Option(label, value));
}
$("application-form").addEventListener("submit", saveApplication);
$("tracker-filter").addEventListener("change", () => {
  state.page = 1;
  renderResults();
});
$("due-shortcut").onclick = () => {
  $("tracker-filter").value = "due";
  state.page = 1;
  renderResults();
};
for (const [id, offset] of [
  ["prev", -1],
  ["next", 1],
]) {
  $(id).addEventListener("click", () => {
    state.page += offset;
    renderResults();
    $("results-title").scrollIntoView({ block: "start" });
    $("query").focus({ preventScroll: true });
  });
}
for (const btn of document.querySelectorAll("[data-close]"))
  btn.addEventListener("click", () => btn.closest("dialog").close());
$("edit-top").onclick = $("edit-side").onclick = openPreferences;
$("view-sources").onclick = openSources;
$("refresh").onclick = () => {
  refreshCatalog(true);
  readScanStatus();
};
setInterval(() => {
  if (!document.hidden) readScanStatus();
}, 15000);
setInterval(() => {
  if (!document.hidden) refreshCatalog();
}, 90000);
$("reset-prefs").onclick = () => populateForm(defaults);
$("pref-form").addEventListener("submit", savePreferences);
for (const [id, checked] of [
  ["all-families", true],
  ["clear-families", false],
]) {
  $(id).onclick = () => {
    for (const input of $("family-options").querySelectorAll("input"))
      input.checked = checked;
  };
}
window.addEventListener("hashchange", setView);
window.addEventListener("pageshow", (event) => {
  if (event.persisted) load();
});
setView();
load().catch(() => {
  $("cards").setAttribute("aria-busy", "false");
  $("result-line").replaceChildren(
    "The dashboard could not load. ",
    button("Retry", "text-btn", () => location.reload()),
  );
});
