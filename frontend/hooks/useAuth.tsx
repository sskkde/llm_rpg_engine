'use client';

import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import type {User, TokenResponse} from '@/types/api';
import {getCurrentUser, loginUser, registerUser} from '@/lib/api';

interface AuthContextType {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, password: string, email?: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let isMounted = true;

    const initializeAuth = async () => {
      const token = localStorage.getItem('access_token');
      if (!token) {
        if (isMounted) setIsLoading(false);
        return;
      }

      try {
        const userData = await getCurrentUser();
        if (isMounted && localStorage.getItem('access_token') === token) {
          setUser(userData);
        }
      } catch {
        if (isMounted && localStorage.getItem('access_token') === token) {
          localStorage.removeItem('access_token');
          setUser(null);
        }
      } finally {
        if (isMounted && localStorage.getItem('access_token') === token) {
          setIsLoading(false);
        }
      }
    };

    void initializeAuth();

    return () => {
      isMounted = false;
    };
  }, []);

  const login = async (username: string, password: string) => {
    const response: TokenResponse = await loginUser({ username, password });
    localStorage.setItem('access_token', response.access_token);
    setUser(response.user);
    setIsLoading(false);
  };

  const register = async (username: string, password: string, email?: string) => {
    await registerUser({username, password, email});
  };

  const logout = () => {
    localStorage.removeItem('access_token');
    setUser(null);
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: !!user,
        isLoading,
        login,
        register,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
