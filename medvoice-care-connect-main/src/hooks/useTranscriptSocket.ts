import { useRef, useState, useCallback } from "react";

export interface TranscriptEntry {
  speaker: "Doctor" | "Patient";
  text: string;
  timestamp: string;
}

interface UseTranscriptSocketOptions {
  /** WebSocket URL — when null, uses demo mode only */
  url?: string | null;
  onMessage?: (entry: TranscriptEntry) => void;
}

/**
 * Hook abstracting a WebSocket connection for live transcript.
 * Exposes connect/disconnect, connection state, and a way to
 * inject simulated messages (for demo without a real mic/WS).
 */
export function useTranscriptSocket(options: UseTranscriptSocketOptions = {}) {
  const { url = null, onMessage } = options;
  const wsRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([]);

  const appendEntry = useCallback(
    (entry: TranscriptEntry) => {
      setTranscript((prev) => [...prev, entry]);
      onMessage?.(entry);
    },
    [onMessage]
  );

  const connect = useCallback(() => {
    if (!url) {
      // No real WS URL — just mark as connected for demo mode
      setConnected(true);
      return;
    }

    try {
      const ws = new WebSocket(url);

      ws.onopen = () => setConnected(true);

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as TranscriptEntry;
          if (data.speaker && data.text) {
            appendEntry(data);
          }
        } catch {
          // ignore malformed messages
        }
      };

      ws.onclose = () => setConnected(false);
      ws.onerror = () => ws.close();

      wsRef.current = ws;
    } catch {
      setConnected(false);
    }
  }, [url, appendEntry]);

  const disconnect = useCallback(() => {
    wsRef.current?.close();
    wsRef.current = null;
    setConnected(false);
  }, []);

  /** Inject a message as if it came from the WebSocket (for demo/simulate) */
  const injectMessage = useCallback(
    (entry: TranscriptEntry) => {
      appendEntry(entry);
    },
    [appendEntry]
  );

  /** Get the full transcript as serializable JSON */
  const getSerializableTranscript = useCallback(() => {
    return JSON.parse(JSON.stringify(transcript)) as TranscriptEntry[];
  }, [transcript]);

  return {
    connected,
    transcript,
    connect,
    disconnect,
    injectMessage,
    getSerializableTranscript,
  };
}
