import { useState, useEffect } from 'react';
import { PersonaForm } from '../Personas/PersonaForm';

interface Persona {
  name: string;
  system_prompt: string;
  is_built_in: boolean;
  created_at: string;
}

export function PersonasSettings() {
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [selectedPersona, setSelectedPersona] = useState<Persona | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadPersonas();
  }, []);

  const loadPersonas = async () => {
    try {
      setIsLoading(true);
      setError(null);
      const response = await fetch('/api/personas');
      if (!response.ok) throw new Error('Failed to load personas');
      const data = await response.json();
      setPersonas(data);
      if (data.length > 0 && !selectedPersona) {
        setSelectedPersona(data[0]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setIsLoading(false);
    }
  };

  const handleSavePersona = async (persona: Persona) => {
    try {
      const isNew = !personas.find(p => p.name === persona.name);
      const method = isNew ? 'POST' : 'PUT';
      const url = isNew ? '/api/personas' : `/api/personas/${selectedPersona?.name}`;

      const response = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(persona),
      });

      if (!response.ok) throw new Error('Failed to save persona');
      const savedPersona = await response.json();

      if (isNew) {
        setPersonas([...personas, savedPersona]);
      } else {
        setPersonas(personas.map(p => p.name === persona.name ? savedPersona : p));
      }

      setSelectedPersona(savedPersona);
      setIsEditing(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save');
    }
  };

  const handleDeletePersona = async (name: string) => {
    if (!confirm(`Delete persona "${name}"?`)) return;

    try {
      const response = await fetch(`/api/personas/${name}`, { method: 'DELETE' });
      if (!response.ok) throw new Error('Failed to delete');

      setPersonas(personas.filter(p => p.name !== name));
      if (selectedPersona?.name === name) {
        setSelectedPersona(personas[0] || null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete');
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="flex items-center gap-2 text-ink/50">
          <div className="w-4 h-4 border-2 border-ink/20 border-t-ink rounded-full animate-spin" />
          <span className="text-sm">Loading personas...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-lg font-semibold text-ink">Personas</h2>
        <p className="text-sm text-ink/60 mt-1">Create and manage custom agent personalities</p>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm">
          {error}
        </div>
      )}

      <div className="grid grid-cols-3 gap-6">
        {/* Left: Personas List */}
        <div className="col-span-1 border border-hairline rounded-lg bg-canvas flex flex-col">
          <div className="bg-surface-soft px-4 py-3 border-b border-hairline flex items-center justify-between rounded-t-lg">
            <h3 className="font-medium text-ink text-sm">All Personas</h3>
            <button
              onClick={() => {
                setSelectedPersona(null);
                setIsEditing(true);
              }}
              className="px-3 py-1.5 bg-ink text-inverse-ink text-xs rounded-full hover:bg-ink/90 font-medium transition-colors"
            >
              + New
            </button>
          </div>

          <div className="flex-1 overflow-y-auto divide-y divide-hairline">
            {personas.length === 0 ? (
              <div className="p-6 text-center">
                <p className="text-sm text-ink/50">No personas yet</p>
                <p className="text-xs text-ink/40 mt-2">Click "+ New" to create one</p>
              </div>
            ) : (
              personas.map(p => (
                <button
                  key={p.name}
                  onClick={() => {
                    setSelectedPersona(p);
                    setIsEditing(false);
                  }}
                  className={`w-full px-4 py-3 text-left transition-colors ${
                    selectedPersona?.name === p.name
                      ? 'bg-ink/5 border-l-2 border-l-ink'
                      : 'hover:bg-surface-soft border-l-2 border-l-transparent'
                  }`}
                >
                  <div className="font-medium text-sm text-ink truncate">{p.name}</div>
                  <div className="text-xs text-ink/50 truncate mt-0.5">{p.system_prompt.substring(0, 40)}...</div>
                </button>
              ))
            )}
          </div>
        </div>

        {/* Right: Editor or View */}
        {(selectedPersona || isEditing) && (
          <div className="col-span-2 border border-hairline rounded-lg bg-canvas flex flex-col">
            <div className="bg-surface-soft px-4 py-3 border-b border-hairline flex items-center justify-between rounded-t-lg">
              <h3 className="font-medium text-ink text-sm">
                {isEditing ? '✏️ Edit Persona' : '👁️ View Persona'}
              </h3>
              {!isEditing && selectedPersona && (
                <button
                  onClick={() => handleDeletePersona(selectedPersona.name)}
                  className="px-3 py-1.5 text-red-600 text-xs rounded-full hover:bg-red-50 font-medium transition-colors border border-red-200"
                >
                  Delete
                </button>
              )}
            </div>

            <div className="flex-1 overflow-y-auto">
              {isEditing ? (
                <PersonaForm
                  persona={selectedPersona}
                  onSave={handleSavePersona}
                  onCancel={() => setIsEditing(false)}
                />
              ) : selectedPersona ? (
                <div className="p-6 space-y-6">
                  <div>
                    <h4 className="text-xs font-semibold text-ink/60 uppercase tracking-wide mb-2">Name</h4>
                    <p className="text-base font-medium text-ink">{selectedPersona.name}</p>
                  </div>
                  <div>
                    <h4 className="text-xs font-semibold text-ink/60 uppercase tracking-wide mb-3">System Prompt</h4>
                    <div className="bg-surface-soft border border-hairline rounded-lg p-4 overflow-auto max-h-96">
                      <pre className="text-xs text-ink whitespace-pre-wrap font-mono leading-relaxed">
                        {selectedPersona.system_prompt}
                      </pre>
                    </div>
                  </div>
                  <button
                    onClick={() => setIsEditing(true)}
                    className="w-full px-4 py-2 bg-ink text-inverse-ink rounded-full hover:bg-ink/90 font-medium text-sm transition-colors"
                  >
                    Edit Persona
                  </button>
                </div>
              ) : null}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
