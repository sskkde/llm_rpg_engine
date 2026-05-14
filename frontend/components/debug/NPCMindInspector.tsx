'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { useTranslations } from 'next-intl';
import { Loading } from '@/components/ui/Loading';
import { ErrorMessage } from '@/components/ui/ErrorMessage';
import { DebugEmptyState } from '@/components/debug/DebugEmptyState';
import { listSessionNpcs, getNpcMind } from '@/lib/api';
import type { SessionNPC, NPCMindResponse, NPCBelief, NPCMemory, NPCSecret, NPCGoal, NPCForbiddenKnowledge, NPCRelationshipMemory } from '@/types/api';

interface NPCMindInspectorProps {
  sessionId: string;
}

interface CollapsibleSectionProps {
  title: string;
  count: number;
  children: React.ReactNode;
}

function CollapsibleSection({ title, count, children }: CollapsibleSectionProps) {
  const [isOpen, setIsOpen] = useState(true);

  return (
    <div className="border border-slate-200 dark:border-slate-700 rounded-lg overflow-hidden">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between p-3 bg-slate-50 dark:bg-slate-800/50 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
      >
        <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
          {title}
          <span className="ml-2 text-xs px-2 py-0.5 bg-slate-200 dark:bg-slate-700 rounded-full">
            {count}
          </span>
        </span>
        <svg
          className={`w-4 h-4 text-slate-500 transition-transform ${isOpen ? 'rotate-180' : ''}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {isOpen && (
        <div className="p-3 space-y-2">
          {children}
        </div>
      )}
    </div>
  );
}

function BeliefItem({ belief }: { belief: NPCBelief }) {
  const t = useTranslations('Debug');
  return (
    <div className="bg-white dark:bg-slate-800 p-2 rounded border border-slate-100 dark:border-slate-700">
      <p className="text-sm text-slate-700 dark:text-slate-300">{belief.content}</p>
      <div className="mt-1 flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
        <span>{t('confidence')}: {Math.round(belief.confidence * 100)}%</span>
        {belief.source_turn !== undefined && (
          <span>{t('sourceTurn')}: {belief.source_turn}</span>
        )}
      </div>
    </div>
  );
}

function MemoryItem({ memory }: { memory: NPCMemory }) {
  const t = useTranslations('Debug');
  return (
    <div className="bg-white dark:bg-slate-800 p-2 rounded border border-slate-100 dark:border-slate-700">
      <p className="text-sm text-slate-700 dark:text-slate-300">{memory.content}</p>
      <div className="mt-1 flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
        <span>{t('strength')}: {Math.round(memory.strength * 100)}%</span>
        <span>{t('type')}: {memory.memory_type}</span>
        <span>{t('turn')}: {memory.created_turn}</span>
      </div>
    </div>
  );
}

function SecretItem({ secret }: { secret: NPCSecret }) {
  const t = useTranslations('Debug');
  return (
    <div className="bg-white dark:bg-slate-800 p-2 rounded border border-slate-100 dark:border-slate-700">
      <p className="text-sm text-slate-700 dark:text-slate-300">{secret.content}</p>
      <div className="mt-1 flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
        <span>{t('revealWillingness')}: {Math.round(secret.reveal_willingness * 100)}%</span>
        {secret.known_by.length > 0 && (
          <span>{t('knownBy')}: {secret.known_by.join(', ')}</span>
        )}
      </div>
    </div>
  );
}

function GoalItem({ goal }: { goal: NPCGoal }) {
  const t = useTranslations('Debug');
  return (
    <div className="bg-white dark:bg-slate-800 p-2 rounded border border-slate-100 dark:border-slate-700">
      <p className="text-sm text-slate-700 dark:text-slate-300">{goal.description}</p>
      <div className="mt-1 flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
        <span>{t('priority')}: {goal.priority}</span>
        <span>{t('status')}: {goal.status}</span>
      </div>
    </div>
  );
}

function ForbiddenKnowledgeItem({ knowledge }: { knowledge: NPCForbiddenKnowledge }) {
  const t = useTranslations('Debug');
  return (
    <div className="bg-white dark:bg-slate-800 p-2 rounded border border-slate-100 dark:border-slate-700">
      <p className="text-sm text-slate-700 dark:text-slate-300">{knowledge.content}</p>
      <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
        <span>{t('source')}: {knowledge.source}</span>
      </div>
    </div>
  );
}

function RelationshipItem({ relationship }: { relationship: NPCRelationshipMemory }) {
  const t = useTranslations('Debug');
  return (
    <div className="bg-white dark:bg-slate-800 p-2 rounded border border-slate-100 dark:border-slate-700">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
          {relationship.target_name}
        </span>
        <span className="text-xs px-2 py-0.5 bg-slate-100 dark:bg-slate-700 rounded text-slate-600 dark:text-slate-400">
          {relationship.relationship_type}
        </span>
      </div>
      {relationship.trust_score !== undefined && (
        <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
          {t('trustScore')}: {Math.round(relationship.trust_score * 100)}%
        </div>
      )}
      {relationship.memories.length > 0 && (
        <div className="mt-2 space-y-1">
          {relationship.memories.map((memory, idx) => (
            <p key={idx} className="text-xs text-slate-500 dark:text-slate-400 italic">
              &ldquo;{memory}&rdquo;
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

export function NPCMindInspector({ sessionId }: NPCMindInspectorProps) {
  const t = useTranslations('Debug');
  const [npcs, setNpcs] = useState<SessionNPC[]>([]);
  const [selectedNpcId, setSelectedNpcId] = useState<string>('');
  const [mind, setMind] = useState<NPCMindResponse | null>(null);
  const [isLoadingNpcs, setIsLoadingNpcs] = useState(false);
  const [isLoadingMind, setIsLoadingMind] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mindError, setMindError] = useState<string | null>(null);

  const loadNpcs = useCallback(async () => {
    if (!sessionId.trim()) return;
    setIsLoadingNpcs(true);
    setError(null);
    try {
      const data = await listSessionNpcs(sessionId);
      setNpcs(data.npcs);
      if (data.npcs.length > 0 && !selectedNpcId) {
        setSelectedNpcId(data.npcs[0].npc_id);
      }
    } catch (err: unknown) {
      const status = (err as { status?: number })?.status;
      if (status === 401 || status === 403) {
        setError(t('adminRequired'));
      } else {
        setError(t('failedToLoad'));
      }
    } finally {
      setIsLoadingNpcs(false);
    }
  }, [sessionId, selectedNpcId, t]);

  const loadMind = useCallback(async (npcId: string) => {
    if (!npcId || !sessionId.trim()) return;
    setIsLoadingMind(true);
    setMindError(null);
    try {
      const data = await getNpcMind(sessionId, npcId);
      setMind(data);
    } catch (err: unknown) {
      const status = (err as { status?: number })?.status;
      if (status === 401 || status === 403) {
        setMindError(t('adminRequired'));
      } else {
        setMindError(t('failedToLoad'));
      }
    } finally {
      setIsLoadingMind(false);
    }
  }, [sessionId, t]);

  useEffect(() => {
    if (sessionId.trim()) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      void loadNpcs();
    }
  }, [sessionId, loadNpcs]);

  useEffect(() => {
    if (selectedNpcId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      void loadMind(selectedNpcId);
    }
  }, [selectedNpcId, loadMind]);

  if (!sessionId.trim()) {
    return <DebugEmptyState message={t('emptyState.noSession')} />;
  }

  if (isLoadingNpcs && npcs.length === 0) {
    return <Loading size="md" text={t('loading')} />;
  }

  if (error) {
    return <ErrorMessage message={error} variant="card" onRetry={loadNpcs} />;
  }

  if (npcs.length === 0) {
    return <DebugEmptyState message={t('noNpcsFound')} />;
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-4">
        <label className="text-sm font-medium text-slate-700 dark:text-slate-300">
          {t('selectNpc')}:
        </label>
        <select
          value={selectedNpcId}
          onChange={(e) => setSelectedNpcId(e.target.value)}
          className="flex-1 max-w-xs px-3 py-2 bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-600 rounded-lg text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
        >
          {npcs.map((npc) => (
            <option key={npc.npc_id} value={npc.npc_id}>
              {npc.name}
            </option>
          ))}
        </select>
      </div>

      {isLoadingMind && <Loading size="sm" text={t('loading')} />}

      {mindError && <ErrorMessage message={mindError} variant="card" />}

      {mind && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
              {mind.npc_name}
            </h3>
            <span className={`text-xs px-2 py-1 rounded ${
              mind.viewer_role === 'admin'
                ? 'bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-300'
                : 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300'
            }`}>
              {mind.viewer_role === 'admin' ? t('adminView') : t('auditorView')}
            </span>
          </div>

          <CollapsibleSection title={t('beliefs')} count={mind.beliefs.length}>
            {mind.beliefs.length === 0 ? (
              <p className="text-sm text-slate-500 dark:text-slate-400">{t('noBeliefs')}</p>
            ) : (
              mind.beliefs.map((belief) => (
                <BeliefItem key={belief.belief_id} belief={belief} />
              ))
            )}
          </CollapsibleSection>

          <CollapsibleSection title={t('privateMemories')} count={mind.private_memories.length}>
            {mind.private_memories.length === 0 ? (
              <p className="text-sm text-slate-500 dark:text-slate-400">{t('noMemories')}</p>
            ) : (
              mind.private_memories.map((memory) => (
                <MemoryItem key={memory.memory_id} memory={memory} />
              ))
            )}
          </CollapsibleSection>

          <CollapsibleSection title={t('secrets')} count={mind.secrets.length}>
            {mind.secrets.length === 0 ? (
              <p className="text-sm text-slate-500 dark:text-slate-400">{t('noSecrets')}</p>
            ) : (
              mind.secrets.map((secret) => (
                <SecretItem key={secret.secret_id} secret={secret} />
              ))
            )}
          </CollapsibleSection>

          <CollapsibleSection title={t('goals')} count={mind.goals.length}>
            {mind.goals.length === 0 ? (
              <p className="text-sm text-slate-500 dark:text-slate-400">{t('noGoals')}</p>
            ) : (
              mind.goals.map((goal) => (
                <GoalItem key={goal.goal_id} goal={goal} />
              ))
            )}
          </CollapsibleSection>

          <CollapsibleSection title={t('forbiddenKnowledge')} count={mind.forbidden_knowledge.length}>
            {mind.forbidden_knowledge.length === 0 ? (
              <p className="text-sm text-slate-500 dark:text-slate-400">{t('noForbiddenKnowledge')}</p>
            ) : (
              mind.forbidden_knowledge.map((knowledge) => (
                <ForbiddenKnowledgeItem key={knowledge.knowledge_id} knowledge={knowledge} />
              ))
            )}
          </CollapsibleSection>

          <CollapsibleSection title={t('relationships')} count={mind.relationship_memories.length}>
            {mind.relationship_memories.length === 0 ? (
              <p className="text-sm text-slate-500 dark:text-slate-400">{t('noRelationships')}</p>
            ) : (
              mind.relationship_memories.map((relationship) => (
                <RelationshipItem key={relationship.target_entity_id} relationship={relationship} />
              ))
            )}
          </CollapsibleSection>
        </div>
      )}
    </div>
  );
}
