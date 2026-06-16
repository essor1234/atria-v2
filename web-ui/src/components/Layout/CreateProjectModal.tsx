import { useProjectsStore } from '../../stores/projects';
import { NameInputModal } from './NameInputModal';

interface Props {
  isOpen: boolean;
  onClose: () => void;
}

export function CreateProjectModal({ isOpen, onClose }: Props) {
  const createProject = useProjectsStore(state => state.createProject);
  return (
    <NameInputModal
      isOpen={isOpen}
      onClose={onClose}
      title="New Project"
      inputLabel="Project name"
      placeholder="e.g. FPT Research, My App"
      submitLabel="Create"
      emptyError="Project name is required"
      onSubmit={createProject}
    >
      {(name) => {
        const slug = name.trim().toLowerCase().replace(/\s+/g, '-') || '<name>';
        return (
          <p className="text-xs text-text-400">
            Folder: <code className="font-mono text-text-300">~/.atria/workspaces/…/{slug}/</code>
          </p>
        );
      }}
    </NameInputModal>
  );
}
