import { useState, useCallback } from 'react';
import { ProjectSidebar } from '../components/Layout/ProjectSidebar';
import { ChatInterface } from '../components/Chat/ChatInterface';
import { ApprovalDialog } from '../components/ApprovalDialog';
import { AskUserDialog } from '../components/Chat/AskUserDialog';
import { PlanApprovalDialog } from '../components/Chat/PlanApprovalDialog';
import { CommandPalette } from '../components/Chat/CommandPalette';
import { StatusDialog } from '../components/Chat/StatusDialog';
import { ArtifactViewer } from '../components/ArtifactViewer/ArtifactViewer';
import { useChatStore } from '../stores/chat';
import { useModulesStore } from '../stores/modules';
import { ModuleDashboardView } from '../components/ModuleDashboard/ModuleDashboardView';

export function ChatPage() {
  const [statusDialogOpen, setStatusDialogOpen] = useState(false);

  const commandPaletteOpen = useChatStore(state => state.commandPaletteOpen);
  const closeCommandPalette = useChatStore(state => state.closeCommandPalette);
  const activeModuleDashboard = useModulesStore(s => s.activeModuleDashboard);

  const openStatusDialog = useCallback(() => setStatusDialogOpen(true), []);
  const closeStatusDialog = useCallback(() => setStatusDialogOpen(false), []);

  return (
    <div className="flex-1 min-h-0 flex overflow-hidden bg-bg-000">
      <ProjectSidebar />
      <main className="flex-1 flex flex-col overflow-hidden bg-bg-000">
        {activeModuleDashboard
          ? <ModuleDashboardView moduleName={activeModuleDashboard} />
          : <ChatInterface />}
      </main>
      <ArtifactViewer />

      <ApprovalDialog />
      <AskUserDialog />
      <PlanApprovalDialog />
      <CommandPalette
        isOpen={commandPaletteOpen}
        onClose={closeCommandPalette}
        onOpenStatus={openStatusDialog}
      />
      <StatusDialog isOpen={statusDialogOpen} onClose={closeStatusDialog} />
    </div>
  );
}
