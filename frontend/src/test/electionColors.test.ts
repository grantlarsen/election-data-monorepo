import { describe, it, expect } from "vitest";
import { partyGroup, partyPalette, resultColor, missingColor } from "../map/electionColors";
import type { Summary } from "../map/types";

describe("district source party colors", () => {
  it("uses fusion affiliations without guessing a major party from names", () => {
    expect(partyGroup(["WORKING FAMILIES", "DEMOCRATIC"])).toBe("Democratic");
    expect(partyGroup(["CONSERVATIVE", "REPUBLICAN"])).toBe("Republican");
    expect(partyGroup(["DEMOCRATIC-FARMER-LABOR"])).toBe("Democratic");
    expect(partyGroup(["DEMOCRATIC", "REPUBLICAN"])).toBe("Multiple major parties");
    expect(partyGroup([])).toBe("Other / independent");
  });
  it("keeps candidate-label colors separate from House party colors and missing votes", () => {
    const summary = {status:"available", leader:"Example", candidates:[{label:"Example", party_labels:["REPUBLICAN"]}]} as Summary;
    expect(resultColor(summary, true)).toBe(partyPalette.Republican);
    expect(resultColor({...summary, status:"no_results"}, true)).toBe(missingColor);
  });
});
