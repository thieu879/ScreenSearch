/**
 * Authentication context — the single source of truth for auth state in the React tree.
 *
 * On mount, calls `/auth/me` to restore the session from cookies. If that 401s, tries
 * `/auth/refresh` once. If both fail, the user is unauthenticated and protected routes
 * redirect to `/login`.
 *
 * Nothing is stored in localStorage — tokens live in HttpOnly cookies, and user state
 * lives here.
 */

import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';
import type { UserProfile } from '../api/auth';
import { authGoogleLogin, authLogin, authLogout, authMe, authRefresh, authRegister } from '../api/auth';

// ---------------------------------------------------------------------------
// Context shape
// ---------------------------------------------------------------------------

interface AuthContextValue {
  isAuthenticated: boolean;
  user: UserProfile | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<UserProfile>;
  loginWithGoogle: (code?: string, credential?: string, redirectUri?: string) => Promise<UserProfile>;
  register: (email: string, password: string, otp: string, fullName?: string, username?: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);

  // Attempt to restore session on mount
  useEffect(() => {
    let cancelled = false;

    const restore = async () => {
      try {
        const me = await authMe();
        if (!cancelled) setUser(me);
      } catch {
        // Access token expired or missing — try refresh
        try {
          const refreshRes = await authRefresh();
          if (!cancelled) setUser(refreshRes.user);
        } catch {
          // Both failed — user is not authenticated
          if (!cancelled) setUser(null);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    restore();
    return () => { cancelled = true; };
  }, []);

  const login = useCallback(async (email: string, password: string): Promise<UserProfile> => {
    const res = await authLogin(email, password);
    setUser(res.user);
    return res.user;
  }, []);

  const loginWithGoogle = useCallback(async (
    code?: string,
    credential?: string,
    redirectUri?: string,
  ): Promise<UserProfile> => {
    const res = await authGoogleLogin(code, credential, redirectUri);
    setUser(res.user);
    return res.user;
  }, []);

  const register = useCallback(async (
    email: string,
    password: string,
    otp: string,
    fullName?: string,
    username?: string,
  ) => {
    await authRegister(email, password, otp, fullName, username);
  }, []);

  const logout = useCallback(async () => {
    await authLogout();
    setUser(null);
    // Clean up any leftover localStorage from the old mock system
    localStorage.removeItem('ssp_auth_token');
    localStorage.removeItem('ssp_user');
    localStorage.removeItem('ssp_mock_db_users');
  }, []);

  const refreshUser = useCallback(async () => {
    try {
      const me = await authMe();
      setUser(me);
    } catch {
      setUser(null);
    }
  }, []);

  return (
    <AuthContext.Provider
      value={{
        isAuthenticated: user !== null,
        user,
        loading,
        login,
        loginWithGoogle,
        register,
        logout,
        refreshUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);

  if (!ctx) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return ctx;
}
