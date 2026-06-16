import { useState, useEffect } from 'react';
import type { Persona } from '../../types';

interface PersonaFormProps {
  persona: Persona | null;
  onSave: (persona: Persona) => void;
  onCancel: () => void;
}

export function PersonaForm({ persona, onSave, onCancel }: PersonaFormProps) {
  const [name, setName] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('');

  useEffect(() => {
    if (persona) {
      setName(persona.name);
      setSystemPrompt(persona.system_prompt || '');
    } else {
      setName('');
      setSystemPrompt('');
    }
  }, [persona]);

  const handleSave = () => {
    if (!name.trim()) {
      alert('Please enter a persona name');
      return;
    }
    if (!systemPrompt.trim()) {
      alert('Please enter a system prompt');
      return;
    }

    const savedPersona: Persona = {
      name: name.trim(),
      system_prompt: systemPrompt.trim(),
      is_built_in: false,
      created_at: persona?.created_at || new Date().toISOString(),
    };

    onSave(savedPersona);
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto p-6">
        <div className="space-y-5">
          {/* Persona Name */}
          <div>
            <label className="block text-xs font-semibold text-ink/60 uppercase tracking-wide mb-2">
              Persona Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., Code Expert, Creative Writer"
              className="w-full px-3 py-2 border border-hairline rounded-lg bg-canvas text-ink placeholder:text-ink/40"
            />
          </div>

          {/* System Prompt */}
          <div>
            <label className="block text-xs font-semibold text-ink/60 uppercase tracking-wide mb-2">
              System Prompt
            </label>
            <textarea
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              placeholder="Enter custom system prompt for this persona..."
              className="w-full px-3 py-2 border border-hairline rounded-lg bg-canvas text-ink resize-none font-mono text-xs leading-relaxed placeholder:text-ink/40"
              rows={10}
            />
          </div>
        </div>
      </div>

      {/* Save/Cancel buttons - sticky at bottom */}
      <div className="border-t border-hairline bg-surface-soft px-6 py-3 flex gap-3 rounded-b-lg">
        <button
          onClick={handleSave}
          className="flex-1 px-4 py-2 bg-ink text-inverse-ink rounded-full hover:bg-ink/90 active:scale-[0.98] font-medium text-sm transition-all whitespace-nowrap"
        >
          Save
        </button>
        <button
          onClick={onCancel}
          className="flex-1 px-4 py-2 border border-hairline text-ink rounded-full hover:bg-canvas active:scale-[0.98] font-medium text-sm transition-all whitespace-nowrap"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
