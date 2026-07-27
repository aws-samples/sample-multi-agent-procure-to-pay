// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { createContext, useContext, useState, useEffect } from "react";
import type { ReactNode } from "react";
import type { AuthUser } from "./auth";
import { login as authLogin, logout as authLogout, getAuthUser } from "./auth";

interface AuthContextType {
  user: AuthUser | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType>({
  user: null,
  loading: true,
  login: async () => {},
  logout: () => {},
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getAuthUser()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  const login = async (username: string, password: string) => {
    const u = await authLogin(username, password);
    setUser(u);
  };

  const logout = async () => {
    await authLogout();
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components -- context hook co-located with its provider; splitting into a separate file is a larger refactor with no runtime benefit.
export const useAuth = () => useContext(AuthContext);
