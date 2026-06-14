import { create } from 'zustand';
import type { Project, Conversation } from '../types';
import { apiClient } from '../api/client';
import { useChatStore } from './chat';

interface ProjectsState {
  projects: Project[];
  conversations: Record<string, Conversation[]>;
  workspaceProjectId: string | null;
  expandedProjects: Set<string>;
  isLoading: boolean;
  error: string | null;

  loadProjects: () => Promise<void>;
  loadConversations: (projectId: string) => Promise<void>;
  createProject: (name: string) => Promise<Project>;
  deleteProject: (projectId: string) => Promise<void>;
  createConversation: (projectId: string, name: string) => Promise<Conversation>;
  deleteConversation: (projectId: string, conversationId: string) => Promise<void>;
  createWorkspaceConversation: (name?: string) => Promise<Conversation>;
  toggleProject: (projectId: string) => void;
  expandProject: (projectId: string) => void;
}

export const useProjectsStore = create<ProjectsState>((set, get) => ({
  projects: [],
  conversations: {},
  workspaceProjectId: null,
  expandedProjects: new Set(),
  isLoading: false,
  error: null,

  loadProjects: async () => {
    set({ isLoading: true, error: null });
    try {
      const [projects, me] = await Promise.all([
        apiClient.listProjects(),
        apiClient.me() as Promise<{ project_id?: number | null } | null>,
      ]);
      const workspaceProjectId = me?.project_id ? String(me.project_id) : null;
      set({ projects, workspaceProjectId, isLoading: false });
      for (const p of projects) {
        get().loadConversations(p.id);
        set(state => ({ expandedProjects: new Set([...state.expandedProjects, p.id]) }));
      }
    } catch (err) {
      set({ error: (err as Error).message, isLoading: false });
    }
  },

  loadConversations: async (projectId: string) => {
    try {
      const conversations = await apiClient.listConversations(projectId);
      set(state => ({
        conversations: { ...state.conversations, [projectId]: conversations },
      }));
    } catch (_) {
      // silently ignore
    }
  },

  createProject: async (name: string) => {
    const project = await apiClient.createProject(name);
    set(state => ({
      projects: [project, ...state.projects],
      conversations: { ...state.conversations, [project.id]: [] },
      expandedProjects: new Set([...state.expandedProjects, project.id]),
    }));
    return project;
  },

  deleteProject: async (projectId: string) => {
    await apiClient.deleteProject(projectId);
    set(state => {
      const { [projectId]: _, ...rest } = state.conversations;
      const nextExpanded = new Set(state.expandedProjects);
      nextExpanded.delete(projectId);
      return {
        projects: state.projects.filter(p => p.id !== projectId),
        conversations: rest,
        expandedProjects: nextExpanded,
      };
    });
  },

  createConversation: async (projectId: string, name: string) => {
    const conv = await apiClient.createConversation(projectId, name);
    set(state => ({
      conversations: {
        ...state.conversations,
        [projectId]: [conv, ...(state.conversations[projectId] ?? [])],
      },
    }));
    await useChatStore.getState().loadSession(conv.id);
    return conv;
  },

  createWorkspaceConversation: async (name = 'New Chat') => {
    const { workspaceProjectId, createConversation, expandProject } = get();
    if (!workspaceProjectId) throw new Error('Workspace project not loaded yet');
    const conv = await createConversation(workspaceProjectId, name);
    expandProject(workspaceProjectId);
    return conv;
  },

  deleteConversation: async (projectId: string, conversationId: string) => {
    await apiClient.deleteConversation(projectId, conversationId);
    set(state => ({
      conversations: {
        ...state.conversations,
        [projectId]: (state.conversations[projectId] ?? []).filter(c => c.id !== conversationId),
      },
    }));
    const chatStore = useChatStore.getState();
    if (chatStore.currentSessionId === conversationId) {
      useChatStore.setState({ currentSessionId: null });
    }
  },

  toggleProject: (projectId: string) => {
    set(state => {
      const next = new Set(state.expandedProjects);
      if (next.has(projectId)) {
        next.delete(projectId);
      } else {
        next.add(projectId);
        get().loadConversations(projectId);
      }
      return { expandedProjects: next };
    });
  },

  expandProject: (projectId: string) => {
    set(state => ({ expandedProjects: new Set([...state.expandedProjects, projectId]) }));
    get().loadConversations(projectId);
  },
}));
