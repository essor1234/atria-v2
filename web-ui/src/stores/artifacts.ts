import { create } from 'zustand';
import type { Artifact } from '../types';
import { apiClient } from '../api/client';

interface ArtifactsState {
  // keyed by conversationId (string form of int)
  artifacts: Record<string, Artifact[]>;
  loading: Record<string, boolean>;
  scanning: boolean;

  loadArtifacts: (conversationId: string) => Promise<void>;
  scanArtifacts: (conversationId: string) => Promise<void>;
  togglePin: (conversationId: string, artifactId: number, pinned: boolean) => Promise<void>;
  deleteArtifact: (conversationId: string, artifactId: number) => Promise<void>;
  addArtifact: (conversationId: string, artifact: Artifact) => void;
  setArtifacts: (conversationId: string, artifacts: Artifact[]) => void;
}

export const useArtifactsStore = create<ArtifactsState>((set, get) => ({
  artifacts: {},
  loading: {},
  scanning: false,

  loadArtifacts: async (conversationId: string) => {
    const convInt = parseInt(conversationId, 10);
    if (isNaN(convInt)) return;
    set(s => ({ loading: { ...s.loading, [conversationId]: true } }));
    try {
      const items = await apiClient.listArtifacts(convInt);
      set(s => ({
        artifacts: { ...s.artifacts, [conversationId]: items },
        loading: { ...s.loading, [conversationId]: false },
      }));
    } catch {
      set(s => ({ loading: { ...s.loading, [conversationId]: false } }));
    }
  },

  scanArtifacts: async (conversationId: string) => {
    const convInt = parseInt(conversationId, 10);
    if (isNaN(convInt)) return;
    set({ scanning: true });
    try {
      const items = await apiClient.scanArtifacts(convInt);
      set(s => ({
        artifacts: { ...s.artifacts, [conversationId]: items },
        scanning: false,
      }));
    } catch {
      set({ scanning: false });
    }
  },

  togglePin: async (conversationId: string, artifactId: number, pinned: boolean) => {
    await apiClient.updateArtifact(artifactId, { pinned: !pinned });
    await get().loadArtifacts(conversationId);
  },

  deleteArtifact: async (conversationId: string, artifactId: number) => {
    await apiClient.deleteArtifact(artifactId);
    set(s => ({
      artifacts: {
        ...s.artifacts,
        [conversationId]: (s.artifacts[conversationId] ?? []).filter(a => a.id !== artifactId),
      },
    }));
  },

  addArtifact: (conversationId: string, artifact: Artifact) => {
    set(s => ({
      artifacts: {
        ...s.artifacts,
        [conversationId]: [...(s.artifacts[conversationId] ?? []), artifact],
      },
    }));
  },

  setArtifacts: (conversationId: string, artifacts: Artifact[]) => {
    set(s => ({
      artifacts: {
        ...s.artifacts,
        [conversationId]: artifacts,
      },
    }));
  },
}));
