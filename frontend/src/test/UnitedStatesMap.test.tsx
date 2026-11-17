import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { mockAnimationFrames } from './animationFrames';
import { geoArea, geoContains } from "d3-geo";
import greatLakes from "../geography/data/great-lakes.json";
import type { FeatureCollection, Polygon, MultiPolygon } from "geojson";
import { UnitedStatesMap } from "../geography/UnitedStatesMap";
import {
  MAP_HEIGHT,
  MAP_WIDTH,
  matchJurisdictions,
  projectionFeature,
  projectUnitedStates,
} from "../geography/unitedStates";
import type {
  JurisdictionCollection,
  JurisdictionFeature,
} from "../geography/unitedStates";

function rectangle(
  geoid: string,
  state: string,
  west: number,
  south: number,
  east: number,
  north: number,
): JurisdictionFeature {
  return {
    type: "Feature",
    id: geoid,
    properties: {
      geoid,
      state_code: state,
      name: state,
      jurisdiction_id: `canonical-${geoid}`,
    },
    geometry: {
      type: "Polygon",
      coordinates: [
        [
          [west, south],
          [east, south],
          [east, north],
          [west, north],
          [west, south],
        ],
      ],
    },
  };
}
const features: JurisdictionCollection = {
  type: "FeatureCollection",
  features: [
    rectangle("06", "CA", -123, 34, -117, 40),
    rectangle("02", "AK", -160, 59, -145, 68),
    rectangle("15", "HI", -158, 19, -155, 22),
  ],
};
function rows() {
  return features.features.map((feature) => ({
    id: feature.properties.geoid,
    geoid: feature.properties.geoid,
    state_code: feature.properties.state_code,
    jurisdiction_id: feature.properties.jurisdiction_id!,
    value: feature.properties.state_code,
  }));
}

describe("generic United States mapping", () => {
  let frames: ReturnType<typeof mockAnimationFrames>;
  beforeEach(() => { frames = mockAnimationFrames(); });
  function wheel(target: Element, options: object) {
    const result = fireEvent.wheel(target, options);
    frames.flush();
    return result;
  }
  it('reuses labels, shapes and tooltip content while coalescing pointer motion', () => {
    const featureLabel = vi.fn(feature => [feature.properties.state_code]);
    const fill = vi.fn(() => '#abc');
    const describe = vi.fn(row => row?.value || '');
    const tooltip = vi.fn(row => <span>{row?.value}</span>);
    render(<UnitedStatesMap features={features} data={matchJurisdictions(features, rows())}
      title="Cached map" fill={fill} describe={describe} tooltip={tooltip}
      onSelect={vi.fn()} featureLabel={featureLabel} attribution="Source" />);
    expect(featureLabel).toHaveBeenCalledTimes(3);
    const path = screen.getByRole('button', { name: 'CA' });
    const bounds = vi.spyOn(path, 'getBoundingClientRect');
    fireEvent.mouseEnter(path, { clientX: 220, clientY: 180 });
    expect(bounds).not.toHaveBeenCalled();
    [featureLabel, fill, describe, tooltip].forEach(fn => fn.mockClear());
    for (let i=0;i<20;i++) fireEvent.mouseMove(path, { clientX:240+i, clientY:200+i });
    expect(frames.pending.size).toBe(1);
    expect(screen.getByRole('tooltip')).toHaveStyle({ left:'236px', top:'196px' });
    frames.flush();
    expect(screen.getByRole('tooltip')).toHaveStyle({ left:'275px', top:'235px' });
    [featureLabel, fill, describe, tooltip].forEach(fn => expect(fn).not.toHaveBeenCalled());
    fireEvent.click(screen.getByRole('button', { name:'Zoom in' }));
    expect(featureLabel).not.toHaveBeenCalled();
    fill.mockClear(); describe.mockClear();
    fireEvent.keyDown(screen.getByRole('group', { name:'Cached map' }), { key:'ArrowRight' });
    expect(fill).not.toHaveBeenCalled();
    expect(describe).not.toHaveBeenCalled();
  });

  it('accumulates wheel bursts and applies discrete controls to the latest queued camera', () => {
    render(<UnitedStatesMap features={features} data={matchJurisdictions(features, rows())}
      title="Queued camera" fill={() => '#abc'} describe={row => row?.value || ''} tooltip={() => ''}
      onSelect={vi.fn()} attribution="Source" />);
    const map = screen.getByRole('group', { name:'Queued camera' });
    vi.spyOn(map, 'getBoundingClientRect').mockReturnValue({ left:0,top:0,width:960,height:600,right:960,bottom:600,x:0,y:0,toJSON:()=>({}) });
    for (let i=0;i<3;i++) fireEvent.wheel(map, { deltaY:-60, clientX:720, clientY:420 });
    expect(map).toHaveAttribute('viewBox','0 0 960 600');
    expect(frames.pending.size).toBe(1);
    frames.flush();
    const view = map.getAttribute('viewBox')!.split(' ').map(Number);
    expect(view[2]).toBeCloseTo(960 / Math.exp(.36));
    expect(view[0] + .75*view[2]).toBeCloseTo(720);
    fireEvent.wheel(map, { deltaY:-60, clientX:480,clientY:300 });
    fireEvent.click(screen.getByRole('button', { name:'Zoom in' }));
    expect(frames.pending.size).toBe(0);
    expect(map.getAttribute('viewBox')!.split(' ').map(Number)[2]).toBeCloseTo(960 / (Math.exp(.48)*1.5));
    fireEvent.wheel(map, { deltaY:-60,clientX:480,clientY:300 });
    fireEvent.click(screen.getByRole('button', { name:'Reset zoom' }));
    frames.flush();
    expect(map).toHaveAttribute('viewBox','0 0 960 600');
  });

  it('cancels queued motion when boundaries change or the map unmounts', () => {
    const props = { features, data:matchJurisdictions(features, rows()), title:'Changing map',
      fill:()=> '#abc', describe:()=> '', tooltip:()=> '', onSelect:vi.fn(), attribution:'Source' };
    const view = render(<UnitedStatesMap {...props} />);
    const map = screen.getByRole('group', { name:'Changing map' });
    vi.spyOn(map, 'getBoundingClientRect').mockReturnValue({ left:0,top:0,width:960,height:600,right:960,bottom:600,x:0,y:0,toJSON:()=>({}) });
    fireEvent.wheel(map, { deltaY:-120,clientX:400,clientY:300 });
    expect(frames.pending.size).toBe(1);
    view.rerender(<UnitedStatesMap {...props} features={{ ...features }} />);
    expect(frames.pending.size).toBe(0);
    frames.flush();
    expect(map).toHaveAttribute('viewBox','0 0 960 600');
    fireEvent.wheel(map, { deltaY:-120,clientX:400,clientY:300 });
    view.unmount();
    expect(frames.pending.size).toBe(0);
  });

  it('keeps the final drag position and suppresses its click without suppressing the next selection', () => {
    vi.stubGlobal('PointerEvent', class extends MouseEvent {
      pointerId: number; isPrimary: boolean;
      constructor(type:string, options:PointerEventInit = {}) {
        super(type, options); this.pointerId=options.pointerId || 0; this.isPrimary=options.isPrimary !== false;
      }
    });
    const select = vi.fn();
    render(<UnitedStatesMap features={features} data={matchJurisdictions(features, rows())}
      title="Drag map" fill={() => '#abc'} describe={row => row?.value || ''} tooltip={() => ''}
      onSelect={select} attribution="Source" />);
    const map = screen.getByRole('group', { name:'Drag map' });
    vi.spyOn(map, 'getBoundingClientRect').mockReturnValue({ left:0,top:0,width:960,height:600,right:960,bottom:600,x:0,y:0,toJSON:()=>({}) });
    Object.assign(map, { setPointerCapture:vi.fn(), hasPointerCapture:()=>true, releasePointerCapture:vi.fn() });
    fireEvent.click(screen.getByRole('button', { name:'Zoom in' }));
    const before=map.getAttribute('viewBox')!.split(' ').map(Number);
    fireEvent.pointerDown(map, { pointerId:7,clientX:480,clientY:300,button:0 });
    for (let i=1;i<=30;i++) fireEvent.pointerMove(map, { pointerId:7,clientX:480+i,clientY:300 });
    expect(frames.pending.size).toBe(1);
    fireEvent.pointerUp(map, { pointerId:7 });
    frames.flush();
    const after=map.getAttribute('viewBox')!.split(' ').map(Number);
    expect(after[0]).toBeCloseTo(before[0]-20);
    expect(map).not.toHaveClass('is-panning');
    const path=screen.getByRole('button', { name:'CA' });
    fireEvent.click(path);
    expect(select).not.toHaveBeenCalled();
    fireEvent.pointerDown(map, { pointerId:8,clientX:450,clientY:300,button:0 });
    fireEvent.pointerUp(map, { pointerId:8 });
    fireEvent.click(path);
    expect(select).toHaveBeenCalledOnce();
  });
  it('allows keyboard access to tooltip candidate links and returns focus to the map with Escape', async () => {
    render(<UnitedStatesMap features={features} data={matchJurisdictions(features, rows())}
      title="Linked map" fill={() => '#abc'} describe={row => row?.value || ''}
      tooltip={() => <a href="/candidates/example">Candidate profile</a>}
      onSelect={vi.fn()} attribution="Source" />);
    const path = screen.getByRole('button', { name: 'CA' });
    const user = userEvent.setup();
    act(() => path.focus());
    await user.tab();
    expect(screen.getByRole('link', { name: 'Candidate profile' })).toHaveFocus();
    await user.keyboard('{Escape}');
    expect(path).toHaveFocus();
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });
  it('zooms toward the wheel pointer, normalizes scroll units, and contains scrolling at zoom limits', () => {
    render(<UnitedStatesMap features={features} data={matchJurisdictions(features, rows())}
      title="Wheel map" fill={() => '#abc'} describe={row => row?.value || ''} tooltip={() => ''}
      onSelect={vi.fn()} focusSelection={false} attribution="Source" />);
    const map = screen.getByRole('group', { name: 'Wheel map' });
    vi.spyOn(map, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 0, width: 960, height: 600, right: 960, bottom: 600, x: 0, y: 0, toJSON: () => ({}) });
    expect(wheel(map, { deltaY: -120, clientX: 720, clientY: 420, cancelable: true })).toBe(false);
    const view = map.getAttribute('viewBox')!.split(' ').map(Number);
    expect(view[2]).toBeLessThan(960);
    expect(view[0] + .75 * view[2]).toBeCloseTo(720);
    expect(view[1] + .7 * view[3]).toBeCloseTo(420);
    fireEvent.click(screen.getByRole('button', { name: 'Reset zoom' }));
    wheel(map, { deltaY: -7.5, deltaMode: 1, clientX: 720, clientY: 420 });
    expect(map.getAttribute('viewBox')!.split(' ').map(Number)[2]).toBeCloseTo(view[2]);
    const before = map.getAttribute('viewBox');
    expect(wheel(map, { deltaY: -120, ctrlKey: true, cancelable: true })).toBe(true);
    expect(map).toHaveAttribute('viewBox', before!);
    for (let i = 0; i < 20; i++) wheel(map, { deltaY: -240, clientX: 480, clientY: 300 });
    expect(map.getAttribute('viewBox')!.split(' ').map(Number)[2]).toBe(240);
    expect(wheel(map, { deltaY: -240, cancelable: true })).toBe(false);
    for (let i = 0; i < 20; i++) wheel(map, { deltaY: 240, clientX: 480, clientY: 300 });
    expect(map).toHaveAttribute('viewBox', '0 0 960 600');
  });
  it('pans a zoomed map with arrow keys, preserves its center on zoom-in, and resets the viewport', () => {
    const { rerender } = render(<UnitedStatesMap features={features} data={matchJurisdictions(features, rows())}
      title="Pan map" fill={() => '#abc'} describe={row => row?.value || ''} tooltip={() => ''}
      onSelect={vi.fn()} selectedId="06" focusSelection={false} attribution="Source" />);
    const map = screen.getByRole('group', { name: 'Pan map' });
    fireEvent.click(screen.getByRole('button', { name: 'Zoom in' }));
    expect(map).toHaveClass('is-pannable');
    const before = map.getAttribute('viewBox')!.split(' ').map(Number);
    fireEvent.keyDown(map, { key: 'ArrowRight' });
    const after = map.getAttribute('viewBox')!.split(' ').map(Number);
    expect(after[0]).toBeGreaterThan(before[0]);
    expect(after[2]).toBe(before[2]);
    const centerX = after[0] + after[2] / 2;
    fireEvent.click(screen.getByRole('button', { name: 'Zoom in' }));
    const zoomed = map.getAttribute('viewBox')!.split(' ').map(Number);
    expect(zoomed[0] + zoomed[2] / 2).toBeCloseTo(centerX);
    fireEvent.click(screen.getByRole('button', { name: 'Reset zoom' }));
    expect(map).toHaveAttribute('viewBox', `0 0 ${MAP_WIDTH} ${MAP_HEIGHT}`);
    expect(map).not.toHaveClass('is-pannable');
    fireEvent.click(screen.getByRole('button', { name: 'Zoom in' }));
    rerender(<UnitedStatesMap features={{ ...features }} data={matchJurisdictions(features, rows())}
      title="Pan map" fill={() => '#abc'} describe={row => row?.value || ''} tooltip={() => ''}
      onSelect={vi.fn()} focusSelection={false} attribution="Source" />);
    expect(map).toHaveAttribute('viewBox', `0 0 ${MAP_WIDTH} ${MAP_HEIGHT}`);
  });
  it("keeps geographic context in view while highlighting a selection and making neighbors passive", () => {
    const onSelect = vi.fn();
    render(<UnitedStatesMap features={features} data={matchJurisdictions(features, rows())}
      title="Context map" fill={() => '#dce4e1'} describe={(datum) => datum?.value || 'Context'}
      tooltip={() => 'Context'} onSelect={onSelect} selectedId="06" focusSelection={false}
      isInteractive={datum => datum?.id === '06'} attribution="Test source" />);
    expect(screen.getByRole('group', { name: 'Context map' })).toHaveAttribute('viewBox', `0 0 ${MAP_WIDTH} ${MAP_HEIGHT}`);
    expect(screen.getByRole('button', { name: 'CA' })).toHaveAttribute('aria-pressed', 'true');
    const neighbor = screen.getByRole('img', { name: 'AK' });
    expect(neighbor).not.toHaveAttribute('tabindex');
    fireEvent.click(neighbor);
    expect(onSelect).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Zoom in' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'CA' }));
    expect(onSelect).toHaveBeenCalledOnce();
  });
  it("masks Great Lakes water while retaining both Michigan peninsulas and Wisconsin/Minnesota land", () => {
    const water = greatLakes as FeatureCollection<
      Polygon | MultiPolygon,
      { name: string }
    >;
    const contains = (point: [number, number]) =>
      water.features.some((lake) =>
        geoContains(projectionFeature(lake), point),
      );
    expect(contains([-86.5, 44])).toBe(true); // Lake Michigan, inside legal state waters.
    expect(contains([-90, 47.5])).toBe(true); // Lake Superior.
    for (const land of [
      [-84.5, 43.5],
      [-87, 46.4],
      [-89.4, 43.07],
      [-94.2, 46.35],
    ] as [number, number][])
      expect(contains(land)).toBe(false);
    const onSelect = vi.fn();
    render(
      <UnitedStatesMap
        features={features}
        data={matchJurisdictions(features, rows())}
        title="Water regression"
        fill={() => "#123456"}
        describe={() => "Land"}
        tooltip={() => "Land"}
        onSelect={onSelect}
        attribution="Physical water provenance"
        water={water}
      />,
    );
    const lake = screen.getByRole("img", { name: "Lake Michigan" });
    expect(lake).toHaveAttribute("pointer-events", "all");
    fireEvent.click(lake);
    expect(onSelect).not.toHaveBeenCalled();
    expect(lake.closest("svg")?.lastElementChild).toHaveClass("map-water");
  });
  it("uses Albers USA to place Alaska and Hawaii below the mainland with finite paths", () => {
    const projected = projectUnitedStates(features);
    expect(projected).toHaveLength(3);
    for (const item of projected) {
      expect(item.path).toMatch(/^M/);
      expect(item.path).not.toMatch(/NaN|Infinity/);
      const [[left, top], [right, bottom]] = item.bounds;
      expect(left).toBeGreaterThanOrEqual(23);
      expect(right).toBeLessThanOrEqual(MAP_WIDTH - 23);
      expect(top).toBeGreaterThanOrEqual(23);
      expect(bottom).toBeLessThanOrEqual(MAP_HEIGHT - 23);
    }
    expect(projected[1].bounds[0][1]).toBeGreaterThan(
      projected[0].bounds[0][1],
    );
    expect(projected[2].bounds[0][1]).toBeGreaterThan(
      projected[0].bounds[0][1],
    );
  });

  it("normalizes RFC polygon winding for D3 without modifying the boundary source", () => {
    const before = JSON.stringify(features);
    expect(geoArea(features.features[0])).toBeGreaterThan(2 * Math.PI);
    expect(geoArea(projectionFeature(features.features[0]))).toBeLessThan(
      2 * Math.PI,
    );
    expect(JSON.stringify(features)).toBe(before);
  });

  it("matches reordered data by exact GEOID and canonical identity, never position or name", () => {
    const data = rows().reverse();
    expect(matchJurisdictions(features, data).get("06")?.value).toBe("CA");
    expect(matchJurisdictions(features, data.slice(1)).has("15")).toBe(false);
    expect(() => matchJurisdictions(features, [...data, data[0]])).toThrow(
      /same GEOID/,
    );
    expect(() =>
      matchJurisdictions(features, [{ ...data[0], state_code: "CA" }]),
    ).toThrow(/do not agree/);
    expect(() =>
      matchJurisdictions(features, [
        { ...data[0], jurisdiction_id: "wrong-canonical-id" },
      ]),
    ).toThrow(/do not agree/);
    const unverified = {
      ...features,
      features: [
        {
          ...features.features[2],
          properties: {
            ...features.features[2].properties,
            jurisdiction_id: null,
          },
        },
      ],
    };
    expect(() => matchJurisdictions(unverified, [data[0]])).toThrow(
      /do not agree/,
    );
  });

  it("allows keyboard and pointer selection using caller-supplied data and tooltips", async () => {
    const onSelect = vi.fn();
    const data = matchJurisdictions(features, rows());
    render(
      <UnitedStatesMap
        features={features}
        data={data}
        title="Generic geographic data"
        fill={(row) => (row?.value === "CA" ? "#123456" : "#abcdef")}
        describe={(row) => `Select ${row?.value}`}
        tooltip={(row) => `Data: ${row?.value}`}
        onSelect={onSelect}
        attribution="Source archive"
      />,
    );
    const california = screen.getByRole("button", { name: "Select CA" });
    expect(california).toHaveAttribute("fill", "#123456");
    fireEvent.focus(california);
    expect(screen.getByRole("tooltip")).toHaveTextContent("Data: CA");
    fireEvent.keyDown(california, { key: "Enter" });
    expect(onSelect).toHaveBeenLastCalledWith(
      data.get("06"),
      expect.objectContaining({ id: "06" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Select AK" }));
    expect(onSelect).toHaveBeenLastCalledWith(
      data.get("02"),
      expect.objectContaining({ id: "02" }),
    );
  });

  it("anchors a hover tooltip near the pointer, portals it outside the map, and dismisses it with Escape", () => {
    render(
      <UnitedStatesMap
        features={features}
        data={matchJurisdictions(features, rows())}
        title="Anchor regression"
        fill={() => "#123456"}
        describe={(row) => `Select ${row?.value}`}
        tooltip={(row) => `Data: ${row?.value}`}
        onSelect={vi.fn()}
        attribution="Source"
      />,
    );
    const california = screen.getByRole("button", { name: "Select CA" });
    fireEvent.mouseEnter(california, { clientX: 220, clientY: 180 });
    const tooltip = screen.getByRole("tooltip");
    expect(tooltip.parentElement).toBe(document.body);
    expect(tooltip).toHaveStyle({ left: "236px", top: "196px" });
    fireEvent.mouseMove(california, { clientX: 240, clientY: 200 });
    frames.flush();
    expect(tooltip).toHaveStyle({ left: "256px", top: "216px" });
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    fireEvent.mouseMove(california, { clientX: 245, clientY: 205 });
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });
});
