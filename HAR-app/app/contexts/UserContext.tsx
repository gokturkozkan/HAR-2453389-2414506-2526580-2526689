
import { createContext, useState, ReactNode } from 'react';

interface User {
  username: string;
  id: string;
}

interface UserContextType {
  user: User | null;
  setUser: (user: User) => void;
}

export const UserContext = createContext<UserContextType | undefined>(undefined);

export function UserProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);

  return (
    <UserContext.Provider value = {{ user, setUser }}>
      {children}
    </UserContext.Provider>
  )
}

