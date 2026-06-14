interface Persona {
  name: string;
  system_prompt: string;
  is_built_in: boolean;
  created_at: string;
}

interface PersonaPreviewProps {
  persona: Persona;
}

export function PersonaPreview({ persona }: PersonaPreviewProps) {
  return (
    <div className="p-6 space-y-4">
      <div>
        <h4 className="text-xs font-medium text-ink/50 uppercase mb-1">Name</h4>
        <p className="text-sm text-ink">{persona.name}</p>
      </div>
      <div>
        <h4 className="text-xs font-medium text-ink/50 uppercase mb-2">System Prompt</h4>
        <pre className="text-xs bg-surface-soft p-3 rounded-lg overflow-auto max-h-64 text-ink whitespace-pre-wrap">
          {persona.system_prompt}
        </pre>
      </div>
    </div>
  );
}
