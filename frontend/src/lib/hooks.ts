import { useCallback, useEffect, useRef, useState, type DependencyList } from 'react';
import { errMsg } from '../api';
import { useJobs } from '../stores/jobs';
import type { WsMessage } from '../types';

export function useFetch<T>(fn: () => Promise<T>, deps: DependencyList) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const seq = useRef(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const reload = useCallback(async (quiet = false) => {
    const my = ++seq.current;
    if (!quiet) setLoading(true);
    try {
      const d = await fnRef.current();
      if (my === seq.current) {
        setData(d);
        setError(null);
      }
    } catch (e) {
      if (my === seq.current) setError(errMsg(e));
    } finally {
      if (my === seq.current) setLoading(false);
    }
  }, []);
  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return { data, error, loading, reload, setData };
}

/** Subscribe to websocket events (also fired by the polling fallback for job updates). */
export function useWsEvent(handler: (msg: WsMessage) => void) {
  const ref = useRef(handler);
  ref.current = handler;
  const subscribe = useJobs((s) => s.subscribe);
  useEffect(() => subscribe((m) => ref.current(m)), [subscribe]);
}

export function useInterval(fn: () => void, ms: number | null) {
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => {
    if (ms === null) return;
    const id = window.setInterval(() => ref.current(), ms);
    return () => window.clearInterval(id);
  }, [ms]);
}

/** Debounce a callback; returns [trigger, flush]. */
export function useDebounced<A extends unknown[]>(fn: (...args: A) => void, ms: number) {
  const ref = useRef(fn);
  ref.current = fn;
  const timer = useRef<number | null>(null);
  const last = useRef<A | null>(null);
  const trigger = useCallback(
    (...args: A) => {
      last.current = args;
      if (timer.current) window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => {
        timer.current = null;
        if (last.current) ref.current(...last.current);
        last.current = null;
      }, ms);
    },
    [ms],
  );
  const flush = useCallback(() => {
    if (timer.current) {
      window.clearTimeout(timer.current);
      timer.current = null;
      if (last.current) ref.current(...last.current);
      last.current = null;
    }
  }, []);
  return [trigger, flush] as const;
}
