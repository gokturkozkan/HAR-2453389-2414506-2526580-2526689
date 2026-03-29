
import { createContext, useState, useEffect, ReactNode, useMemo, useCallback } from 'react';
import { espStatusApi } from '@/apis/espStatusApi';

interface ConnectionContextType {
  connection: boolean; 
  setConnection: (connection: boolean) => void;
}

export const ConnectionContext = createContext<ConnectionContextType>({
  connection: false,
  setConnection: () => {},
});

export function ConnectionProvider({ children }: { children: ReactNode }) {
  const [connection, setConnectionState] = useState<boolean>(false);
  const { getEsp, getEspStatus } = useMemo(() => espStatusApi(), []);
  
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
        const esps = await getEsp();

        if (!esps || esps.length === 0) {
          if (!cancelled) setConnectionState(false);
          return;
        }

        const statusResults = await Promise.allSettled(
          esps.map((esp) => getEspStatus(esp.id))
        );

        // Keep current state when refresh has transient request failures.
        const hasFailures = statusResults.some((result) => result.status === 'rejected');
        if (hasFailures) {
          return;
        }

        const allConnected = statusResults.every(
          (result) => result.status === 'fulfilled' && result.value.isConnected === true
        );
        if (!cancelled) setConnectionState(allConnected);
      } catch (error) {
        console.error("Connection refresh failed:", error);
      }
    };

    refreshConnection();
    const interval = setInterval(refreshConnection, 30000);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [getEsp, getEspStatus]);

  // CRITICAL: Memoize the value object so React detects changes
  const value = useMemo(() => ({ connection, setConnection }), [connection, setConnection]);

  return (
    <ConnectionContext.Provider value={value}>
      {children}
    </ConnectionContext.Provider>
  )
}

