/**
 * Shared form fields/chrome for MCP server modals.
 * Used by both Add and Edit MCP server modals to remove duplication.
 */

import { XMarkIcon } from '@heroicons/react/24/outline';

interface ModalHeaderProps {
  title: string;
  subtitle?: string;
  onClose: () => void;
  disabled: boolean;
}

export function ModalHeader({ title, subtitle, onClose, disabled }: ModalHeaderProps) {
  return (
    <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
      <div>
        <h2 className="text-xl font-semibold text-gray-900">{title}</h2>
        {subtitle && <p className="text-sm text-gray-500 mt-0.5">{subtitle}</p>}
      </div>
      <button
        aria-label="Close dialog"
        type="button"
        onClick={onClose}
        disabled={disabled}
        className="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors disabled:opacity-50"
      >
        <XMarkIcon className="w-5 h-5" />
      </button>
    </div>
  );
}

interface ModalFooterProps {
  onClose: () => void;
  onSubmit: (e: React.FormEvent) => void;
  isSubmitting: boolean;
  submitLabel: string;
  submittingLabel?: string;
  showSubmit?: boolean;
}

export function ModalFooter({
  onClose,
  onSubmit,
  isSubmitting,
  submitLabel,
  submittingLabel = 'Saving...',
  showSubmit = true,
}: ModalFooterProps) {
  return (
    <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-gray-200 bg-gray-50">
      <button
        type="button"
        onClick={onClose}
        disabled={isSubmitting}
        className="px-4 py-2 text-sm font-medium text-gray-700 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors disabled:opacity-50"
      >
        Cancel
      </button>
      {showSubmit && (
        <button
          type="submit"
          onClick={onSubmit}
          disabled={isSubmitting}
          className="px-4 py-2 text-sm font-medium text-white bg-gray-900 hover:bg-gray-800 active:scale-[0.98] whitespace-nowrap rounded-lg transition-colors disabled:opacity-50"
        >
          {isSubmitting ? submittingLabel : submitLabel}
        </button>
      )}
    </div>
  );
}

export function ErrorMessage({ message }: { message: string }) {
  return (
    <div className="px-4 py-3 bg-red-50 border border-semantic-danger rounded-lg mb-4">
      <p className="text-sm text-semantic-danger">{message}</p>
    </div>
  );
}

interface TextFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  required?: boolean;
  disabled?: boolean;
}

export function TextField({ label, value, onChange, placeholder, required, disabled }: TextFieldProps) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1">
        {label}
        {required && <span className="text-semantic-danger ml-1">*</span>}
      </label>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        required={required}
        disabled={disabled}
        className="w-full px-3 py-2 border border-gray-300 rounded-lg disabled:bg-gray-50 disabled:text-gray-500"
      />
    </div>
  );
}

interface CheckboxFieldProps {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
}

export function CheckboxField({ label, checked, onChange, disabled }: CheckboxFieldProps) {
  return (
    <label className="flex items-center gap-2 cursor-pointer">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        disabled={disabled}
        className="w-4 h-4 text-gray-900 border-gray-300 rounded disabled:opacity-50"
      />
      <span className="text-sm text-gray-700">{label}</span>
    </label>
  );
}

interface ArgumentsListProps {
  args: string[];
  argInput: string;
  onArgInputChange: (value: string) => void;
  onAddArg: () => void;
  onRemoveArg: (index: number) => void;
  disabled?: boolean;
}

export function ArgumentsList({
  args,
  argInput,
  onArgInputChange,
  onAddArg,
  onRemoveArg,
  disabled,
}: ArgumentsListProps) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1">Arguments</label>
      <div className="space-y-2">
        {args.map((arg, index) => (
          <div key={index} className="flex items-center gap-2">
            <input
              type="text"
              value={arg}
              readOnly
              className="flex-1 px-3 py-2 border border-gray-300 rounded-lg bg-gray-50 text-gray-700 font-mono text-sm"
            />
            <button
              type="button"
              onClick={() => onRemoveArg(index)}
              disabled={disabled}
              className="p-2 text-semantic-danger hover:bg-red-50 rounded-lg transition-colors disabled:opacity-50"
            >
              <XMarkIcon className="w-4 h-4" />
            </button>
          </div>
        ))}
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={argInput}
            onChange={(e) => onArgInputChange(e.target.value)}
            onKeyPress={(e) => e.key === 'Enter' && (e.preventDefault(), onAddArg())}
            placeholder="Add argument..."
            disabled={disabled}
            className="flex-1 px-3 py-2 border border-gray-300 rounded-lg disabled:bg-gray-50"
          />
          <button
            type="button"
            onClick={onAddArg}
            disabled={disabled || !argInput.trim()}
            className="px-3 py-2 text-sm font-medium text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors disabled:opacity-50"
          >
            Add
          </button>
        </div>
      </div>
    </div>
  );
}

interface EnvironmentVariablesProps {
  env: Record<string, string>;
  envKey: string;
  envValue: string;
  onEnvKeyChange: (value: string) => void;
  onEnvValueChange: (value: string) => void;
  onAddEnv: () => void;
  onRemoveEnv: (key: string) => void;
  disabled?: boolean;
}

export function EnvironmentVariables({
  env,
  envKey,
  envValue,
  onEnvKeyChange,
  onEnvValueChange,
  onAddEnv,
  onRemoveEnv,
  disabled,
}: EnvironmentVariablesProps) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1">Environment Variables</label>
      <div className="space-y-2">
        {Object.entries(env).map(([key, value]) => (
          <div key={key} className="flex items-center gap-2">
            <span className="px-3 py-2 bg-gray-50 border border-gray-300 rounded-lg text-sm font-mono text-gray-700">
              {key}
            </span>
            <span className="text-gray-400">=</span>
            <input
              type="text"
              value={value}
              readOnly
              className="flex-1 px-3 py-2 border border-gray-300 rounded-lg bg-gray-50 text-gray-700 font-mono text-sm"
            />
            <button
              type="button"
              onClick={() => onRemoveEnv(key)}
              disabled={disabled}
              className="p-2 text-semantic-danger hover:bg-red-50 rounded-lg transition-colors disabled:opacity-50"
            >
              <XMarkIcon className="w-4 h-4" />
            </button>
          </div>
        ))}
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={envKey}
            onChange={(e) => onEnvKeyChange(e.target.value)}
            placeholder="KEY"
            disabled={disabled}
            className="w-32 px-3 py-2 border border-gray-300 rounded-lg font-mono text-sm disabled:bg-gray-50"
          />
          <span className="text-gray-400">=</span>
          <input
            type="text"
            value={envValue}
            onChange={(e) => onEnvValueChange(e.target.value)}
            onKeyPress={(e) => e.key === 'Enter' && (e.preventDefault(), onAddEnv())}
            placeholder="value"
            disabled={disabled}
            className="flex-1 px-3 py-2 border border-gray-300 rounded-lg font-mono text-sm disabled:bg-gray-50"
          />
          <button
            type="button"
            onClick={onAddEnv}
            disabled={disabled || !envKey.trim() || !envValue.trim()}
            className="px-3 py-2 text-sm font-medium text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors disabled:opacity-50"
          >
            Add
          </button>
        </div>
      </div>
    </div>
  );
}
