/**
 * Add MCP Server Modal
 *
 * Modal for adding new MCP server configurations.
 * Supports both manual form entry and JSON import.
 */

import { useState } from 'react';
import type { MCPServerCreateRequest } from '../../types/mcp';
import {
  ModalHeader,
  ModalFooter,
  ErrorMessage,
  TextField,
  CheckboxField,
  ArgumentsList,
  EnvironmentVariables,
} from './mcpFormFields';

interface AddMCPServerModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (server: MCPServerCreateRequest) => Promise<void>;
}

interface FormData {
  name: string;
  command: string;
  args: string[];
  env: Record<string, string>;
  enabled: boolean;
  auto_start: boolean;
  project_config: boolean;
}

const initialFormData: FormData = {
  name: '',
  command: '',
  args: [],
  env: {},
  enabled: true,
  auto_start: false,
  project_config: false,
};

type InputMode = 'form' | 'json';

export function AddMCPServerModal({ isOpen, onClose, onSubmit }: AddMCPServerModalProps) {
  const [mode, setMode] = useState<InputMode>('form');
  const [formData, setFormData] = useState<FormData>(initialFormData);
  const [jsonInput, setJsonInput] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Args management
  const [argInput, setArgInput] = useState('');

  // Env management
  const [envKey, setEnvKey] = useState('');
  const [envValue, setEnvValue] = useState('');

  if (!isOpen) return null;

  const parseJSON = () => {
    try {
      const parsed = JSON.parse(jsonInput);

      // Support Claude Code format: { "mcpServers": { "name": { config } } }
      if (parsed.mcpServers) {
        const serverName = Object.keys(parsed.mcpServers)[0];
        if (!serverName) {
          setError('No server found in JSON');
          return;
        }
        const serverConfig = parsed.mcpServers[serverName];
        setFormData({
          name: serverName,
          command: serverConfig.command || '',
          args: serverConfig.args || [],
          env: serverConfig.env || {},
          enabled: serverConfig.enabled ?? true,
          auto_start: serverConfig.auto_start ?? false,
          project_config: false,
        });
        setMode('form');
        setError(null);
      }
      // Support direct server config format: { "command": "...", "args": [...] }
      else if (parsed.command) {
        setFormData({
          name: parsed.name || '',
          command: parsed.command,
          args: parsed.args || [],
          env: parsed.env || {},
          enabled: parsed.enabled ?? true,
          auto_start: parsed.auto_start ?? false,
          project_config: parsed.project_config ?? false,
        });
        setMode('form');
        setError(null);
      } else {
        setError('Invalid JSON format. Expected either Claude Code format or server config.');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Invalid JSON');
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    // Validation
    if (!formData.name.trim()) {
      setError('Server name is required');
      return;
    }

    if (!formData.command.trim()) {
      setError('Command is required');
      return;
    }

    setIsSubmitting(true);
    try {
      await onSubmit({
        name: formData.name.trim(),
        command: formData.command.trim(),
        args: formData.args.filter(arg => arg.trim()),
        env: formData.env,
        enabled: formData.enabled,
        auto_start: formData.auto_start,
        project_config: formData.project_config,
      });

      // Reset form and close
      setFormData(initialFormData);
      setJsonInput('');
      setArgInput('');
      setEnvKey('');
      setEnvValue('');
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add server');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleClose = () => {
    if (!isSubmitting) {
      setFormData(initialFormData);
      setJsonInput('');
      setArgInput('');
      setEnvKey('');
      setEnvValue('');
      setError(null);
      setMode('form');
      onClose();
    }
  };

  const addArg = () => {
    if (argInput.trim()) {
      setFormData(prev => ({
        ...prev,
        args: [...prev.args, argInput.trim()],
      }));
      setArgInput('');
    }
  };

  const removeArg = (index: number) => {
    setFormData(prev => ({
      ...prev,
      args: prev.args.filter((_, i) => i !== index),
    }));
  };

  const addEnvVar = () => {
    if (envKey.trim() && envValue.trim()) {
      setFormData(prev => ({
        ...prev,
        env: { ...prev.env, [envKey.trim()]: envValue.trim() },
      }));
      setEnvKey('');
      setEnvValue('');
    }
  };

  const removeEnvVar = (key: string) => {
    setFormData(prev => {
      const newEnv = { ...prev.env };
      delete newEnv[key];
      return { ...prev, env: newEnv };
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm animate-fade-in">
      <div className="bg-canvas rounded-2xl shadow-modal w-full max-w-2xl max-h-[85vh] flex flex-col overflow-hidden animate-slide-up">
        {/* Header */}
        <ModalHeader title="Add MCP Server" onClose={handleClose} disabled={isSubmitting} />

        {/* Mode Tabs */}
        <div className="flex border-b border-hairline-soft px-6">
          <button
            type="button"
            onClick={() => setMode('form')}
            disabled={isSubmitting}
            className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
              mode === 'form'
                ? 'border-gray-900 text-ink'
                : 'border-transparent text-text-muted hover:text-text-secondary'
            }`}
          >
            Manual Entry
          </button>
          <button
            type="button"
            onClick={() => setMode('json')}
            disabled={isSubmitting}
            className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
              mode === 'json'
                ? 'border-gray-900 text-ink'
                : 'border-transparent text-text-muted hover:text-text-secondary'
            }`}
          >
            Import JSON
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          {error && <ErrorMessage message={error} />}

          {mode === 'json' ? (
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-text-secondary mb-2">
                  Paste JSON Configuration
                </label>
                <p className="text-xs text-text-muted mb-3">
                  Paste your MCP server JSON from Claude Code format or direct server config
                </p>
                <textarea
                  value={jsonInput}
                  onChange={(e) => setJsonInput(e.target.value)}
                  placeholder={`{\n  "mcpServers": {\n    "server-name": {\n      "command": "npx",\n      "args": ["-y", "package-name"]\n    }\n  }\n}`}
                  disabled={isSubmitting}
                  rows={12}
                  className="w-full px-3 py-2 border border-hairline-soft rounded-lg font-mono text-sm disabled:bg-surface-soft"
                />
              </div>
              <button
                type="button"
                onClick={parseJSON}
                disabled={isSubmitting || !jsonInput.trim()}
                className="px-4 py-2 text-sm font-medium text-white bg-gradient-brand hover:brightness-110 active:scale-[0.98] whitespace-nowrap rounded-lg transition-colors disabled:opacity-50"
              >
                Parse and Fill Form
              </button>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              <TextField
                label="Server Name"
                value={formData.name}
                onChange={(value) => setFormData(prev => ({ ...prev, name: value }))}
                placeholder="e.g., github, filesystem"
                required
                disabled={isSubmitting}
              />

              <TextField
                label="Command"
                value={formData.command}
                onChange={(value) => setFormData(prev => ({ ...prev, command: value }))}
                placeholder="e.g., npx -y @modelcontextprotocol/server-github"
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
                onChange={(checked) => setFormData(prev => ({ ...prev, auto_start: checked }))}
                disabled={isSubmitting}
              />

              <CheckboxField
                label="Enable this server"
                checked={formData.enabled}
                onChange={(checked) => setFormData(prev => ({ ...prev, enabled: checked }))}
                disabled={isSubmitting}
              />

              <CheckboxField
                label="Save to project config (instead of global)"
                checked={formData.project_config}
                onChange={(checked) => setFormData(prev => ({ ...prev, project_config: checked }))}
                disabled={isSubmitting}
              />
            </form>
          )}
        </div>

        {/* Footer */}
        <ModalFooter
          onClose={handleClose}
          onSubmit={handleSubmit}
          isSubmitting={isSubmitting}
          submitLabel="Add Server"
          submittingLabel="Adding..."
          showSubmit={mode === 'form'}
        />
      </div>
    </div>
  );
}
