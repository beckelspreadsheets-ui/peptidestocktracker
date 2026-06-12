import { useEffect, useState } from "react";

interface State<T> {
  data: T | null;
  live: boolean;
  loading: boolean;
  error: string | null;
}

/** Minimal fetch hook over the api client functions (which return {data,live}). */
export function useFetch<T>(
  fn: () => Promise<{ data: T; live: boolean }>,
  deps: unknown[] = [],
): State<T> {
  const [state, setState] = useState<State<T>>({
    data: null,
    live: false,
    loading: true,
    error: null,
  });

  useEffect(() => {
    let cancelled = false;
    setState((s) => ({ ...s, loading: true }));
    fn()
      .then(({ data, live }) => {
        if (!cancelled) setState({ data, live, loading: false, error: null });
      })
      .catch((e) => {
        if (!cancelled)
          setState({ data: null, live: false, loading: false, error: String(e) });
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return state;
}
