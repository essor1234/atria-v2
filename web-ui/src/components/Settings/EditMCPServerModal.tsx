/**
 * Edit MCP Server Modal
 *
 * Modal for editing existing MCP server configurations.
 * Reuses shared form fields from mcpFormFields.
 */

import { useState, useEffect } from 'react';
import type { MCPServer, MCPServerUpdateRequest } from '../../types/mcp';
import {
  ModalHeader,
  ModalFooter,
  ErrorMessage,
  TextField,
  CheckboxField,
  ArgumentsList,
  EnvironmentVariables,
} from './mcpFormFields';

interface EditMCPServerModalProps {
  isOpen: boolean;
  server: MCPServer | null;
  onClose: () => void;
  onSubmit: (name: string, update: MCPServerUpdateRequest) => Promise<void>;
}

interface FormData {
  command: string;
  args: string[];
  env: Record<string, string>;
  enabled: boolean;
  auto_start: boolean;
}

export function EditMCPServerModal({ isOpen, server, onClose, onSubmit }: EditMCPServerModalProps) {
  const [formData, setFormData] = useState<FormData | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [argInput, setArgInput] = useState('');
  const [envKey, setEnvKey] = useState('');
  const [envValue, setEnvValue] = useState('');

  useEffect(() => {
    if (server) {
      setFormData({
        command: server.config.command,
        args: [...server.config.args],
        env: { ...server.config.env },
        enabled: server.config.enabled,
        auto_start: server.config.auto_start,
      });
    }
  }, [server]);

  if (!isOpen || !server || !formData) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!formData.command.trim()) {
      setError('Command is required');
      return;
    }

    setIsSubmitting(true);
    try {
      await onSubmit(server.name, {
        command: formData.command.trim(),
        args: formData.args.filter(arg => arg.trim()),
        env: formData.env,
        enabled: formData.enabled,
        auto_start: formData.auto_start,
      });

      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update server');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleClose = () => {
    if (!isSubmitting) {
      setArgInput('');
      setEnvKey('');
      setEnvValue('');
      setError(null);
      onClose();
    }
  };

  const addArg = () => {
    if (argInput.trim()) {
      setFormData(prev => prev ? ({ ...prev, args: [...prev.args, argInput.trim()] }) : null);
      setArgInput('');
    }
  };

  const removeArg = (index: number) => {
    setFormData(prev => prev ? ({ ...prev, args: prev.args.filter((_, i) => i !== index) }) : null);
  };

  const addEnvVar = () => {
    if (envKey.trim() && envValue.trim()) {
      setFormData(prev => prev ? ({
        ...prev,
        env: { ...prev.env, [envKey.trim()]: envValue.trim() },
      }) : null);
      setEnvKey('');
      setEnvValue('');
    }
  };

  const removeEnvVar = (key: string) => {
    setFormData(prev => {
      if (!prev) return null;
      const newEnv = { ...prev.env };
      delete newEnv[key];
      return { ...prev, env: newEnv };
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm animate-fade-in">
      <div className="bg-white rounded-2xl shadow-modal w-full max-w-2xl max-h-[85vh] flex flex-col overflow-hidden animate-slide-up">
        <ModalHeader
          title="Edit MCP Server"
          subtitle={server.name}
          onClose={handleClose}
          disabled={isSubmitting}
        />

        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto p-6">
          <div className="space-y-4">
            {error && <ErrorMessage message={error} />}

            <TextField
              label="Command"
              value={formData.command}
              onChange={(value) => setFormData(prev => prev ? ({ ...prev, command: value }) : null)}
              required
              disabled={isSubmitting}
            />

            <ArgumentsList
              args={formData.args}
              argInput={argInput}
              onArgInputChange={setArgInput}
              onAddArg={addArg}
              onRemoveArg={removeArg}
              disabled={isSubmitting}
            />

            <EnvironmentVariables
              env={formData.env}
              envKey={envKey}
              envValue={envValue}
              onEnvKeyChange={setEnvKey}
              onEnvValueChange={setEnvValue}
              onAddEnv={addEnvVar}
              onRemoveEnv={removeEnvVar}
              disabled={isSubmitting}
            />

            <CheckboxField
              label="Enable auto-start on launch"
              checked={formData.auto_start}
              onChange={(checked) => setFormData(prev => prev ? ({ ...prev, auto_start: checked }) : null)}
              disabled={isSubmitting}
            />

            <CheckboxField
              label="Enable this server"
              checked={formData.enabled}
              onChange={(checked) => setFormData(prev => prev ? ({ ...prev, enabled: checked }) : null)}
              disabled={isSubmitting}
            />
          </div>
        </form>

        <ModalFooter
          onClose={handleClose}
          onSubmit={handleSubmit}
          isSubmitting={isSubmitting}
          submitLabel="Save Changes"
          submittingLabel="Saving..."
        />
      </div>
    </div>
  );
}
