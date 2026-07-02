/**
 * Settings Modal with Vertical Sidebar Navigation
 *
 * Redesigned to use vertical tabs for better space utilization
 * and scalability as more settings categories are added.
 */

import { useState, useEffect } from 'react';
import { XMarkIcon } from '@heroicons/react/24/outline';
import {
  CpuChipIcon,
  ServerIcon,
  Cog6ToothIcon,
  SparklesIcon,
  ChatBubbleLeftRightIcon
} from '@heroicons/react/24/outline';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { ModelSettings } from './ModelSettings';
import { MCPSettings } from './MCPSettings';
import { PersonasSettings } from './PersonasSettings';
import { ChannelSettings } from './ChannelSettings';

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

type TabId = 'model' | 'mcp' | 'connect' | 'personas' | 'general';

interface TabConfig {
  id: TabId;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  description: string;
}

const tabs: TabConfig[] = [
  {
    id: 'model',
    label: 'Model',
    icon: CpuChipIcon,
    description: 'Configure AI model and provider settings'
  },
  {
    id: 'mcp',
    label: 'MCP Servers',
    icon: ServerIcon,
    description: 'Manage Model Context Protocol servers'
  },
  {
    id: 'connect',
    label: 'Connect',
    icon: ChatBubbleLeftRightIcon,
    description: 'Connect Telegram & other chat apps to the agent'
  },
  {
    id: 'personas',
    label: 'Personas',
    icon: SparklesIcon,
    description: 'Customize agent behavior and system prompts'
  },
  {
    id: 'general',
    label: 'General',
    icon: Cog6ToothIcon,
    description: 'General application settings'
  },
];

export function SettingsModal({ isOpen, onClose }: SettingsModalProps) {
  const [activeTab, setActiveTab] = useState<TabId>('model');
  const reduce = useReducedMotion();

  // Handle Escape key to close modal
  useEffect(() => {
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && isOpen) {
        onClose();
      }
    };

    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [isOpen, onClose]);

  const activeTabConfig = tabs.find(t => t.id === activeTab);

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2, ease: [0.4, 0, 0.2, 1] }}
          className="fixed inset-0 z-50 flex items-stretch sm:items-center justify-center bg-black/60 backdrop-blur-sm sm:p-4"
          onClick={onClose}
        >
          <motion.div
            initial={reduce ? { opacity: 0 } : { opacity: 0, y: 12, scale: 0.97 }}
            animate={reduce ? { opacity: 1 } : { opacity: 1, y: 0, scale: 1 }}
            exit={reduce ? { opacity: 0 } : { opacity: 0, y: 8, scale: 0.98 }}
            transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
            onClick={(e) => e.stopPropagation()}
            className="bg-canvas sm:rounded-lg shadow-modal w-full sm:max-w-content h-full sm:h-[85vh] flex flex-col overflow-hidden sm:border border-hairline-soft">
        {/* Header */}
        <div className="flex items-center justify-between px-4 sm:px-6 py-4 border-b border-hairline-soft">
          <div>
            <h2 className="text-xl font-semibold text-ink">Settings</h2>
            {activeTabConfig && (
              <p className="text-xs text-text-muted mt-0.5">{activeTabConfig.description}</p>
            )}
          </div>
          <button
            aria-label="Close dialog"
            onClick={onClose}
            className="p-2 text-text-muted hover:text-text-secondary hover:bg-surface-soft rounded-lg transition-colors"
          >
            <XMarkIcon className="w-5 h-5" />
          </button>
        </div>

        {/* Main Content Area with Sidebar (horizontal tab bar on mobile) */}
        <div className="flex-1 flex flex-col sm:flex-row overflow-hidden min-h-0">
          {/* Navigation — vertical sidebar at sm+, horizontal scroll bar on mobile */}
          <div className="flex-shrink-0 w-full sm:w-56 border-b sm:border-b-0 sm:border-r border-hairline-soft bg-surface-soft overflow-x-auto sm:overflow-y-auto">
            <nav className="flex sm:flex-col gap-1 p-2 sm:p-3">
              {tabs.map(tab => {
                const Icon = tab.icon;
                const isActive = activeTab === tab.id;

                return (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id)}
                    className={`flex-shrink-0 sm:w-full flex items-center gap-2 sm:gap-3 px-3 py-2 sm:py-2.5 rounded-lg text-left whitespace-nowrap cursor-pointer transition-colors ${
                      isActive
                        ? 'bg-surface-soft text-ink shadow-sm'
                        : 'text-text-secondary hover:bg-surface-soft hover:text-ink'
                    }`}
                  >
                    <Icon className={`w-5 h-5 flex-shrink-0 ${isActive ? 'text-ink' : 'text-text-muted'}`} />
                    <span className="text-sm font-medium">{tab.label}</span>
                  </button>
                );
              })}
            </nav>

            {/* Sidebar Footer — hidden on the mobile horizontal bar */}
            <div className="hidden sm:block p-4 mt-4 border-t border-hairline-soft">
              <p className="text-xs text-text-muted">
                Atria v0.1.7
              </p>
            </div>
          </div>

          {/* Content Area */}
          <div className="flex-1 min-w-0 overflow-y-auto bg-canvas">
            <div className="p-4 sm:p-6">
              {activeTab === 'model' && <ModelSettings />}
              {activeTab === 'mcp' && <MCPSettings />}
              {activeTab === 'connect' && <ChannelSettings />}
              {activeTab === 'personas' && <PersonasSettings />}
              {activeTab === 'general' && (
                <div className="text-center py-12">
                  <Cog6ToothIcon className="w-12 h-12 mx-auto text-text-muted mb-3" />
                  <p className="text-sm text-text-secondary font-medium mb-1">General Settings</p>
                  <p className="text-xs text-text-muted">
                    General settings coming soon...
                  </p>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-4 sm:px-6 py-4 border-t border-hairline-soft bg-surface-soft">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-text-secondary hover:text-ink hover:bg-surface-soft rounded-lg transition-colors"
          >
            Close
          </button>
        </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
