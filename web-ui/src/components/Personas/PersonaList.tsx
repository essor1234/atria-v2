interface Persona {
  name: string;
  system_prompt: string;
  is_built_in: boolean;
  created_at: string;
}

interface PersonaListProps {
  personas: Persona[];
  selectedPersona: Persona | null;
  onSelect: (persona: Persona) => void;
}

export function PersonaList({
  personas,
  selectedPersona,
  onSelect,
}: PersonaListProps) {
  return (
    <div className="flex-1 overflow-y-auto divide-y divide-hairline">
      {personas.length === 0 ? (
        <div className="p-4 text-center text-ink/50 text-sm">
          No personas yet. Create one to get started.
        </div>
      ) : (
        personas.map((persona) => (
          <button
            key={persona.name}
            onClick={() => onSelect(persona)}
            className={`w-full px-4 py-3 text-left text-sm transition-colors ${
              selectedPersona?.name === persona.name
                ? 'bg-ink/5 text-ink font-medium'
                : 'text-ink hover:bg-surface-soft'
            }`}
          >
            <div className="truncate font-medium">{persona.name}</div>
            <div className="text-xs text-ink/50 truncate mt-1">{persona.system_prompt.substring(0, 50)}...</div>
          </button>
        ))
      )}
    </div>
  );
}
