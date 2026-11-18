"""Adapters for employer-operated career feeds outside the original three ATS providers."""

import datetime as dt
import html
import json
import re
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError
from urllib.parse import urlencode, urljoin, urlsplit
from xml.etree import ElementTree


def job(
    source, identifier, title, location, url, description="", posted=None, workplace=""
):
    if not identifier or not title or not url.startswith("https://"):
        raise ValueError("Incomplete listing")
    return {
        "id": f"{source['provider']}:{source['slug']}:{identifier}",
        "company": source["company"],
        "title": html.unescape(title),
        "location": html.unescape(location or ""),
        "url": url,
        "description": html.unescape(description or ""),
        "posted": posted,
        "workplace": {"on-site": "onsite", "on site": "onsite"}.get(
            workplace.lower(), workplace.lower()
        ),
    }


def qualifications(required, preferred=None, general=None):
    return (
        (general or "")
        + "\nMinimum qualifications\n"
        + (required or "")
        + "\nPreferred qualifications\n"
        + (preferred or "")
    )


def pages(fetch, identify, limit):
    """Require forward progress so pagination bugs cannot delete earlier results."""
    offset = 0
    seen = set()
    while True:
        rows, total = fetch(offset, limit)
        if not isinstance(rows, list):
            raise ValueError("Unexpected listing format")
        ids = {identify(row) for row in rows}
        if rows and not ids - seen:
            raise ValueError("Pagination stopped advancing")
        for row in rows:
            identifier = identify(row)
            if identifier not in seen:
                seen.add(identifier)
                yield row
        offset += len(rows)
        if total is not None and offset >= total:
            return
        if not rows:
            if total:
                raise ValueError(f"Page ended before {total} reported listings")
            return
        if total is None and len(rows) < limit:
            return


def posted(value):
    if isinstance(value, (float, int)):
        return (
            dt.datetime.fromtimestamp(
                value / (1000 if value > 10**11 else 1), dt.timezone.utc
            )
            .date()
            .isoformat()
        )
    if isinstance(value, str) and re.match(r"\d{4}-\d{2}-\d{2}", value):
        return value[:10]
    if value:
        for fmt in ("%B %d, %Y", "%Y-%m-%d %I:%M %p"):
            try:
                return dt.datetime.strptime(value, fmt).date().isoformat()
            except ValueError:
                continue
    return None


def amazon(source, get):
    base = "https://www.amazon.jobs"

    def fetch(offset, limit):
        data = get(
            base
            + "/en/search.json?"
            + urlencode(
                dict(offset=offset, result_limit=limit, sort="recent", country="IND")
            )
        )
        return data["jobs"], data["hits"]

    for row in pages(fetch, lambda r: r["id_icims"], 100):
        location = " · ".join(filter(None, [row.get("normalized_location"), "India"]))
        yield job(
            source,
            row["id_icims"],
            row["title"],
            location,
            urljoin(base, row["job_path"]),
            qualifications(
                row.get("basic_qualifications"),
                row.get("preferred_qualifications"),
                row.get("description"),
            ),
            posted(row.get("posted_date")),
        )


def atlassian(source, get):
    data = get("https://www.atlassian.com/endpoint/careers/listings")
    if not isinstance(data, list):
        raise ValueError("Unexpected Atlassian listing format")
    for row in data:
        portal = row.get("portalJobPost") or {}
        yield job(
            source,
            row.get("id") or portal.get("id"),
            row["title"],
            " · ".join(row.get("locations") or []),
            portal.get("portalUrl") or row["applyUrl"],
            qualifications(row.get("qualifications"), general=row.get("overview")),
        )


def microsoft(source, get):
    base = "https://apply.careers.microsoft.com"

    def fetch(offset, limit):
        response = get(
            base
            + "/api/pcsx/search?"
            + urlencode(dict(domain="microsoft.com", location="India", start=offset))
        )
        payload = response["data"]
        return payload["positions"], payload.get("count") or payload.get("totalCount")

    for row in pages(fetch, lambda r: r["id"], 10):
        identifier = row["id"]
        description = row.get("jobDescription") or ""
        if not description:
            detail = get(
                base
                + "/api/pcsx/position_details?"
                + urlencode(
                    dict(domain="microsoft.com", position_id=identifier, hl="en")
                )
            )["data"]
            description = detail.get("jobDescription") or ""
        yield job(
            source,
            identifier,
            row["name"],
            " · ".join(row.get("locations") or ["India"]),
            f"{base}/careers/job/{identifier}",
            description,
            posted(row.get("postedTs")),
            row.get("workLocationOption") or "",
        )


def oracle(source, get):
    base = f"https://{source['host']}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"

    def fetch(offset, limit):
        finder = f"findReqs;siteNumber={source['site']},limit={limit},offset={offset},sortBy=POSTING_DATES_DESC"
        payload = get(
            base
            + "?"
            + urlencode(
                dict(
                    onlyData="true",
                    expand="requisitionList.secondaryLocations",
                    finder=finder,
                )
            )
        )
        items = payload["items"]
        if len(items) != 1:
            raise ValueError("Unexpected Oracle HCM response")
        return items[0]["requisitionList"], items[0].get("TotalJobsCount")

    for row in pages(fetch, lambda r: r["Id"], 25):
        locs = [row.get("PrimaryLocation"), row.get("PrimaryLocationCountry")] + [
            place.get("Name") for place in row.get("secondaryLocations") or []
        ]
        yield job(
            source,
            row["Id"],
            row["Title"],
            " · ".join(dict.fromkeys(filter(None, locs))),
            source["listing"].format(id=row["Id"]),
            qualifications(
                row.get("ExternalQualificationsStr"),
                general=row.get("ShortDescriptionStr"),
            ),
            posted(row.get("PostedDate")),
            row.get("WorkplaceType") or "",
        )


def google(source, get):
    base = "https://www.google.com/about/careers/applications/"
    seen = set()
    for number in range(1, 251):
        page = get(
            base + "jobs/results?" + urlencode(dict(location="India", page=number)),
            raw=True,
        )
        found = set()
        previous = set(seen)
        # The visible listing cards include the minimum qualifications before the job link.
        cards = re.split(r"(?=<h3\b[^>]*>)", page)
        for card in cards:
            title = re.match(r"<h3\b[^>]*>(.*?)</h3>", card, re.S)
            link = re.search(r'href="(jobs/results/(\d+)-[^"?]+)', card)
            if not title or not link:
                continue
            minimum = re.search(
                r"Minimum qualifications\s*</h4>\s*(<ul\b.*?</ul>)", card, re.S | re.I
            )
            identifier = link[2]
            found.add(identifier)
            if identifier in seen:
                continue
            seen.add(identifier)
            places = re.findall(r'<span class="r0wTof[^"]*">([^<]+)', card)
            yield job(
                source,
                identifier,
                re.sub(r"<[^>]+>", "", title[1]),
                " · ".join(places) or "India",
                urljoin(base, link[1]),
                qualifications(minimum[1] if minimum else ""),
            )
        if not found:
            raise ValueError("Google career cards missing")
        if not found - previous:
            raise ValueError("Google pagination stopped advancing")
        if 'aria-label="Go to next page"' not in page:
            return
    raise ValueError("Google pagination exceeded safety limit")


def workday(source, get):
    base = f"https://{source['slug']}.{source['instance']}.myworkdayjobs.com"
    api = f"{base}/wday/cxs/{source['slug']}/{source['site']}"

    def listing(offset, limit, facets, search=""):
        body = dict(appliedFacets=facets, limit=limit, offset=offset, searchText=search)
        return get(api + "/jobs", body=body)

    initial = listing(0, 1, {})
    candidates = [
        (group["facetParameter"], value["id"])
        for group in initial.get("facets", [])
        for value in group.get("values", [])
        if value.get("descriptor", "").lower() == "india"
        and re.search("location|country", group["facetParameter"], re.I)
    ]
    facet = next(
        (pair for pair in candidates if "country" in pair[0].lower()),
        candidates[0] if candidates else None,
    )
    facets = {facet[0]: [facet[1]]} if facet else {}

    def fetch(offset, limit):
        payload = listing(offset, limit, facets, "" if facets else "India")
        return payload["jobPostings"], payload["total"]

    for row in pages(fetch, lambda r: r["externalPath"], 20):
        path = row["externalPath"]
        try:
            details = get(api + path)["jobPostingInfo"]
        except HTTPError as exc:
            if exc.code == 404:
                continue
            raise
        locations = [details.get("location") or row.get("locationsText")] + list(
            details.get("additionalLocations") or []
        )
        if facets:
            locations.append("India")
        yield job(
            source,
            path.rsplit("_", 1)[-1],
            row["title"],
            " · ".join(dict.fromkeys(filter(None, locations))),
            details.get("externalUrl") or f"{base}/{source['site']}{path}",
            details.get("jobDescription"),
            posted(details.get("startDate")),
        )


def wipro(source, get):
    base = "https://careers.wipro.com"
    seen = set()
    for term in (
        "",
        "developer",
        "software",
        "data",
        "analytics",
        "cloud",
        "AI",
        "security",
        "engineer",
        "test",
        "consultant",
    ):
        keywords = (f"({term}) AND " if term else "") + "locationSearch:(India)"
        url = (
            base
            + "/services/rss/job/?"
            + urlencode(dict(locale="en_US", keywords=keywords))
        )
        feed = ElementTree.fromstring(get(url, raw=True))
        channel = feed.find("channel")
        if channel is None:
            raise ValueError("Wipro feed missing channel")
        for item in channel.findall("item"):
            link = item.findtext("link")
            path = urlsplit(link).path
            identifier = path.strip("/").rsplit("/", 1)[-1]
            if identifier in seen:
                continue
            seen.add(identifier)
            details = get(base + path, raw=True)
            description = re.search(
                r'<[^>]*itemprop=["\x27]description["\x27][^>]*>([\s\S]*)',
                details,
                re.I,
            )
            fragment = (
                re.split(
                    r"</(?:section|main)>|<footer\b",
                    description[1],
                    maxsplit=1,
                    flags=re.I,
                )[0]
                if description
                else ""
            )
            title = item.findtext("title")
            heading, sep, location = title.rpartition(" (")
            date = item.findtext("pubDate")
            yield job(
                source,
                identifier,
                heading if sep else title,
                (location.rstrip(")") + " · India") if sep else "India",
                base + path,
                fragment or item.findtext("description"),
                parsedate_to_datetime(date).date().isoformat() if date else None,
            )


def cisco(source, get):
    base = "https://careers.cisco.com/global/en/search-results"

    def fetch(offset, limit):
        page = get(
            base + "?" + urlencode({"location": "India", "from": offset, "s": 1}),
            raw=True,
        )
        match = re.search(r'"eagerLoadRefineSearch"\s*:\s*(?=\{)', page)
        if not match:
            raise ValueError("Cisco search results missing")
        data = json.JSONDecoder().raw_decode(page[match.end() :])[0]
        return data["data"]["jobs"], data["totalHits"]

    for row in pages(fetch, lambda r: r["jobId"], 10):
        candidates = row.get("multi_location") or [
            row.get("cityStateCountry") or row.get("location")
        ]
        location = " · ".join(dict.fromkeys(filter(None, candidates)))
        description = (row.get("ml_job_parser") or {}).get(
            "descriptionTeaser"
        ) or row.get("descriptionTeaser")
        link = row["applyUrl"].removesuffix("/apply")
        yield job(
            source,
            row["jobId"],
            row["title"],
            location,
            link,
            description,
            posted(row.get("postedDate")),
        )


def structured(page, kind):
    for match in re.finditer(
        r'<script\s[^>]*type=["\x27]([^"\x27]+)["\x27][^>]*>([\s\S]*?)</script>',
        page,
        re.I,
    ):
        if html.unescape(match[1]).lower() != "application/ld+json":
            continue
        data = json.loads(match[2])
        for obj in data if isinstance(data, list) else [data]:
            if obj.get("@type") == kind:
                return obj
    raise ValueError(f"Structured {kind} data missing")


def postman(source, get):
    rows = get("https://www.postman.com/_mk-www-next/api-cache/careers-jobs.json")[
        "jobs"
    ]
    if not isinstance(rows, list):
        raise ValueError("Unexpected Postman listing format")
    for row in rows:
        yield job(
            source,
            row["id"],
            row["title"],
            row["location"],
            row["url"],
            row.get("description"),
        )


def fractal(source, get):
    listing = structured(get(source["careers"], raw=True), "ItemList")
    rows = listing.get("itemListElement") or []
    for row in rows if isinstance(rows, list) else [rows]:
        link = row["url"].split("?", 1)[0]
        detail = structured(get(link, raw=True), "JobPosting")
        places = detail.get("jobLocation") or []
        location = []
        for place in places if isinstance(places, list) else [places]:
            address = place.get("address") or {}
            location.extend(
                address.get(field)
                for field in ("addressLocality", "addressRegion", "addressCountry")
            )
        yield job(
            source,
            link.rsplit("-", 1)[-1],
            detail.get("title") or row["name"],
            " · ".join(dict.fromkeys(v for v in location if isinstance(v, str) and v)),
            link,
            detail.get("description"),
            posted(detail.get("datePosted")),
        )


def apple(source, get):
    base = "https://jobs.apple.com"
    seen = set()
    for number in range(1, 251):
        url = (
            base
            + "/en-in/search?"
            + urlencode(dict(location="india-INDC", sort="newest", page=number))
        )
        page = get(url, raw=True)
        hydration = re.search(
            r'__staticRouterHydrationData = JSON\.parse\(("(?:[^"\\]|\\.)*")\)', page
        )
        if not hydration:
            raise ValueError("Apple career records missing")
        search = json.loads(json.loads(hydration[1]))["loaderData"]["search"]
        rows = search["searchResults"]
        if not rows:
            return
        previous = len(seen)
        for row in rows:
            identifier = row["positionId"]
            if identifier in seen:
                continue
            seen.add(identifier)
            details = get(f"{base}/api/v1/jobDetails/{identifier}")["res"]
            location = [place.get("name") for place in row.get("locations") or []] + [
                "India"
            ]
            yield job(
                source,
                identifier,
                row["postingTitle"],
                " · ".join(dict.fromkeys(filter(None, location))),
                f"{base}/en-in/details/{identifier}/{row.get('transformedPostingTitle', '')}",
                qualifications(
                    details.get("minimumQualifications"),
                    details.get("preferredQualifications"),
                    details.get("description"),
                ),
                posted(row.get("postDateInGMT")),
            )
        if len(seen) == previous:
            raise ValueError("Apple pagination stopped advancing")
        if search.get("totalRecords") and len(seen) >= search["totalRecords"]:
            return
        if len(rows) < 20:
            return
    raise ValueError("Apple pagination exceeded safety limit")


def smartrecruiters(source, get):
    base = f"https://api.smartrecruiters.com/v1/companies/{source['slug']}/postings"

    def fetch(offset, limit):
        payload = get(
            base + "?" + urlencode(dict(country="in", offset=offset, limit=limit))
        )
        return payload["content"], payload["totalFound"]

    for row in pages(fetch, lambda r: r["id"], 100):
        identifier = row["id"]
        try:
            detail = get(f"{base}/{identifier}")
        except HTTPError as exc:
            if exc.code == 404:
                continue
            raise
        sections = detail["jobAd"]["sections"]
        location = detail.get("location") or row["location"]
        workplace = (
            "remote"
            if location.get("remote")
            else "hybrid"
            if location.get("hybrid")
            else ""
        )
        body = qualifications(
            (sections.get("qualifications") or {}).get("text"),
            general=(sections.get("jobDescription") or {}).get("text"),
        )
        yield job(
            source,
            identifier,
            row["name"],
            location.get("fullLocation") or "India",
            detail["postingUrl"],
            body,
            posted(detail.get("releasedDate")),
            workplace,
        )


ADAPTERS = {
    "google": google,
    "microsoft": microsoft,
    "oracle": oracle,
    "amazon": amazon,
    "atlassian": atlassian,
    "workday": workday,
    "wipro": wipro,
    "fractal": fractal,
    "apple": apple,
    "cisco": cisco,
    "postman": postman,
    "smartrecruiters": smartrecruiters,
}
