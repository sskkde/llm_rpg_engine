'use client';

import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import type { User, TokenResponse } from '@/types/api';
import { loginUser, registerUser, getCurrentUser } from '@/lib/api';

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
  const [isLoading, setIsLoading] = useState(
    () => typeof window !== 'undefined' && Boolean(localStorage.getItem('access_token'))
  );

  useEffect(() => {
    const token = localStorage.getItem('access_token');
    if (token) {
      getCurrentUser()
        .then((userData) => {
          setUser(userData);
        })
        .catch(() => {
          localStorage.removeItem('access_token');
        })
        .finally(() => {
          setIsLoading(false);
        });
    }
  }, []);

  const login = async (username: string, password: string) => {
    const response: TokenResponse = await loginUser({ username, password });
    localStorage.setItem('access_token', response.access_token);
    setUser(response.user);
  };

  const register = async (username: string, password: string, email?: string) => {
    const response: TokenResponse = await registerUser({ username, password, email });
    localStorage.setItem('access_token', response.access_token);
    setUser(response.user);
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
