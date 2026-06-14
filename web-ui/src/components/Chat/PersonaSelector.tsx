import { useState, useEffect, useRef } from 'react';
import { User, X, ChevronDown, Settings } from 'lucide-react';
import { useChatStore } from '../../stores/chat';

interface Persona {
  name: string;
  system_prompt: string;
  is_built_in: boolean;
  created_at: string;
}

export function PersonaSelector() {
  const [open, setOpen] = useState(false);
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [fetchError, setFetchError] = useState(false);
  const cachedRef = useRef(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const selectedPersona = useChatStore(state => {
    const sid = state.currentSessionId;
    return sid ? state.sessionStates[sid]?.selectedPersona : null;
  });
  const setSelectedPersona = useChatStore(state => state.setSelectedPersona);
  const openSettingsModal = useChatStore(state => state.openSettingsModal);

  // Fetch personas once per mount (lazy, cached after first open)
  useEffect(() => {
    if (!open || cachedRef.current) return;
    cachedRef.current = true;
    fetch('/api/personas')
      .then(r => {
        if (!r.ok) throw new Error('Failed');
        return r.json();
      })
      .then((data: Persona[]) => setPersonas(data))
      .catch(() => setFetchError(true));
  }, [open]);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const handleSelect = (name: string) => {
    setSelectedPersona(name);
    setOpen(false);
  };

  const handleClear = (e: React.MouseEvent) => {
    e.stopPropagation();
    setSelectedPersona(null);
  };

  const pillBase =
    'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-medium cursor-pointer transition-colors select-none hover:scale-105';
  const pillStyle = 'bg-bg-400/40 text-text-200 border-gray-300 hover:bg-bg-400/60';

  return (
    <div ref={containerRef} className="relative flex items-center gap-2">
      <button
        onClick={() => setOpen(prev => !prev)}
        className={`${pillBase} ${pillStyle}`}
        title={selectedPersona ? `Current persona: ${selectedPersona}` : 'Select a persona'}
      >
        <User className="w-3 h-3" strokeWidth={2} />
        {selectedPersona ? (
          <>
            <span>{selectedPersona}</span>
            <button
              onClick={handleClear}
              className="ml-1 text-text-200/60 hover:text-text-200 transition-colors"
              title="Clear persona"
            >
              <X className="w-3 h-3" strokeWidth={2} />
            </button>
          </>
        ) : (
          <>
            <span>Persona</span>
            <ChevronDown className="w-3 h-3" strokeWidth={2} />
          </>
        )}
      </button>

      {open && (
        <div className="absolute bottom-full mb-2 left-0 z-50 min-w-[180px] max-h-64 overflow-y-auto rounded-lg border border-gray-300 bg-bg-300 shadow-lg py-1">
          {fetchError ? (
            <p className="px-3 py-2 text-xs text-red-400">Could not load personas</p>
          ) : personas.length === 0 ? (
            <div className="px-3 py-2 text-xs text-text-200/60">
              <p>No personas yet</p>
              <button
                onClick={() => { openSettingsModal(); setOpen(false); }}
                className="mt-1 flex items-center gap-1 text-text-200 hover:underline"
              >
                <Settings className="w-3 h-3" />
                Open Settings
              </button>
            </div>
          ) : (
            personas.map(p => (
              <button
                key={p.name}
                onClick={() => handleSelect(p.name)}
                className={`w-full text-left px-3 py-2 text-xs hover:bg-bg-400/40 transition-colors ${
                  selectedPersona === p.name ? 'text-text-100 font-semibold' : 'text-text-200'
                }`}
              >
                {p.name}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}
