import { describe, it, expect } from "vitest";
import { partyGroup, partyPalette, mapCandidateColor, resultColor, missingColor, tieColor, indeterminateColor } from "../map/electionColors";
import type { Summary } from "../map/types";

describe("shared source party colors", () => {
  it("uses fusion affiliations without guessing a major party from names", () => {
    expect(partyGroup(["WORKING FAMILIES", "DEMOCRATIC"])).toBe("Democratic");
    expect(partyGroup(["CONSERVATIVE", "REPUBLICAN"])).toBe("Republican");
    expect(partyGroup(["DEMOCRATIC-FARMER-LABOR"])).toBe("Democratic");
    expect(partyGroup(["DEMOCRATIC", "REPUBLICAN"])).toBe("Multiple major parties");
    expect(partyGroup([' democratic ', 'Working Families'])).toBe('Democratic');
    expect(partyGroup(['LIBERTARIAN'])).toBe('Other / independent');
    expect(partyGroup([])).toBe('Party unavailable');
  });
  it.each(['candidate', 'source_candidate'])('colors %s returns by party regardless of candidate name', kind => {
    for (const label of ['JOE BIDEN', 'JOSEPH R BIDEN JR', 'Unrelated name']) {
      const candidate = { kind, label, party_labels: ['DEMOCRATIC'] };
      expect(mapCandidateColor(candidate)).toBe('#3276ac');
      candidate.party_labels = ['REPUBLICAN'];
      expect(mapCandidateColor(candidate)).toBe('#bd5548');
    }
  });
  it('keeps missing, unknown, aggregate, tied and mixed affiliations distinct', () => {
    const summary = {status:'available', leader:'Example', candidates:[{kind:'candidate',label:'Example',party_labels:['REPUBLICAN']}]} as Summary;
    expect(resultColor(summary)).toBe(partyPalette.Republican);
    expect(resultColor({...summary, status:'no_results'})).toBe(missingColor);
    expect(resultColor({...summary, status:'tie'})).toBe(tieColor);
    expect(resultColor({...summary, leader:null})).toBe(indeterminateColor);
    expect(mapCandidateColor({ kind:'candidate' })).toBe(partyPalette['Party unavailable']);
    expect(mapCandidateColor({ kind:'aggregate', party_labels:['DEMOCRATIC'] })).toBe(indeterminateColor);
    expect(mapCandidateColor({ kind:'candidate', party_labels:['DEMOCRATIC','REPUBLICAN'] })).toBe(partyPalette['Multiple major parties']);
  });
});
