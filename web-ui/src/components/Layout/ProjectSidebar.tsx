import {
  ChevronRight,
  Folder,
  FolderOpen,
  MessageSquare,
  Package,
  Plus,
  Settings,
  Trash2,
} from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { useEffect, useState } from "react";
import { useLocalStorage } from "usehooks-ts";
import { ResizeHandle } from "../ui/ResizeHandle";
import { useChatStore } from "../../stores/chat";
import { useModulesStore } from "../../stores/modules";
import { useProjectsStore } from "../../stores/projects";
import type { Project } from "../../types";
import { SettingsModal } from "../Settings/SettingsModal";
import { CreateConversationModal } from "./CreateConversationModal";
import { CreateProjectModal } from "./CreateProjectModal";

export function ProjectSidebar() {
  const {
    projects,
    conversations,
    expandedProjects,
    isLoading,
    loadProjects,
    toggleProject,
    deleteProject,
    deleteConversation,
    createWorkspaceConversation,
  } = useProjectsStore();
  const workspaceProjectId = useProjectsStore((s) => s.workspaceProjectId);

  const currentSessionId = useChatStore((s) => s.currentSessionId);
  const loadSession = useChatStore((s) => s.loadSession);
  const isCollapsed = useChatStore((s) => s.sidebarCollapsed);
  const toggleSidebar = useChatStore((s) => s.toggleSidebar);
  const runningSessions = useChatStore((s) => s.runningSessions);

  const modulesWithDashboards = useModulesStore((s) => s.modulesWithDashboards);
  const activeModuleDashboard = useModulesStore((s) => s.activeModuleDashboard);
  const moduleBadges = useModulesStore((s) => s.badges);
  const openModuleDashboard = useModulesStore((s) => s.openDashboard);
  const closeModuleDashboard = useModulesStore((s) => s.closeDashboard);
  const refreshModules = useModulesStore((s) => s.refresh);

  const [createProjectOpen, setCreateProjectOpen] = useState(false);
  const [createConvFor, setCreateConvFor] = useState<Project | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<{
    type: "project" | "conv";
    id: string;
    projectId?: string;
  } | null>(null);
  const [creatingChat, setCreatingChat] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useLocalStorage<number>("sidebar.width", 256);

  const reduce = useReducedMotion();

  useEffect(() => {
    loadProjects();
    refreshModules();
  }, []);

  const handleNewChat = async () => {
    if (creatingChat || !workspaceProjectId) return;
    setCreatingChat(true);
    try {
      await createWorkspaceConversation("New Chat");
    } finally {
      setCreatingChat(false);
    }
  };

  const handleDeleteConfirmed = async () => {
    if (!confirmDelete) return;
    if (confirmDelete.type === "project") {
      await deleteProject(confirmDelete.id);
    } else if (confirmDelete.projectId) {
      await deleteConversation(confirmDelete.projectId, confirmDelete.id);
    }
    setConfirmDelete(null);
  };

  if (isCollapsed) {
    return (
      <aside
        data-surface="dark"
        className="w-12 flex flex-col items-center py-3 gap-3 bg-bg-100 border-r border-border-300/15"
      >
        <button
          onClick={toggleSidebar}
          className="p-1.5 rounded hover:bg-bg-200 text-text-400 hover:text-text-200 transition-colors"
          title="Expand sidebar"
        >
          <ChevronRight className="w-4 h-4" />
        </button>
        <button
          onClick={() => {
            toggleSidebar();
            setCreateProjectOpen(true);
          }}
          className="p-1.5 rounded hover:bg-bg-200 text-text-400 hover:text-text-200 transition-colors"
          title="New project"
        >
          <Plus className="w-4 h-4" />
        </button>
        {modulesWithDashboards.length > 0 && (
          <div className="w-6 h-px bg-border-300/15 my-1" />
        )}
        {modulesWithDashboards.map((m) => {
          const isActive = activeModuleDashboard === m.name;
          const badge = moduleBadges[m.name] || null;
          return (
            <button
              key={m.name}
              onClick={() =>
                isActive ? closeModuleDashboard() : openModuleDashboard(m.name)
              }
              className={`relative p-1.5 rounded transition-colors ${
                isActive
                  ? "bg-accent-main-100/10 text-accent-main-100"
                  : "hover:bg-bg-200 text-text-400 hover:text-text-200"
              }`}
              title={m.tooltip}
              aria-label={m.display_name}
            >
              {m.icon_url ? (
                <img src={m.icon_url} className="w-4 h-4" alt="" />
              ) : (
                <Package className="w-4 h-4" />
              )}
              {badge && badge.count > 0 && (
                <span
                  className={`absolute -top-0.5 -right-0.5 w-1.5 h-1.5 rounded-full ${
                    badge.severity === "danger"
                      ? "bg-semantic-danger"
                      : badge.severity === "warning"
                        ? "bg-amber-400"
                        : "bg-accent-main-100"
                  }`}
                />
              )}
            </button>
          );
        })}
      </aside>
    );
  }

  return (
    <>
      <motion.aside
        initial={reduce ? false : { opacity: 0, x: -12 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
        data-surface="dark"
        style={{ width: sidebarWidth }}
        className="relative flex-shrink-0 flex flex-col bg-bg-100 border-r border-border-300/15 overflow-hidden"
      >
        {/* Drag the right edge to resize the sidebar (kept within bounds — aside is overflow-hidden) */}
        <ResizeHandle
          side="right"
          width={sidebarWidth}
          min={200}
          max={480}
          onResize={setSidebarWidth}
          className="absolute top-0 bottom-0 right-0 w-2 cursor-col-resize hover:bg-sky-400/30 transition-colors z-30"
        />
        {/* Header: collapse + New Chat + New Project + Settings */}
        <div className="flex items-center justify-between px-3 py-2.5 border-b border-border-300/10">
          <button
            onClick={toggleSidebar}
            className="text-xs font-mono font-semibold text-text-300 hover:text-text-100 transition-colors flex items-center gap-1"
          >
            <ChevronRight className="w-3 h-3 rotate-180" />
            Workspace
          </button>
          <div className="flex items-center gap-1">
            {/* New Chat — creates a conversation inside the user's workspace project */}
            <button
              onClick={handleNewChat}
              disabled={creatingChat}
              className="flex items-center gap-1 px-2 py-1 rounded bg-accent-main-100/10 hover:bg-accent-main-100/20 text-accent-main-100 text-xs font-mono font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
              title="New chat in your workspace"
            >
              <Plus className="w-3 h-3" />
              Chat
            </button>
            <button
              onClick={() => setCreateProjectOpen(true)}
              className="p-1 rounded hover:bg-bg-200 text-text-400 hover:text-text-200 transition-colors"
              title="New project"
            >
              <Folder className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={() => setSettingsOpen(true)}
              className="p-1 rounded hover:bg-bg-200 text-text-400 hover:text-text-200 transition-colors"
              title="Settings"
            >
              <Settings className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto py-1">
          {isLoading && projects.length === 0 && (
            <p className="text-xs text-text-400 font-mono px-4 py-3">
              Loading…
            </p>
          )}
          {!isLoading && projects.length === 0 && (
            <div className="px-4 py-6 text-center">
              <MessageSquare className="w-7 h-7 text-text-500 mx-auto mb-2 opacity-40" />
              <p className="text-xs text-text-300 mb-3">
                Start chatting or create a project
              </p>
              <div className="flex flex-col gap-1.5">
                <button
                  onClick={handleNewChat}
                  disabled={creatingChat}
                  className="text-xs bg-accent-main-100/10 hover:bg-accent-main-100/20 text-accent-main-100 font-mono px-3 py-1.5 rounded transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  + New Chat
                </button>
                <button
                  onClick={() => setCreateProjectOpen(true)}
                  className="text-xs text-text-400 hover:text-text-200 font-mono transition-colors"
                >
                  + New Project
                </button>
              </div>
            </div>
          )}
          {modulesWithDashboards.length > 0 && (
            <div className="border-t border-border-300/10 mt-2 pt-2">
              <div className="px-3 pb-1 text-[10px] font-mono uppercase tracking-wider text-text-500">
                Modules
              </div>
              {modulesWithDashboards.map((m) => {
                const isActive = activeModuleDashboard === m.name;
                const badge = moduleBadges[m.name] || null;
                return (
                  <button
                    key={m.name}
                    onClick={() =>
                      isActive
                        ? closeModuleDashboard()
                        : openModuleDashboard(m.name)
                    }
                    title={m.tooltip}
                    className={`group flex items-center gap-2 px-3 py-1.5 w-full transition-colors text-left ${
                      isActive
                        ? "bg-accent-main-100/10 border-r-2 border-accent-main-100"
                        : "hover:bg-bg-200/40"
                    }`}
                  >
                    {m.icon_url ? (
                      <img
                        src={m.icon_url}
                        className="w-3.5 h-3.5 flex-shrink-0"
                        alt=""
                      />
                    ) : (
                      <Package
                        className={`w-3.5 h-3.5 flex-shrink-0 ${isActive ? "text-accent-main-100" : "text-text-400"}`}
                      />
                    )}
                    <span
                      className={`flex-1 text-xs truncate ${isActive ? "text-accent-main-100 font-medium" : "text-text-200"}`}
                    >
                      {m.display_name}
                    </span>
                    {badge && badge.count > 0 && (
                      <span
                        className={`w-1.5 h-1.5 rounded-full ${
                          badge.severity === "danger"
                            ? "bg-semantic-danger"
                            : badge.severity === "warning"
                              ? "bg-amber-400"
                              : "bg-accent-main-100"
                        }`}
                        title={`${badge.count}`}
                      />
                    )}
                  </button>
                );
              })}
            </div>
          )}
          {projects.map((project) => {
            const isExpanded = expandedProjects.has(project.id);
            const convs = conversations[project.id] ?? [];

            return (
              <div key={project.id}>
                <div
                  className="group flex items-center gap-1.5 px-2 py-1.5 hover:bg-bg-200/50 cursor-pointer select-none"
                  onClick={() => toggleProject(project.id)}
                >
                  {isExpanded ? (
                    <FolderOpen className="w-4 h-4 text-accent-main-100 flex-shrink-0" />
                  ) : (
                    <Folder className="w-4 h-4 text-text-400 flex-shrink-0" />
                  )}
                  <span className="flex-1 text-xs font-medium text-text-100 truncate">
                    {project.name}
                  </span>
                  <span className="text-[10px] text-text-500 font-mono opacity-0 group-hover:opacity-100">
                    {convs.length}
                  </span>
                  <div
                    className="opacity-0 group-hover:opacity-100 flex items-center gap-0.5"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <button
                      onClick={() => setCreateConvFor(project)}
                      className="p-0.5 rounded hover:bg-bg-300 text-text-400 hover:text-accent-main-100 transition-colors"
                      title="New conversation"
                    >
                      <Plus className="w-3 h-3" />
                    </button>
                    <button
                      onClick={() =>
                        setConfirmDelete({ type: "project", id: project.id })
                      }
                      className="p-0.5 rounded hover:bg-bg-300 text-text-400 hover:text-semantic-danger transition-colors"
                      title="Delete project"
                    >
                      <Trash2 className="w-3 h-3" />
                    </button>
                  </div>
                </div>

                {isExpanded && (
                  <div className="ml-3 border-l border-border-300/15">
                    {convs.length === 0 && (
                      <button
                        onClick={() => setCreateConvFor(project)}
                        className="flex items-center gap-1.5 w-full px-3 py-1.5 text-xs text-text-400 hover:text-accent-main-100 font-mono transition-colors"
                      >
                        <Plus className="w-3 h-3" />
                        New conversation
                      </button>
                    )}
                    {convs.map((conv) => {
                      const isActive = currentSessionId === conv.id;
                      const isRunning = runningSessions.has(conv.id);
                      return (
                        <div
                          key={conv.id}
                          onClick={() => loadSession(conv.id)}
                          className={`group flex items-center gap-1.5 px-3 py-1.5 cursor-pointer transition-colors ${
                            isActive
                              ? "bg-accent-main-100/10 border-r-2 border-accent-main-100"
                              : "hover:bg-bg-200/40"
                          }`}
                        >
                          {isRunning ? (
                            <span className="w-3 h-3 flex-shrink-0 inline-block rounded-full bg-amber-400 animate-pulse" />
                          ) : (
                            <MessageSquare
                              className={`w-3 h-3 flex-shrink-0 ${isActive ? "text-accent-main-100" : "text-text-400"}`}
                            />
                          )}
                          <span
                            className={`flex-1 text-xs truncate ${isActive ? "text-accent-main-100 font-medium" : "text-text-200"}`}
                          >
                            {conv.name}
                          </span>
                          {conv.message_count > 0 && (
                            <span className="text-[10px] text-text-500 font-mono">
                              {conv.message_count}
                            </span>
                          )}
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              setConfirmDelete({
                                type: "conv",
                                id: conv.id,
                                projectId: project.id,
                              });
                            }}
                            className="opacity-0 group-hover:opacity-100 p-0.5 rounded hover:bg-bg-300 text-text-400 hover:text-semantic-danger transition-colors"
                          >
                            <Trash2 className="w-3 h-3" />
                          </button>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </motion.aside>

      <CreateProjectModal
        isOpen={createProjectOpen}
        onClose={() => setCreateProjectOpen(false)}
      />
      <CreateConversationModal
        isOpen={!!createConvFor}
        projectId={createConvFor?.id ?? ""}
        projectName={createConvFor?.name ?? ""}
        onClose={() => setCreateConvFor(null)}
      />
      <SettingsModal
        isOpen={settingsOpen}
        onClose={() => setSettingsOpen(false)}
      />

      {confirmDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div
            data-surface="dark"
            className="bg-bg-000 border border-border-300/20 rounded-xl p-6 w-80 shadow-modal"
          >
            <p className="text-sm text-text-100 mb-4">
              Delete this{" "}
              {confirmDelete.type === "project"
                ? "project and all its conversations"
                : "conversation"}
              ? This cannot be undone.
            </p>
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => setConfirmDelete(null)}
                className="px-3 py-1.5 text-sm text-text-300 hover:text-text-100"
              >
                Cancel
              </button>
              <button
                onClick={handleDeleteConfirmed}
                className="px-3 py-1.5 text-sm bg-semantic-danger text-white rounded-lg hover:bg-semantic-danger/90"
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
