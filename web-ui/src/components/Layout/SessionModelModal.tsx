import { useState, useEffect } from 'react';
import { X } from 'lucide-react';
import { createPortal } from 'react-dom';
import { apiClient } from '../../api/client';
import { useToastStore } from '../../stores/toast';

interface SessionModelModalProps {
  sessionId: string | null;
  sessionLabel: string;
  onClose: () => void;
}

function ModelInput({
  label,
  value,
  onChange,
  placeholder,
  optional,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  optional?: boolean;
}) {
  return (
    <div>
      <div className="flex items-center gap-2 mb-1">
        <label className="text-xs font-medium text-text-secondary">{label}</label>
        {optional && (
          <span className="text-xs px-1.5 py-0.5 bg-surface-soft text-text-muted rounded">optional</span>
        )}
      </div>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full px-3 py-2 text-sm border border-hairline-soft rounded-lg bg-canvas font-mono"
      />
    </div>
  );
}

export function SessionModelModal({ sessionId, sessionLabel, onClose }: SessionModelModalProps) {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [hasExistingOverlay, setHasExistingOverlay] = useState(false);
  const addToast = useToastStore(state => state.addToast);

  const [normalModel, setNormalModel] = useState('');
  const [thinkingModel, setThinkingModel] = useState('');
  const [critiqueModel, setCritiqueModel] = useState('');
  const [compactModel, setCompactModel] = useState('');
  const [visionModel, setVisionModel] = useState('');

  useEffect(() => {
    if (sessionId) loadData();
  }, [sessionId]);

  const loadData = async () => {
    if (!sessionId) return;
    try {
      setLoading(true);
      const [configData, overlayData] = await Promise.all([
        apiClient.getConfig(),
        apiClient.getSessionModel(sessionId),
      ]);

      setHasExistingOverlay(Object.keys(overlayData).length > 0);
      setNormalModel(overlayData.model || configData.model || '');
      setThinkingModel(overlayData.model_thinking || configData.model_thinking || '');
      setCritiqueModel(overlayData.model_critique || configData.model_critique || '');
      setCompactModel(overlayData.model_compact || configData.model_compact || '');
      setVisionModel(overlayData.model_vlm || configData.model_vlm || '');
    } catch (error) {
      console.error('Failed to load session model data:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    if (!sessionId) return;
    try {
      setSaving(true);
      await apiClient.updateSessionModel(sessionId, {
        model: normalModel || null,
        model_thinking: thinkingModel || null,
        model_critique: critiqueModel || null,
        model_compact: compactModel || null,
        model_vlm: visionModel || null,
      });
      setHasExistingOverlay(true);
      addToast('Session model updated', 'success');
      onClose();
    } catch (error) {
      console.error('Failed to save session model:', error);
      addToast('Failed to save session model', 'error');
    } finally {
      setSaving(false);
    }
  };

  const handleClear = async () => {
    if (!sessionId) return;
    try {
      setSaving(true);
      await apiClient.clearSessionModel(sessionId);
      setHasExistingOverlay(false);
      const configData = await apiClient.getConfig();
      setNormalModel(configData.model || '');
      setThinkingModel(configData.model_thinking || '');
      setCritiqueModel(configData.model_critique || '');
      setCompactModel(configData.model_compact || '');
      setVisionModel(configData.model_vlm || '');
      addToast('Session model cleared', 'success');
      onClose();
    } catch (error) {
      console.error('Failed to clear session model:', error);
      addToast('Failed to clear session model', 'error');
    } finally {
      setSaving(false);
    }
  };

  if (!sessionId) return null;

  const modalContent = (
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/50 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="bg-canvas rounded-2xl shadow-modal w-full max-w-lg max-h-[90vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-6 py-4 border-b border-hairline-soft flex-shrink-0">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-bold text-ink">Session Models</h2>
              <p className="text-xs text-text-muted mt-0.5">{sessionLabel}</p>
            </div>
            <button
              aria-label="Close dialog"
              onClick={onClose}
              className="w-8 h-8 rounded-lg flex items-center justify-center hover:bg-surface-soft text-text-muted hover:text-text-secondary"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
          <div className="mt-3 px-3 py-2 bg-amber-50 border border-amber-200 rounded-lg">
            <p className="text-xs text-amber-800">
              Override models for this session only. Changes don't affect global settings.
            </p>
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <div className="flex items-center gap-2 text-text-secondary">
                <div className="w-4 h-4 border-2 border-hairline-soft border-t-gray-600 rounded-full animate-spin" />
                <span className="text-sm">Loading...</span>
              </div>
            </div>
          ) : (
            <>
              <ModelInput label="Normal Model" value={normalModel} onChange={setNormalModel} placeholder="gpt-4o" />
              <ModelInput label="Thinking Model" value={thinkingModel} onChange={setThinkingModel} placeholder="o3-mini" optional />
              <ModelInput label="Critique Model" value={critiqueModel} onChange={setCritiqueModel} optional />
              <ModelInput label="Compact Model" value={compactModel} onChange={setCompactModel} optional />
              <ModelInput label="Vision Model" value={visionModel} onChange={setVisionModel} optional />
            </>
          )}
        </div>

        {/* Footer */}
        {!loading && (
          <div className="px-6 py-4 border-t border-hairline-soft flex-shrink-0 space-y-3">
            <div className="flex gap-3">
              {hasExistingOverlay && (
                <button
                  onClick={handleClear}
                  disabled={saving}
                  className="px-4 py-2.5 border border-semantic-danger/40 text-semantic-danger rounded-lg hover:bg-semantic-danger/10 disabled:opacity-50 disabled:cursor-not-allowed font-medium text-sm"
                >
                  Clear Overrides
                </button>
              )}
              <button
                onClick={handleSave}
                disabled={saving}
                className="flex-1 px-4 py-2.5 bg-gradient-to-r from-amber-500 to-orange-600 hover:from-amber-600 hover:to-orange-700 text-white rounded-lg disabled:opacity-50 disabled:cursor-not-allowed font-medium text-sm shadow-soft hover:shadow-hover"
              >
                {saving ? (
                  <span className="flex items-center justify-center gap-2">
                    <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                    Saving...
                  </span>
                ) : 'Save'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );

  return createPortal(modalContent, document.body);
}
