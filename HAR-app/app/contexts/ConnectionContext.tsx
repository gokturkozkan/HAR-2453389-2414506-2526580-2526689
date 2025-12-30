
import { createContext, useState, useEffect, ReactNode, useMemo, useCallback } from 'react';

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

  // CRITICAL: Memoize the value object so React detects changes
  const value = useMemo(() => ({ connection, setConnection }), [connection, setConnection]);

  return (
    <ConnectionContext.Provider value={value}>
      {children}
    </ConnectionContext.Provider>
  )
}

