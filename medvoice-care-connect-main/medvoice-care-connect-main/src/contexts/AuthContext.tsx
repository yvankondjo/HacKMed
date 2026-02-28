import { createContext, useContext, useState, ReactNode } from "react";

type UserRole = "doctor" | "patient";

interface User {
  id: string;
  name: string;
  phone: string;
  role: UserRole;
  patientId?: string;
}

interface AuthContextType {
  isAuthenticated: boolean;
  user: User | null;
  login: (phone: string) => boolean;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | null>(null);

// POC: single user identified only by phone number.
const POC_USER = {
  id: "user-poc-1",
  name: "Utilisateur POC",
  role: "doctor",
} as const;

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);

  const login = (phone: string) => {
    const normalized = phone.trim();
    if (!normalized) return false;
    setUser({ ...POC_USER, phone: normalized });
    return true;
  };

  const logout = () => setUser(null);

  return (
    <AuthContext.Provider value={{ isAuthenticated: !!user, user, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
