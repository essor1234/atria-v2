/**
 * MCP Tools Browser Modal - Master-Detail Layout
 *
 * Elegant modal for browsing MCP server tools with detailed parameter information.
 * Uses a master-detail pattern for optimal information architecture.
 */

import { useState, useMemo, useEffect } from 'react';
import { useCopyToClipboard } from 'usehooks-ts';
import { XMarkIcon, MagnifyingGlassIcon, ClipboardIcon, CheckIcon } from '@heroicons/react/24/outline';
import { WrenchScrewdriverIcon } from '@heroicons/react/24/solid';
import { Search } from 'lucide-react';
import type { MCPTool } from '../../types/mcp';

interface MCPToolsModalProps {
  isOpen: boolean;
  serverName: string;
  tools: MCPTool[];
  onClose: () => void;
}

export function MCPToolsModal({ isOpen, serverName, tools, onClose }: MCPToolsModalProps) {
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedTool, setSelectedTool] = useState<MCPTool | null>(null);
  const [copiedText, setCopiedText] = useState<string | null>(null);
  const [, copyToClipboard] = useCopyToClipboard();

  // Reset state when modal opens or tools change
  useEffect(() => {
    if (isOpen) {
      setSearchQuery('');
      setSelectedTool(tools[0] || null);
      setCopiedText(null);
    }
  }, [isOpen, tools]);

  // Filter tools based on search query
  const filteredTools = useMemo(() => {
    if (!searchQuery.trim()) return tools;

    const query = searchQuery.toLowerCase();
    return tools.filter(
      tool =>
        tool.name.toLowerCase().includes(query) ||
        tool.description.toLowerCase().includes(query)
    );
  }, [tools, searchQuery]);

  // Auto-select first tool when filtered list changes
  useMemo(() => {
    if (filteredTools.length > 0 && !filteredTools.find(t => t.name === selectedTool?.name)) {
      setSelectedTool(filteredTools[0]);
    } else if (filteredTools.length === 0) {
      setSelectedTool(null);
    }
  }, [filteredTools, selectedTool]);

  if (!isOpen) return null;

  const handleCopy = async (text: string) => {
    const ok = await copyToClipboard(text);
    if (!ok) return;
    setCopiedText(text);
    setTimeout(() => setCopiedText(null), 2000);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm animate-fade-in">
      <div className="bg-canvas rounded-2xl shadow-modal w-full max-w-content h-[85vh] flex flex-col overflow-hidden animate-slide-up">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-hairline-soft bg-gradient-to-r from-gray-50 to-white">
          <div>
            <h2 className="text-xl font-semibold text-ink">
              Tools from {serverName}
            </h2>
            <p className="text-sm text-text-muted mt-0.5">
              {filteredTools.length} {filteredTools.length === 1 ? 'tool' : 'tools'} available
            </p>
          </div>
          <button
            aria-label="Close dialog"
            onClick={onClose}
            className="p-2 text-text-muted hover:text-text-secondary hover:bg-surface-soft rounded-lg transition-colors"
          >
            <XMarkIcon className="w-5 h-5" />
          </button>
        </div>

        {/* Search Bar */}
        <div className="px-6 py-3 border-b border-hairline-soft bg-surface-soft">
          <div className="relative">
            <MagnifyingGlassIcon className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-text-muted" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search tools by name or description..."
              className="w-full pl-10 pr-4 py-2.5 border border-hairline-soft rounded-lg bg-canvas"
            />
          </div>
        </div>

        {/* Master-Detail Layout */}
        <div className="flex-1 flex overflow-hidden">
          {/* Master: Tools List (Left Sidebar) */}
          <div className="w-80 border-r border-hairline-soft bg-surface-soft overflow-y-auto">
            {filteredTools.length === 0 ? (
              <EmptyState searchQuery={searchQuery} />
            ) : (
              <div className="p-2">
                {filteredTools.map((tool) => (
                  <ToolListItem
                    key={tool.name}
                    tool={tool}
                    isSelected={selectedTool?.name === tool.name}
                    onClick={() => setSelectedTool(tool)}
                  />
                ))}
              </div>
            )}
          </div>

          {/* Detail: Tool Details (Right Panel) */}
          <div className="flex-1 overflow-y-auto bg-canvas">
            {selectedTool ? (
              <ToolDetails
                tool={selectedTool}
                serverName={serverName}
                copiedText={copiedText}
                onCopy={handleCopy}
              />
            ) : (
              <div className="flex items-center justify-center h-full text-text-muted">
                <div className="text-center">
                  <WrenchScrewdriverIcon className="w-16 h-16 mx-auto mb-3 opacity-20" />
                  <p className="text-sm">Select a tool to view details</p>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ============================================================================
// Sub-components
// ============================================================================

interface EmptyStateProps {
  searchQuery: string;
}

function EmptyState({ searchQuery }: EmptyStateProps) {
  return (
    <div className="text-center py-12 px-4">
      <div className="text-text-muted mb-2">
        <Search className="w-12 h-12 mx-auto" />
      </div>
      <p className="text-sm text-text-secondary font-medium mb-1">
        {searchQuery ? 'No tools found' : 'No tools available'}
      </p>
      {searchQuery && (
        <p className="text-xs text-text-muted">
          Try a different search term
        </p>
      )}
    </div>
  );
}

interface ToolListItemProps {
  tool: MCPTool;
  isSelected: boolean;
  onClick: () => void;
}

function ToolListItem({ tool, isSelected, onClick }: ToolListItemProps) {
  const paramCount = tool.inputSchema?.properties ? Object.keys(tool.inputSchema.properties).length : 0;

  return (
    <button
      onClick={onClick}
      className={`w-full text-left p-3 rounded-lg transition-all ${
        isSelected
          ? 'bg-surface-soft shadow-soft border border-hairline-soft'
          : 'hover:bg-surface-soft border border-transparent'
      }`}
    >
      <div className="flex items-start gap-2">
        <WrenchScrewdriverIcon className={`w-4 h-4 mt-0.5 flex-shrink-0 ${
          isSelected ? 'text-ink' : 'text-text-muted'
        }`} />
        <div className="flex-1 min-w-0">
          <h4 className={`text-sm font-medium truncate ${
            isSelected ? 'text-ink' : 'text-text-secondary'
          }`}>
            {tool.name}
          </h4>
          <p className="text-xs text-text-muted mt-0.5 line-clamp-2">
            {tool.description}
          </p>
          {paramCount > 0 && (
            <div className="mt-1.5">
              <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-surface-soft text-text-secondary">
                {paramCount} {paramCount === 1 ? 'parameter' : 'parameters'}
              </span>
            </div>
          )}
        </div>
      </div>
    </button>
  );
}

interface ToolDetailsProps {
  tool: MCPTool;
  serverName: string;
  copiedText: string | null;
  onCopy: (text: string) => void;
}

function ToolDetails({ tool, serverName, copiedText, onCopy }: ToolDetailsProps) {
  const fullName = `mcp__${serverName}__${tool.name}`;
  const properties = tool.inputSchema?.properties || {};
  const required = tool.inputSchema?.required || [];
  const hasParameters = Object.keys(properties).length > 0;

  return (
    <div className="p-6">
      {/* Tool Header */}
      <div className="mb-6">
        <div className="flex items-start gap-3 mb-3">
          <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-gray-700 to-gray-900 flex items-center justify-center shadow-soft flex-shrink-0">
            <WrenchScrewdriverIcon className="w-5 h-5 text-white" />
          </div>
          <div className="flex-1">
            <h3 className="text-xl font-semibold text-ink">{tool.name}</h3>
            <p className="text-sm text-text-secondary mt-1 leading-relaxed">{tool.description}</p>
          </div>
        </div>

        {/* Full Tool Name */}
        <div className="mt-4">
          <label className="block text-xs font-medium text-text-muted mb-1.5">Full Tool Name</label>
          <div className="flex items-center gap-2">
            <code className="flex-1 px-3 py-2.5 bg-surface-soft border border-hairline-soft rounded-lg text-sm font-mono text-ink">
              {fullName}
            </code>
            <button
              onClick={() => onCopy(fullName)}
              className="p-2.5 text-text-secondary hover:text-ink hover:bg-surface-soft rounded-lg transition-colors border border-hairline-soft"
              title="Copy to clipboard"
            >
              {copiedText === fullName ? (
                <CheckIcon className="w-4 h-4 text-green-600" />
              ) : (
                <ClipboardIcon className="w-4 h-4" />
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Parameters Section */}
      <div className="border-t border-hairline-soft pt-6">
        <h4 className="text-sm font-semibold text-ink mb-4">Parameters</h4>

        {!hasParameters ? (
          <div className="text-center py-8 bg-surface-soft rounded-lg border border-hairline-soft">
            <p className="text-sm text-text-muted">This tool doesn't require any parameters</p>
          </div>
        ) : (
          <div className="space-y-4">
            {Object.entries(properties).map(([paramName, paramSchema]) => (
              <ParameterCard
                key={paramName}
                name={paramName}
                schema={paramSchema}
                isRequired={required.includes(paramName)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

interface ParameterCardProps {
  name: string;
  schema: any;
  isRequired: boolean;
}

function ParameterCard({ name, schema, isRequired }: ParameterCardProps) {
  const getTypeDisplay = (schema: any): string => {
    if (schema.enum) {
      return `enum: ${schema.enum.join(' | ')}`;
    }
    if (schema.type === 'array') {
      const itemType = schema.items?.type || 'any';
      return `array<${itemType}>`;
    }
    return schema.type || 'any';
  };

  return (
    <div className="bg-canvas border border-hairline-soft rounded-lg p-4 hover:border-hairline transition-colors">
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-2">
          <code className="text-sm font-semibold text-ink">{name}</code>
          {isRequired && (
            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-red-100 text-semantic-danger">
              Required
            </span>
          )}
        </div>
        <span className="text-xs font-mono text-text-muted bg-surface-soft px-2 py-1 rounded">
          {getTypeDisplay(schema)}
        </span>
      </div>

      {schema.description && (
        <p className="text-sm text-text-secondary leading-relaxed">{schema.description}</p>
      )}

      {schema.enum && (
        <div className="mt-2 pt-2 border-t border-hairline-soft">
          <p className="text-xs text-text-muted mb-1">Allowed values:</p>
          <div className="flex flex-wrap gap-1">
            {schema.enum.map((value: string) => (
              <code key={value} className="text-xs bg-surface-soft text-text-secondary px-2 py-0.5 rounded">
                {value}
              </code>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
