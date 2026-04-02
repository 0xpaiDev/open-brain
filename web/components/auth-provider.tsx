"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import {
  getApiKey,
  removeApiKey,
  setApiKey,
  validateApiKey,
} from "@/lib/api";
import { AuthGateDialog } from "@/components/auth-gate-dialog";

interface AuthContextValue {
  isAuthenticated: boolean;
  isLoading: boolean;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue>({
  isAuthenticated: false,
  isLoading: true,
  logout: () => {},
});

export function useAuth() {
  return useContext(AuthContext);
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const key = getApiKey();
    if (!key) {
      setIsLoading(false);
      return;
    }

    validateApiKey(key).then((valid) => {
      if (valid) {
        setIsAuthenticated(true);
      } else {
        removeApiKey();
      }
      setIsLoading(false);
    });
  }, []);

  const handleLogin = useCallback((key: string) => {
    setApiKey(key);
    setIsAuthenticated(true);
  }, []);

  const logout = useCallback(() => {
    removeApiKey();
    setIsAuthenticated(false);
  }, []);

  return (
    <AuthContext.Provider value={{ isAuthenticated, isLoading, logout }}>
      {isLoading ? (
        <div className="flex h-screen items-center justify-center bg-background">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        </div>
      ) : isAuthenticated ? (
        children
      ) : (
        <AuthGateDialog onLogin={handleLogin} />
      )}
    </AuthContext.Provider>
  );
}
