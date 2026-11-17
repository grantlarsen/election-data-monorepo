import { Link } from "react-router";
import type { ElectionMap, MapUnit } from "./types";
import { margin, number, percent, leaderCandidate } from "./types";
import { CandidateLink } from '../CandidateLink';
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
      {selected.summary.status !== "no_results" && <p>
        <CandidateLink candidacyId={leaderCandidate(selected.summary)?.candidacy_id}>{selected.summary.leader || "No determined leader"}</CandidateLink> · Margin{" "}
        {margin(selected.summary)}
        {selected.summary.margin_votes !== null &&
          ` (${number(selected.summary.margin_votes)} votes)`}
      </p>}
      {selected.summary.candidates.length > 0 ? <div className="table-scroll">
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
                  <CandidateLink candidacyId={candidate.candidacy_id}>{candidate.label}</CandidateLink>
                </th>
                <td className="number">{number(candidate.votes)}</td>
                <td className="number">{percent(candidate.share)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div> : <p>No published returns for this area.</p>}
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
          Election results
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
              </th>
              <td>
                {unit.summary.candidates.map((candidate) => (
                  <span className="candidate-line" key={candidate.label}>
                    <CandidateLink candidacyId={candidate.candidacy_id}>{candidate.label}</CandidateLink>
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
                <CandidateLink candidacyId={leaderCandidate(unit.summary)?.candidacy_id}>{unit.summary.leader ||
                  (unit.summary.status === "tie" ? "Tie" : "Undetermined")}</CandidateLink>
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
