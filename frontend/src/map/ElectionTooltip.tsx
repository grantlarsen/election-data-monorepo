import type { CSSProperties, ReactNode } from "react";
import type { ElectionMap, MapUnit } from "./types";
import { number, percent, margin, leaderCandidate } from "./types";
import { CandidateLink } from '../CandidateLink';
import { mapCandidateColor, resultColor, indeterminateColor } from "./electionColors";
import { humanize } from "../filters";
import { popoverCandidates } from './popoverCandidates';
import { CandidateAvatar } from '../CandidateAvatar';
import { cachedPortrait } from '../candidateMedia';

/** Reference-card styling over published data; no inferred parties or elected status. */
export function ElectionTooltip({
  data,
  unit,
  name,
  heading,
  contextLabel,
  sourceLabel,
  candidateSearch,
  footerNote,
  headerLayout = 'stacked',
  showLeader = true,
}: {
  data: Pick<ElectionMap, 'reporting_level' | 'year' | 'office' | 'stage' | 'publications'>;
  unit?: Pick<MapUnit, 'summary' | 'publication_batch_id' | 'name' | 'state_code' | 'contest_id'>;
  name: string;
  heading?: ReactNode;
  contextLabel?: string;
  sourceLabel?: string;
  candidateSearch?: URLSearchParams;
  footerNote?: ReactNode;
  headerLayout?: 'stacked' | 'split';
  showLeader?: boolean;
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
      <header className={`popover-head${headerLayout === 'split' ? ' popover-head-split' : ''}`}>
        <div className="popover-eyebrow">
          {humanize(data.reporting_level)} / {data.year} / {data.office}
        </div>
        <h3>
          {heading || unit?.name || name}
          {!heading && data.reporting_level !== "state" && unit?.state_code
            ? `, ${unit.state_code}`
            : ""}
        </h3>
        <p>
          {humanize(data.stage)} election · {contextLabel || context}
        </p>
      </header>
      {showLeader && <div className="popover-leader">
        {summary?.leader ? (
          <>
            <span aria-hidden="true">●</span> Leading here: <CandidateLink candidacyId={leaderCandidate(summary)?.candidacy_id} contestId={unit?.contest_id} search={candidateSearch}>{summary.leader}</CandidateLink>
          </>
        ) : summary?.status === "tie" ? (
          "Tied reported votes"
        ) : summary?.status === "no_results" || !summary ? (
          "No published returns"
        ) : (
          "Leader undetermined"
        )}
      </div>}
      <div className="popover-candidates">
        {popoverCandidates(summary).map((candidate, index) => {
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
          const leading = named && candidate.label === summary?.leader;
          return (
            <div
              className={`popover-candidate${leading ? " is-leading" : ""}`}
              key={`${candidate.candidacy_id}:${candidate.label}:${index}`}
              style={{ "--candidate-color": color } as CSSProperties}
            >
              <CandidateAvatar className="popover-avatar" portrait={named ? cachedPortrait(candidate.portrait) : undefined}
                name={candidate.label} fallback={initials} decorative />
              <div className="popover-candidate-body">
                <div className="popover-name"><CandidateLink candidacyId={candidate.candidacy_id} contestId={unit?.contest_id} search={candidateSearch}>{candidate.label}</CandidateLink>
                  {candidate.incumbent && <span className="incumbent-marker" title="Incumbent U.S. senator entering this election">Incumbent</span>}
                  {candidate.result_badge && <span className="incumbent-marker winner-marker" title={candidate.result_badge === 'Winner' ? 'Winner per source certification' : 'Projected by Call the Map; not certified'}>{candidate.result_badge}</span>}</div>
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
            {sourceLabel || publication?.source.name || "No published source for this unit"}
          </span>
        </div>
        <div className="popover-margin">
          Margin<strong>{summary ? margin(summary) : "Unavailable"}</strong>
        </div>
      </footer>
      {footerNote && <div className="popover-source-note">{footerNote}</div>}
    </article>
  );
}
