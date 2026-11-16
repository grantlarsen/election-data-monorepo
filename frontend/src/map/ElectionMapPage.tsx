import { JurisdictionDetail, ResultsTable } from "./MapResults";
import { lazy, Suspense, useCallback, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { FilterLink, Notice } from "../components";
import { humanize, validateSearch } from "../filters";
import { sourceUrl } from "../api";
import { MapSources } from "./MapSources";
import { number } from "./types";
import {
  candidateColor,
  missingColor,
  tieColor,
  indeterminateColor,
  partyPalette,
} from "./electionColors";
import type { MapUnit } from "./types";
import { useElectionMap } from "./useElectionMap";
import { StateResultsSummary } from "./StateResultsSummary";
import { CandidateLink } from "../CandidateLink";

const GeographyMap = lazy(() =>
  import("./GeographyMap").then((module) => ({ default: module.GeographyMap })),
);

export function ElectionMapPage() {
  const [params, setParams] = useSearchParams();
  const [sort, setSort] = useState("name");
  const error =
    validateSearch(params) ||
    (params.has("map_unit") &&
    !/^(?:\d{2}|\d{4}|\d{5})$/.test(params.get("map_unit") || "")
      ? "Choose a valid jurisdiction map unit."
      : params.getAll("map_unit").length > 1
        ? "Choose only one jurisdiction map unit."
        : params.has("map_unit") && !params.get("state_code")
          ? "Choose a state before selecting a jurisdiction map unit."
          : null);
  const unsupportedLevel =
    params.has("reporting_level") &&
    !["county", "congressional_district"].includes(
      params.get("reporting_level")!,
    );
  const query = new URLSearchParams();
  for (const key of [
    "year",
    "office",
    "stage",
    "state_code",
    "jurisdiction_id",
  ]) {
    const value = params.get(key);
    if (value) query.set(key, value);
  }
  if (
    (params.get("office") || "").trim().toLowerCase() === "u.s. house" ||
    params.get("reporting_level") === "congressional_district"
  ) {
    query.set("reporting_level", "congressional_district");
  } else if (
    params.get("state_code") &&
    params.get("reporting_level") === "county" &&
    (params.get("office") || "U.S. President").trim().toLowerCase() !==
      "u.s. senate"
  ) {
    query.set("reporting_level", "county");
  }
  const {
    data,
    error: loadError,
    retry,
  } = useElectionMap(query.toString(), !error && !unsupportedLevel);
  const select = useCallback(
    (unit: MapUnit) => {
      const next = new URLSearchParams(params);
      next.set("year", String(data?.year ?? params.get("year") ?? 2008));
      next.set(
        "office",
        data?.office ?? params.get("office") ?? "U.S. President",
      );
      next.set("stage", data?.stage ?? params.get("stage") ?? "general");
      next.set("state_code", unit.state_code);
      const drillDown = data?.drill_down_level === "county";
      const nextLevel =
        data?.drill_down_level || data?.reporting_level || "county";
      if (nextLevel === "state") next.delete("reporting_level");
      else next.set("reporting_level", nextLevel);
      next.delete("offset");
      next.delete("contest_id");
      next.delete("jurisdiction_id");
      next.delete("map_unit");
      if (!drillDown) {
        if (unit.geoid) next.set("map_unit", unit.geoid);
        if (unit.jurisdiction_id)
          next.set("jurisdiction_id", unit.jurisdiction_id);
      }
      setParams(next);
    },
    [params, data, setParams],
  );
  const national = new URLSearchParams(params);
  national.delete("state_code");
  national.delete("jurisdiction_id");
  national.delete("offset");
  national.delete("map_unit");
  const state = new URLSearchParams(params);
  state.delete("jurisdiction_id");
  state.delete("map_unit");
  const selected = data?.units.find((unit) =>
    params.has("jurisdiction_id")
      ? unit.jurisdiction_id === params.get("jurisdiction_id")
      : data.state_code && unit.id === params.get("map_unit"),
  );
  const selectionError =
    data && params.has("map_unit") && selected?.id !== params.get("map_unit");
  const sorted = [...(data?.units || [])].sort((a, b) =>
    sort === "votes"
      ? (b.summary.total_votes ?? -1) - (a.summary.total_votes ?? -1) ||
        a.name.localeCompare(b.name)
      : sort === "margin"
        ? (b.summary.margin_pp ?? -1) - (a.summary.margin_pp ?? -1) ||
          a.name.localeCompare(b.name)
        : a.name.localeCompare(b.name),
  );
  const units = selected ? [selected] : sorted;
  const candidateResults = (data?.units || []).flatMap(unit => unit.summary.candidates
    .filter(candidate => ["candidate", "source_candidate"].includes(candidate.kind)));
  const candidates = [
    ...new Set(
      candidateResults.map(candidate => candidate.label),
    ),
  ].sort();
  const legend: { label: string; color: string; candidacyId?: string | null }[] = [
    ...(data?.reporting_level === "congressional_district"
      ? Object.entries(partyPalette).map(([label, color]) => ({ label, color }))
      : candidates.map((label) => {
          const ids = new Set(candidateResults.filter(candidate => candidate.label === label).map(candidate => candidate.candidacy_id));
          return { label, color: candidateColor(label), candidacyId: ids.size === 1 ? [...ids][0] : null };
        })),
    { label: "Tie", color: tieColor },
    { label: "Undetermined / zero total", color: indeterminateColor },
    { label: "No published returns", color: missingColor },
  ];
  return (
    <>
      <header className="map-page-heading">
        <nav className="map-presets" aria-label="Election map examples">
          <Link to="/map?year=2024&office=U.S.+House&stage=general&reporting_level=congressional_district">2024 House districts</Link>
          <Link to="/map?year=2008&office=U.S.+President&stage=general">2008 President</Link>
        </nav>
        <h1 id="page-title" tabIndex={-1}>
          {data ? `${data.state_code || "United States"} · ${humanize(data.reporting_level).replace(/^./, (char) => char.toUpperCase())} returns` : "Election map"}
        </h1>
        <span className="map-election-context">
          {data?.year || params.get("year") || 2008} · {data?.office || params.get("office") || "U.S. President"} · {humanize(data?.stage || params.get("stage") || "general")}
        </span>
      <nav className="map-breadcrumb" aria-label="Map geography">
        <Link to={`/map?${national}`}>United States</Link>
        {data?.state_code && (
          <>
            <span aria-hidden="true"> / </span>
            <Link to={`/map?${state}`}>{data.state_code}</Link>
          </>
        )}
        {selected && (
          <>
            <span aria-hidden="true"> / </span>
            <span aria-current="location">{selected.name}</span>
          </>
        )}
      </nav>
      </header>
      {error ? (
        <Notice title="Review your filters" error>
          <p>{error}</p>
        </Notice>
      ) : unsupportedLevel || data?.availability === "unsupported_selection" ? (
        <Notice title="Map unavailable for this selection">
          <p>
            Federal election maps use state, county and congressional district
            reporting where published results and compatible boundary vintages
            are available.
          </p>
          <FilterLink to="/contests">Browse contests</FilterLink>
        </Notice>
      ) : loadError ? (
        <Notice title="Map data could not be loaded" error>
          <p>{loadError}</p>
          <button onClick={retry}>Try again</button>
        </Notice>
      ) : !data ? (
        <Notice title="Loading election map">
          <p>Retrieving boundaries and the current published results.</p>
        </Notice>
      ) : selectionError ? (
        <Notice title="Jurisdiction selection not available">
          <p>
            The map unit does not match this state and jurisdiction selection.
            Use the state breadcrumb to choose a reporting unit.
          </p>
        </Notice>
      ) : (
        <>
          {data.availability === "boundaries_unavailable" && (
            <Notice title="Map boundaries are not available yet">
              <p>
                The historical display package has not been prepared. Published
                results remain available below.
              </p>
            </Notice>
          )}
          {data.availability === "no_matching_published_results" && (
            <Notice title="No matching published results">
              <p>
                Missing returns do not mean zero votes. Choose another geography
                or browse contests.
              </p>
            </Notice>
          )}
          {data.features.features.length > 0 && (
            <Suspense fallback={<p role="status">Loading interactive map…</p>}>
              <GeographyMap
                key={`${data.year}:${data.office}:${data.reporting_level}:${data.state_code || "nation"}`}
                data={data}
                onSelect={select}
                selectedId={selected?.id}
              />
            </Suspense>
          )}
          <ul className="map-legend" aria-label="Map legend">
            {legend.map(({ label, color, candidacyId }) => (
              <li key={label}>
                <span
                  aria-hidden="true"
                  style={{
                    background: color,
                  }}
                />
                <CandidateLink candidacyId={candidacyId}>{label}</CandidateLink>
              </li>
            ))}
          </ul>
          <p className="result-count">
            {number(data.coverage.units_with_results)} areas with results
            {data.coverage.missing_results > 0 && ` · ${number(data.coverage.missing_results)} unavailable`}
            {data.coverage.results_without_geometry > 0 && ` · ${number(data.coverage.results_without_geometry)} without map shapes`}
          </p>
          {data.reporting_level === "county" && data.state_code && (
            <StateResultsSummary selection={data} />
          )}
          {selected && (
            <JurisdictionDetail selected={selected} params={params} />
          )}
          {!selected && <>
          <div className="map-table-heading">
            <h2>Votes, shares & margins</h2>
            <label>
              Sort units
              <select
                value={sort}
                onChange={(event) => setSort(event.target.value)}
              >
                <option value="name">Name A–Z</option>
                <option value="votes">Reported votes, highest first</option>
                <option value="margin">Margin, largest first</option>
              </select>
            </label>
          </div>
          <ResultsTable
            data={data}
            units={units}
            selected={selected}
            onSelect={select}
          />
          </>}
          <aside className="map-notes" aria-label="Sources and notes">
            {data.publications.some(publication => publication.status === "PARTIAL") &&
              <p className="coverage-warning">Partial coverage · Missing returns are not zero votes.</p>}
            <details>
              <summary>Sources & notes</summary>
              <MapSources publications={data.publications} />
              <p>{data.metric_note}</p>
              <p>{data.source_note}</p>
              {data.boundary && <p>{data.boundary.vintage_note} <a href={sourceUrl(data.boundary.documentation_url)}>Census boundaries</a></p>}
            </details>
          </aside>
        </>
      )}
    </>
  );
}
