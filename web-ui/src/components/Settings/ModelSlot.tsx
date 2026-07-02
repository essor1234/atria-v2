export interface Provider {
  id: string;
  name: string;
  description: string;
  models: Model[];
}

export interface Model {
  id: string;
  name: string;
  description: string;
}

export interface ModelSlotProps {
  title: string;
  description: string;
  icon: React.ReactNode;
  providers: Provider[];
  selectedProvider: string;
  selectedModel: string;
  onProviderChange: (provider: string) => void;
  onModelChange: (model: string) => void;
  optional?: boolean;
  notSetText?: string;
}

export function ModelSlot({
  title,
  description,
  icon,
  providers,
  selectedProvider,
  selectedModel,
  onProviderChange,
  onModelChange,
  optional = false,
  notSetText = "Not configured"
}: ModelSlotProps) {
  const currentProvider = providers.find(p => p.id === selectedProvider);
  const availableModels = currentProvider?.models || [];

  return (
    <div className="border border-hairline-soft rounded-lg p-4 bg-gradient-to-br from-white to-gray-50">
      {/* Header */}
      <div className="flex items-center gap-3 mb-4">
        <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center shadow-soft flex-shrink-0">
          {icon}
        </div>
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <h3 className="text-base font-semibold text-ink">{title}</h3>
            {optional && (
              <span className="text-xs px-2 py-0.5 bg-surface-soft text-text-secondary rounded-full">
                Optional
              </span>
            )}
          </div>
          <p className="text-xs text-text-secondary mt-0.5">{description}</p>
        </div>
      </div>

      {/* Provider Selection */}
      <div className="space-y-3">
        <div>
          <label className="block text-xs font-medium text-text-secondary mb-1.5">
            Provider
          </label>
          <select
            value={selectedProvider || ''}
            onChange={(e) => {
              const newProvider = e.target.value;
              onProviderChange(newProvider);
              // Reset model selection when provider changes
              const provider = providers.find(p => p.id === newProvider);
              if (provider && provider.models.length > 0) {
                onModelChange(provider.models[0].id);
              }
            }}
            className="w-full px-3 py-2 text-sm border border-hairline-soft rounded-lg bg-canvas"
          >
            {optional && (
              <option value="">{notSetText}</option>
            )}
            {providers.map(provider => (
              <option key={provider.id} value={provider.id}>
                {provider.name}
              </option>
            ))}
          </select>
        </div>

        {/* Model Selection */}
        {selectedProvider && (
          <div>
            <label className="block text-xs font-medium text-text-secondary mb-1.5">
              Model
            </label>
            <select
              value={selectedModel || ''}
              onChange={(e) => onModelChange(e.target.value)}
              className="w-full px-3 py-2 text-sm border border-hairline-soft rounded-lg bg-canvas"
              disabled={availableModels.length === 0}
            >
              {availableModels.map(model => (
                <option key={model.id} value={model.id}>
                  {model.name}
                </option>
              ))}
            </select>
            {availableModels.find(m => m.id === selectedModel) && (
              <p className="mt-1.5 text-xs text-text-muted">
                {availableModels.find(m => m.id === selectedModel)?.description}
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
