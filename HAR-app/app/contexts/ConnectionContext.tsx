
import { createContext, useState, useEffect, ReactNode, useMemo, useCallback } from 'react';
import { espStatusApi } from '@/apis/espStatusApi';
import { EspStatus } from '../types/espTypes';

interface ConnectionContextType {
  connection: boolean; 
  setConnection: (connection: boolean) => void;
}

export const ConnectionContext = createContext<ConnectionContextType>({
  connection: false,
  setConnection: () => {},
});

const STATUS_TIMEOUT_MS = 10000;
const CONNECTION_REFRESH_MS = 10000;

const CONNECTED_STATUSES = new Set([
  'open',
  'ready',
  'receiving',
  'open - no data',
  'open - unreadable',
]);

const isNodeConnected = (node: EspStatus) => {
  const status = node.status?.trim().toLowerCase();

  return node.isConnected === true || Boolean(status && CONNECTED_STATUSES.has(status));
};

const withTimeout = async <T,>(promise: Promise<T>, ms: number): Promise<T> => {
  return Promise.race([
    promise,
    new Promise<T>((_, reject) =>
      setTimeout(() => reject(new Error('Request timed out')), ms)
    ),
  ]);
};

export function ConnectionProvider({ children }: { children: ReactNode }) {
  const [connection, setConnectionState] = useState<boolean>(false);
  const { getAllEspStatus } = useMemo(() => espStatusApi(), []);
  
  // Explicitly set connection to false on mount
  useEffect(() => {
    setConnectionState(false);
  }, []);

  const setConnection = useCallback((value: boolean) => {
    setConnectionState(value);
  }, []);

  useEffect(() => {
    let cancelled = false;

    const refreshConnection = async () => {
      try {
        const esps = await withTimeout(getAllEspStatus(), STATUS_TIMEOUT_MS);

        if (!esps || esps.length === 0) {
          return;
        }

        const trackedNodes = esps.filter((esp) => [1, 2, 3].includes(esp.id));
        const allConnected =
          trackedNodes.length === 3 && trackedNodes.every(isNodeConnected);

        if (!cancelled) setConnectionState(allConnected);
      } catch (error) {
        console.warn("Connection refresh delayed; keeping last known state.", error);
      }
    };

    refreshConnection();
    const interval = setInterval(refreshConnection, CONNECTION_REFRESH_MS);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [getAllEspStatus]);

  const value = useMemo(() => ({ connection, setConnection }), [connection, setConnection]);

  return (
    <ConnectionContext.Provider value={value}>
      {children}
    </ConnectionContext.Provider>
  )
}
