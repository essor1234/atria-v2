import { useState, useCallback } from 'react';
import { TopBar } from '../components/Layout/TopBar';
import { ProjectSidebar } from '../components/Layout/ProjectSidebar';
import { ChatInterface } from '../components/Chat/ChatInterface';
import { ApprovalDialog } from '../components/ApprovalDialog';
import { AskUserDialog } from '../components/Chat/AskUserDialog';
import { PlanApprovalDialog } from '../components/Chat/PlanApprovalDialog';
import { CommandPalette } from '../components/Chat/CommandPalette';
import { StatusDialog } from '../components/Chat/StatusDialog';
import { SettingsModal } from '../components/Settings/SettingsModal';
import { ToastContainer } from '../components/ui/Toast';
import { ArtifactViewer } from '../components/ArtifactViewer/ArtifactViewer';
import { useChatStore } from '../stores/chat';

export function ChatPage() {
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [statusDialogOpen, setStatusDialogOpen] = useState(false);

  const settingsModalOpen = useChatStore(state => state.settingsModalOpen);
  const closeSettingsModal = useChatStore(state => state.closeSettingsModal);

  const openCommandPalette = useCallback(() => setCommandPaletteOpen(true), []);
  const closeCommandPalette = useCallback(() => setCommandPaletteOpen(false), []);
  const openStatusDialog = useCallback(() => setStatusDialogOpen(true), []);
  const closeStatusDialog = useCallback(() => setStatusDialogOpen(false), []);

  return (
    <div className="h-screen flex flex-col bg-bg-100">
      <TopBar onOpenCommandPalette={openCommandPalette} />
      <div className="flex-1 flex overflow-hidden">
        <ProjectSidebar />
        <main className="flex-1 flex flex-col overflow-hidden bg-bg-000">
          <ChatInterface />
        </main>
        <ArtifactViewer />
      </div>

      <ApprovalDialog />
      <AskUserDialog />
      <PlanApprovalDialog />
      <CommandPalette
        isOpen={commandPaletteOpen}
        onClose={closeCommandPalette}
        onOpenStatus={openStatusDialog}
      />
      <StatusDialog isOpen={statusDialogOpen} onClose={closeStatusDialog} />
      <SettingsModal isOpen={settingsModalOpen} onClose={closeSettingsModal} />
      <ToastContainer />
    </div>
  );
}
