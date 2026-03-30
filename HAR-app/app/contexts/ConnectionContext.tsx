
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

function areAllNodesStreaming(statuses: EspStatus[]): boolean {
  return (
    statuses.length > 0 &&
    statuses.every((esp) => {
      const state = esp.state ?? (esp.isConnected ? 'streaming' : 'disconnected');
      return state === 'streaming';
    })
  );
}

export function ConnectionProvider({ children }: { children: ReactNode }) {
  const [connection, setConnectionState] = useState<boolean>(false);
  const { getEspStatuses } = useMemo(() => espStatusApi(), []);
  
  // Explicitly set connection to false on mount
  useEffect(() => {
    setConnectionState(false);
  }, []);

  const setConnection = useCallback((value: boolean) => {
    console.log("🔴 setConnection CALLED with:", value);
    setConnectionState(value);
  }, []);

  useEffect(() => {
    console.log("🟢 CONNECTION STATE CHANGED TO:", connection);
  }, [connection]);

  useEffect(() => {
    let cancelled = false;

    const refreshConnection = async () => {
      try {
        const statuses = await getEspStatuses();
        if (!statuses || statuses.length === 0) {
          if (!cancelled) setConnectionState(false);
          return;
        }
        if (!cancelled) setConnectionState(areAllNodesStreaming(statuses));
      } catch (error) {
        console.error("Connection refresh failed:", error);
      }
    };

    refreshConnection();
    const interval = setInterval(refreshConnection, 5000);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [getEspStatuses]);

  // CRITICAL: Memoize the value object so React detects changes
  const value = useMemo(() => ({ connection, setConnection }), [connection, setConnection]);

  return (
    <ConnectionContext.Provider value={value}>
      {children}
    </ConnectionContext.Provider>
  )
}

