'use client';

import {useState} from 'react';
import { ProtectedRoute } from '@/components/ui/ProtectedRoute';
import { CombatPanel } from '@/components/game/CombatPanel';
import { Button } from '@/components/ui/Button';

export default function CombatTestPage() {
  return (
    <ProtectedRoute>
      <CombatTestContent />
    </ProtectedRoute>
  );
}

function CombatTestContent() {
  const [combatId, setCombatId] = useState<string>('test-combat-001');
  const [showCombat, setShowCombat] = useState(false);

  const handleCombatEnd = () => {
    setShowCombat(false);
  };

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold text-slate-900 dark:text-slate-100 mb-6">
        Combat UI Test
      </h1>

      {!showCombat ? (
        <div className="bg-white dark:bg-slate-800 rounded-lg shadow p-6">
          <p className="text-slate-600 dark:text-slate-400 mb-4">
            This page demonstrates the CombatPanel component. Enter a combat ID or use the default.
          </p>
          <div className="flex flex-col sm:flex-row gap-3">
            <input
              type="text"
              value={combatId}
              onChange={(e) => setCombatId(e.target.value)}
              placeholder="Combat ID"
              className="flex-1 px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-md bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100"
            />
            <Button onClick={() => setShowCombat(true)}>
              Load Combat
            </Button>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <Button 
            variant="outline" 
            onClick={() => setShowCombat(false)}
          >
            Back to Test Menu
          </Button>
          <CombatPanel 
            combatId={combatId} 
            onCombatEnd={handleCombatEnd} 
          />
        </div>
      )}
    </div>
  );
}
