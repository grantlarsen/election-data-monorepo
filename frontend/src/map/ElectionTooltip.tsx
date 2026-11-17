import type { CSSProperties } from "react";
import type { ElectionMap, MapUnit } from "./types";
import { number, percent, margin, leaderCandidate } from "./types";
import { CandidateLink } from '../CandidateLink';
import { mapCandidateColor, resultColor, indeterminateColor } from "./electionColors";
import { humanize } from "../filters";

/** Reference-card styling over published data; no inferred parties or elected status. */
export function ElectionTooltip({
  data,
  unit,
  name,
}: {
  data: ElectionMap;
  unit?: MapUnit;
  name: string;
}) {
  const summary = unit?.summary;
  const publication = data.publications.find(
    (item) => item.batch_id === unit?.publication_batch_id,
  );
  const leaderColor = resultColor(summary);
  const context =
    publication?.status === "PARTIAL"
      ? "Partial publication"
      : publication
        ? "Published results"
        : "No published returns";
  return (
    <article
      className="election-popover"
      style={{ "--leader-color": leaderColor } as CSSProperties}
    >
      <header className="popover-head">
        <div className="popover-eyebrow">
          {humanize(data.reporting_level)} / {data.year} / {data.office}
        </div>
        <h3>
          {unit?.name || name}
          {data.reporting_level !== "state" && unit?.state_code
            ? `, ${unit.state_code}`
            : ""}
        </h3>
        <p>
          {humanize(data.stage)} election · {context}
        </p>
      </header>
      <div className="popover-leader">
        {summary?.leader ? (
          <>
            <span aria-hidden="true">●</span> Leading here: <CandidateLink candidacyId={leaderCandidate(summary)?.candidacy_id} contestId={unit?.contest_id}>{summary.leader}</CandidateLink>
          </>
        ) : summary?.status === "tie" ? (
          "Tied reported votes"
        ) : summary?.status === "no_results" || !summary ? (
          "No published returns"
        ) : (
          "Leader undetermined"
        )}
      </div>
      <div className="popover-candidates">
        {summary?.candidates.map((candidate, index) => {
          const named = ["candidate", "source_candidate"].includes(
            candidate.kind,
          );
          const color = named
            ? mapCandidateColor(candidate)
            : indeterminateColor;
          const initials = named
            ? candidate.label
                .split(/\s+/)
                .filter(Boolean)
                .slice(0, 2)
                .map((part) => part[0])
                .join("")
            : "∑";
          const leading = candidate.label === summary.leader;
          return (
            <div
              className={`popover-candidate${leading ? " is-leading" : ""}`}
              key={`${candidate.candidacy_id}:${candidate.label}:${index}`}
              style={{ "--candidate-color": color } as CSSProperties}
            >
              <div className="popover-avatar" aria-hidden="true">
                {initials}
              </div>
              <div className="popover-candidate-body">
                <div className="popover-name"><CandidateLink candidacyId={candidate.candidacy_id} contestId={unit?.contest_id}>{candidate.label}</CandidateLink></div>
                {named && <div className="popover-extra">{candidate.party_labels?.join(" / ") || "Party unavailable"}</div>}
                {!named && (
                  <div className="popover-extra">
                    {humanize(candidate.kind)} vote category
                  </div>
                )}
                {candidate.share !== null && (
                  <div className="popover-share" aria-hidden="true">
                    <span style={{ width: `${candidate.share}%` }} />
                  </div>
                )}
              </div>
              <div className="popover-numbers">
                <div>{number(candidate.votes)}</div>
                <div className="popover-percent">
                  {percent(candidate.share)}
                </div>
              </div>
            </div>
          );
        })}
      </div>
      <footer className="popover-foot">
        <div>
          <strong>
            {summary?.total_votes == null
              ? "Votes unavailable"
              : `${number(summary.total_votes)} reported votes`}
          </strong>
          <span>
            {publication?.source.name || "No published source for this unit"}
          </span>
        </div>
        <div className="popover-margin">
          Margin<strong>{summary ? margin(summary) : "Unavailable"}</strong>
        </div>
      </footer>
    </article>
  );
}
