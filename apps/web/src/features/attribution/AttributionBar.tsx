import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { fetchAttribution } from './attributionApi';
import { AttributionModal } from './AttributionModal';
import { parseAttributionSummary } from './parseAttribution';

type Props = {
  apiBaseUrl: string;
};

type AttributionState = {
  loading: boolean;
  error: string | null;
  text: string;
  version: string | null;
};

const INITIAL_STATE: AttributionState = {
  loading: true,
  error: null,
  text: '',
  version: null,
};

export function AttributionBar({ apiBaseUrl }: Props) {
  const [state, setState] = useState<AttributionState>(INITIAL_STATE);
  const [modalSection, setModalSection] = useState<
    'sources' | 'disclaimer' | null
  >(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  const refresh = useCallback(() => {
    abortControllerRef.current?.abort();
    const controller = new AbortController();
    abortControllerRef.current = controller;

    setState((prev) => ({ ...prev, loading: true, error: null }));

    void fetchAttribution(apiBaseUrl, { signal: controller.signal })
      .then((payload) => {
        if (controller.signal.aborted) return;
        setState({
          loading: false,
          error: null,
          text: payload.text,
          version: payload.version,
        });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setState((prev) => ({
          ...prev,
          loading: false,
          error: error instanceof Error ? error.message : String(error),
        }));
      });
  }, [apiBaseUrl]);

  useEffect(() => {
    refresh();
    return () => {
      abortControllerRef.current?.abort();
    };
  }, [refresh]);

  const summary = useMemo(() => {
    if (!state.text) return '© Cesium';
    return parseAttributionSummary(state.text);
  }, [state.text]);

  return (
    <div className="attributionBar" role="contentinfo" aria-label="归因与数据来源">
      <span className="attributionSummary" title={summary}>
        {summary}
      </span>
      <button
        type="button"
        className="attributionButton"
        onClick={() => setModalSection('sources')}
        aria-label="查看数据来源"
      >
        数据来源
      </button>
      <button
        type="button"
        className="attributionButton"
        onClick={() => setModalSection('disclaimer')}
        aria-label="查看免责声明"
      >
        免责声明
      </button>

      <AttributionModal
        open={modalSection !== null}
        section={modalSection ?? 'sources'}
        attributionText={state.text}
        version={state.version}
        loading={state.loading}
        error={state.error}
        onRetry={refresh}
        onClose={() => setModalSection(null)}
      />
    </div>
  );
}
