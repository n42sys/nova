"use client";

import { useCallback, useEffect, useState } from "react";

type Result<T> = { data?: T; error?: unknown; response: Response };

export type Resource<T> = {
  data?: T;
  error?: unknown;
  status?: number;
  loading: boolean;
  reload: () => Promise<void>;
};

/** Load once (and on `reload`) from a typed api call. Minimal by design; no caching. */
export function useResource<T>(load: () => Promise<Result<T>>, deps: unknown[]): Resource<T> {
  const [state, setState] = useState<Omit<Resource<T>, "reload">>({ loading: true });
  // `load` closes over `deps`; callers list them explicitly.
  const reload = useCallback(async () => {
    setState((previous) => ({ ...previous, loading: true }));
    try {
      const { data, error, response } = await load();
      setState({ data, error, status: response.status, loading: false });
    } catch (error) {
      setState({ error, status: 0, loading: false });
    }
  }, deps);
  useEffect(() => {
    void reload();
  }, [reload]);
  return { ...state, reload };
}
