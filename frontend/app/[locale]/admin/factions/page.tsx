'use client';

import React from 'react';
import {ProtectedRoute} from '@/components/ui/ProtectedRoute';
import {FactionEditor} from '@/components/admin/FactionEditor';

export default function FactionsPage() {
  return (
    <ProtectedRoute>
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <FactionEditor />
      </div>
    </ProtectedRoute>
  );
}
