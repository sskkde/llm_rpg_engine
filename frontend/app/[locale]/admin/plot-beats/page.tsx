'use client';

import React from 'react';
import {ProtectedRoute} from '@/components/ui/ProtectedRoute';
import {PlotBeatEditor} from '@/components/admin/PlotBeatEditor';

export default function PlotBeatsPage() {
  return (
    <ProtectedRoute>
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <PlotBeatEditor />
      </div>
    </ProtectedRoute>
  );
}
