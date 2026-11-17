import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MapTooltip, tooltipPosition } from "../geography/MapTooltip";
import { ElectionTooltip } from "../map/ElectionTooltip";
import type { ElectionMap, MapUnit } from "../map/types";
import { publication } from "./fixtures";

describe("map popover positioning", () => {
  it('reuses measured dimensions during pointer movement and measures resized content', () => {
    let resized = () => {};
    const observe = vi.fn(), disconnect = vi.fn(), created = vi.fn();
    vi.stubGlobal('ResizeObserver', class {
      constructor(callback:()=>void) { resized=callback; created(); }
      observe=observe; disconnect=disconnect;
    });
    let width=360;
    const measure=vi.spyOn(HTMLElement.prototype,'getBoundingClientRect').mockImplementation(() =>
      ({ left:0,top:0,width,height:200,right:width,bottom:200,x:0,y:0,toJSON:()=>({}) }));
    const props={ id:'position-test', children:<p>Candidate</p>, onEnter:vi.fn(), onLeave:vi.fn() };
    const view=render(<MapTooltip {...props} anchor={{ x:100,y:100 }} />);
    const tooltip=screen.getByRole('tooltip');
    expect(tooltip).toHaveStyle({ left:'116px', top:'116px' });
    for (let i=0;i<20;i++) view.rerender(<MapTooltip {...props} anchor={{ x:900,y:100+i }} />);
    expect(measure).toHaveBeenCalledOnce();
    expect(created).toHaveBeenCalledOnce();
    expect(tooltip).toHaveAttribute('data-side','left');
    width=400;
    act(() => resized());
    expect(measure).toHaveBeenCalledTimes(2);
    expect(tooltip).toHaveStyle({ left:'484px' });
    view.unmount();
    expect(disconnect).toHaveBeenCalledOnce();
  });
  it.each([
    [100, 100],
    [990, 100],
    [990, 790],
    [3, 790],
  ])("stays beside the anchor and within the viewport at %s,%s", (x, y) => {
    const point = tooltipPosition(
      { x, y },
      { width: 360, height: 330 },
      { width: 1000, height: 800 },
    );
    expect(point.x).toBeGreaterThanOrEqual(8);
    expect(point.x + 360).toBeLessThanOrEqual(992);
    expect(point.y).toBeGreaterThanOrEqual(8);
    expect(point.y + 330).toBeLessThanOrEqual(792);
    if (x === 100) expect(point.x).toBe(116);
    if (x === 990) expect(point.side).toBe("left");
  });
  it("fits a narrow mobile viewport", () => {
    expect(
      tooltipPosition(
        { x: 350, y: 500 },
        { width: 359, height: 600 },
        { width: 375, height: 812 },
      ),
    ).toEqual({ x: 8, y: 8, side: "left" });
  });
});

const data = {
  year: 2008,
  office: "U.S. President",
  stage: "general",
  reporting_level: "county",
  publications: [publication],
} as ElectionMap;
const unit = {
  name: "Albany County",
  state_code: "NY",
  publication_batch_id: publication.batch_id,
  summary: {
    status: "available",
    total_votes: 100,
    leader: "Source candidate",
    margin_votes: 30,
    margin_pp: 30,
    candidates: [
      {
        label: "Source candidate",
        party_labels: ['DEMOCRATIC'],
        kind: "candidate",
        votes: 60,
        share: 60,
        candidacy_id: "one",
      },
      {
        label: "Runner up",
        party_labels: ['REPUBLICAN'],
        kind: "candidate",
        votes: 30,
        share: 30,
        candidacy_id: "two",
      },
      {
        label: "OTHER",
        kind: "aggregate",
        votes: 10,
        share: 10,
        candidacy_id: null,
      },
    ],
  },
} as MapUnit;

describe("reference-style election tooltip", () => {
  it("shows real candidate totals, shares, partial coverage and anonymous categories without inventing portraits or parties", () => {
    render(<ElectionTooltip data={data} unit={unit} name="Fallback" />);
    expect(
      screen.getByRole("heading", { name: "Albany County, NY" }),
    ).toBeVisible();
    expect(screen.getByText(/Leading here:/)).toHaveTextContent('Leading here: Source candidate');
    screen.getAllByRole('link', { name: 'Source candidate' }).forEach(link => expect(link).toHaveAttribute('href', '/candidates/one'));
    expect(screen.getByRole('link', { name: 'Runner up' })).toHaveAttribute('href', '/candidates/two');
    expect(screen.queryByRole('link', { name: 'OTHER' })).not.toBeInTheDocument();
    expect(screen.getByText(/Partial publication/)).toBeVisible();
    expect(screen.getByText("60.00%")).toBeVisible();
    expect(screen.getByText("100 reported votes")).toBeVisible();
    expect(screen.getByText("aggregate vote category")).toBeVisible();
    expect(screen.getByText('DEMOCRATIC').closest('.popover-candidate')).toHaveStyle({ '--candidate-color':'#3276ac' });
    expect(screen.getByText('REPUBLICAN').closest('.popover-candidate')).toHaveStyle({ '--candidate-color':'#bd5548' });
    expect(screen.getByText('aggregate vote category').closest('.popover-candidate')).toHaveStyle({ '--candidate-color':'#7d8584' });
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.queryByText(/elected|certified/i)).not.toBeInTheDocument();
  });
  it("keeps missing returns distinct from stored zero votes", () => {
    const view = render(<ElectionTooltip data={data} name="Missing County" />);
    expect(screen.getAllByText("No published returns").length).toBeGreaterThan(
      0,
    );
    expect(screen.getByText("Votes unavailable")).toBeVisible();
    view.rerender(
      <ElectionTooltip
        data={data}
        unit={{
          ...unit,
          summary: {
            ...unit.summary,
            status: "zero_total",
            total_votes: 0,
            leader: null,
            margin_pp: null,
            candidates: [],
          },
        }}
        name="Zero"
      />,
    );
    expect(screen.getByText("0 reported votes")).toBeVisible();
    expect(screen.getByText("Leader undetermined")).toBeVisible();
  });
});
