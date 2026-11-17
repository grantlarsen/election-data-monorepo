import { useCallback, useEffect, useRef, useState } from 'react';
import type { SetStateAction } from 'react';

/** Keep the latest input immediately; commit at most once per display frame.
 * Discrete controls/reset can commit synchronously and cancel queued motion.
 */
export function useAnimationFrameState<T>(initial: T) {
  const [value, setValue] = useState(initial);
  const latest = useRef(initial);
  const frame = useRef<number | undefined>(undefined);
  const update = useCallback((action: SetStateAction<T>, immediate = false) => {
    latest.current = typeof action === 'function'
      ? (action as (previous: T) => T)(latest.current) : action;
    if (immediate) {
      if (frame.current !== undefined) cancelAnimationFrame(frame.current);
      frame.current = undefined;
      setValue(latest.current);
    } else if (frame.current === undefined) {
      frame.current = requestAnimationFrame(() => {
        frame.current = undefined;
        setValue(latest.current);
      });
    }
  }, []);
  useEffect(() => () => {
    if (frame.current !== undefined) cancelAnimationFrame(frame.current);
  }, []);
  return [value, update, latest] as const;
}
