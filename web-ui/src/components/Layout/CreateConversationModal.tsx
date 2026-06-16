import { useProjectsStore } from '../../stores/projects';
import { NameInputModal } from './NameInputModal';

interface Props {
  isOpen: boolean;
  projectId: string;
  projectName: string;
  onClose: () => void;
}

export function CreateConversationModal({ isOpen, projectId, projectName, onClose }: Props) {
  const createConversation = useProjectsStore(state => state.createConversation);
  return (
    <NameInputModal
      isOpen={isOpen}
      onClose={onClose}
      title="New Conversation"
      subtitle={<>in <span className="text-text-200">{projectName}</span></>}
      inputLabel="Conversation name"
      placeholder="e.g. Initial Research, Q1 Analysis"
      submitLabel="Start Conversation"
      emptyError="Conversation name is required"
      onSubmit={(name) => createConversation(projectId, name)}
    />
  );
}
