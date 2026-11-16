import { Notice } from "../components";
import { MapSources } from "./MapSources";
import type { ElectionMap } from "./types";
import { margin, number, percent } from "./types";
import { candidateColor, indeterminateColor } from "./electionColors";
import { useElectionMap } from "./useElectionMap";

/** Independent published state authority; never a sum of county returns. */
export function StateResultsSummary({ selection }: { selection: ElectionMap }) {
  const query = new URLSearchParams({
    year: String(selection.year),
    office: selection.office,
    stage: selection.stage,
    state_code: selection.state_code!,
    reporting_level: "state",
  });
  const { data, error, retry } = useElectionMap(query.toString(), true);
  const unit =
    data?.reporting_level === "state" &&
    data.state_code === selection.state_code
      ? data.units.find((item) => item.summary.status !== "no_results")
      : undefined;
  const title = `${unit?.name || selection.state_code} statewide summary`;
  return (
    <section className="state-summary" aria-labelledby="state-summary-heading">
      <h2 className="state-summary-heading" id="state-summary-heading">{title}</h2>
      {error ? (
        <Notice title="State summary could not be loaded" error>
          <p>{error}</p>
          <button onClick={retry}>Retry state summary</button>
        </Notice>
      ) : !data ? (
        <p role="status">Loading statewide results…</p>
      ) : !unit ? (
        <p role="status">
          Published statewide results are unavailable for this selection. County
          returns remain separate; they are not used as a substitute.
        </p>
      ) : (
        <>
          <dl className="state-summary-metrics">
            <div>
              <dt>Reported votes</dt>
              <dd>
                {unit.summary.total_votes === null
                  ? "Unavailable"
                  : number(unit.summary.total_votes)}
              </dd>
            </div>
            <div>
              <dt>Margin</dt>
              <dd>
                {margin(unit.summary)}
                {unit.summary.margin_votes !== null && (
                  <small>{number(unit.summary.margin_votes)} votes</small>
                )}
              </dd>
            </div>
          </dl>
          <ul
            className="state-summary-candidates"
            aria-label="State candidate results"
          >
            {unit.summary.candidates.map((candidate, index) => {
              const named = ["candidate", "source_candidate"].includes(
                candidate.kind,
              );
              const color = named
                ? candidateColor(candidate.label)
                : indeterminateColor;
              return (
                <li key={`${candidate.label}:${index}`}>
                  <div className="state-summary-candidate-name">
                    <i aria-hidden="true" style={{ background: color }} />
                    {candidate.label}
                    {candidate.label === unit.summary.leader && <span className="state-summary-leader">Leading</span>}
                  </div>
                  <div className="state-summary-candidate-total">
                    {number(candidate.votes)}{" "}
                    <span>votes · {percent(candidate.share)}</span>
                  </div>
                  {candidate.share !== null && (
                    <div className="state-summary-share" aria-hidden="true">
                      <span
                        style={{
                          width: `${candidate.share}%`,
                          background: color,
                        }}
                      />
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
          <div className="state-summary-sources">
            <p className="field-help">
              Published statewide totals are shown independently of county
              returns. State and county publications may differ and are not added
              together.
            </p>
            <details><summary>Statewide sources</summary><MapSources publications={data.publications} /></details>
          </div>
        </>
      )}
    </section>
  );
}
