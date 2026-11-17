import { act } from '@testing-library/react';
import { vi } from 'vitest';

/** A deterministic frame boundary for input bursts, reset and unmount checks. */
export function mockAnimationFrames() {
  let id = 0;
  const pending = new Map<number, FrameRequestCallback>();
  vi.stubGlobal('requestAnimationFrame', vi.fn((callback: FrameRequestCallback) => {
    pending.set(++id, callback);
    return id;
  }));
  vi.stubGlobal('cancelAnimationFrame', vi.fn((key: number) => pending.delete(key)));
  return {
    pending,
    flush() {
      const callbacks = [...pending.values()];
      pending.clear();
      act(() => callbacks.forEach(callback => callback(performance.now())));
    },
  };
}
