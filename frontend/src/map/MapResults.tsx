import { Link } from "react-router";
import type { ElectionMap, MapUnit } from "./types";
import { margin, number, percent } from "./types";
import { filterSearch } from "../filters";

export function JurisdictionDetail({
  selected,
  params,
}: {
  selected: MapUnit;
  params: URLSearchParams;
}) {
  return (
    <section className="county-detail" aria-labelledby="county-detail-heading">
      <h2 id="county-detail-heading">{selected.name} · Published returns</h2>
      <p>
        {selected.summary.status === "no_results"
          ? "No published returns for this boundary unit."
          : selected.has_geometry
            ? "Exact GEOID match to the 2008 display package."
            : "No matching geometry for this reporting unit."}{" "}
        GEOID: {selected.geoid || "Unavailable"}
      </p>
      <p>
        {selected.summary.leader || "No determined leader"} · Margin{" "}
        {margin(selected.summary)}
        {selected.summary.margin_votes !== null &&
          ` (${number(selected.summary.margin_votes)} votes)`}
      </p>
      <div className="table-scroll">
        <table>
          <caption>Candidate votes and share of reported votes</caption>
          <thead>
            <tr>
              <th>Candidate / source bucket</th>
              <th className="number">Votes</th>
              <th className="number">Share</th>
            </tr>
          </thead>
          <tbody>
            {selected.summary.candidates.map((candidate) => (
              <tr key={candidate.label}>
                <th scope="row">
                  {candidate.candidacy_id ? (
                    <Link
                      to={`/candidates/${candidate.candidacy_id}${filterSearch(params)}&contest_id=${selected.contest_id}`}
                    >
                      {candidate.label}
                    </Link>
                  ) : (
                    candidate.label
                  )}
                </th>
                <td className="number">{number(candidate.votes)}</td>
                <td className="number">{percent(candidate.share)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <details>
        <summary>Reporting unit lineage</summary>
        <dl>
          <dt>Publication batch</dt>
          <dd>{selected.publication_batch_id}</dd>
          {selected.summary.candidates.map((candidate) => (
            <div key={candidate.label}>
              <dt>{candidate.label} · Reference</dt>
              <dd>{candidate.geographic_reference_id}</dd>
              {candidate.reference_vintage_start != null && (
                <>
                  <dt>Statistical reference vintage</dt>
                  <dd>
                    {candidate.reference_vintage_start}–
                    {candidate.reference_vintage_end}; legal boundary dates may
                    differ.
                  </dd>
                </>
              )}
              <dt>Observations</dt>
              <dd>{candidate.observation_ids.join(", ")}</dd>
              <dt>Corrections</dt>
              <dd>{candidate.correction_ids.join(", ") || "None"}</dd>
            </div>
          ))}
        </dl>
      </details>
      {selected.contest_id && (
        <Link to={`/contests/${selected.contest_id}${filterSearch(params)}`}>
          View contest returns
        </Link>
      )}
    </section>
  );
}

export function ResultsTable({
  data,
  units,
  selected,
  onSelect,
}: {
  data: ElectionMap;
  units: MapUnit[];
  selected?: MapUnit;
  onSelect: (unit: MapUnit) => void;
}) {
  return (
    <div
      className="table-scroll"
      tabIndex={0}
      role="region"
      aria-label="Election map results table"
    >
      <table>
        <caption>
          {selected ? selected.name : data.state_code || "United States"} ·{" "}
          {data.reporting_level} reporting · TOTAL mode
        </caption>
        <thead>
          <tr>
            <th scope="col">Geography</th>
            <th scope="col">Candidate votes / shares</th>
            <th scope="col" className="number">
              Reported votes
            </th>
            <th scope="col">Leader / margin</th>
            <th scope="col">Coverage</th>
          </tr>
        </thead>
        <tbody>
          {units.map((unit) => (
            <tr key={unit.id}>
              <th scope="row">
                <button className="text-button" onClick={() => onSelect(unit)}>
                  {unit.name}
                </button>
                <span className="cell-note">
                  GEOID {unit.geoid || "Unavailable"}
                </span>
              </th>
              <td>
                {unit.summary.candidates.map((candidate) => (
                  <span className="candidate-line" key={candidate.label}>
                    {candidate.label}
                    <span>
                      {number(candidate.votes)} · {percent(candidate.share)}
                    </span>
                  </span>
                ))}
              </td>
              <td className="number">
                {unit.summary.total_votes === null
                  ? "Unavailable"
                  : number(unit.summary.total_votes)}
              </td>
              <td>
                {unit.summary.leader ||
                  (unit.summary.status === "tie" ? "Tie" : "Undetermined")}
                <span className="cell-note">
                  {margin(unit.summary)}
                  {unit.summary.margin_votes !== null &&
                    ` · ${number(unit.summary.margin_votes)} votes`}
                </span>
              </td>
              <td>
                {unit.summary.status === "no_results"
                  ? "No published returns"
                  : data.publications.find(
                        (p) => p.batch_id === unit.publication_batch_id,
                      )?.status === "PARTIAL"
                    ? "Partial publication"
                    : "Published"}
                {!unit.has_geometry && (
                  <span className="cell-note">
                    {unit.geometry_match === "missing_reference"
                      ? "No compatible jurisdiction reference"
                      : "No matching geometry"}
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
