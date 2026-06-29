import { useState, useRef, useEffect } from 'react';
import { ChevronDown, Network } from 'lucide-react';
import { Link } from 'react-router-dom';
import type { Message } from '../../types';

interface ToolCallMessageProps {
  message: Message;
}

// Terminal-style tool display utilities
function getToolDisplayParts(toolName: string): { verb: string; label: string } {
  const toolMap: Record<string, { verb: string; label: string }> = {
    'read_file': { verb: 'Read', label: 'file' },
    'read_pdf': { verb: 'Read', label: 'pdf' },
    'write_file': { verb: 'Write', label: 'file' },
    'edit_file': { verb: 'Edit', label: 'file' },
    'delete_file': { verb: 'Delete', label: 'file' },
    'list_files': { verb: 'List', label: 'files' },
    'list_directory': { verb: 'List', label: 'directory' },
    'search_code': { verb: 'Search', label: 'code' },
    'search': { verb: 'Search', label: 'project' },
    'run_command': { verb: 'Bash', label: 'command' },
    'bash_execute': { verb: 'Bash', label: 'command' },
    'fetch_url': { verb: 'Fetch', label: 'url' },
    'open_browser': { verb: 'Open', label: 'browser' },
    'capture_screenshot': { verb: 'Capture', label: 'screenshot' },
    'capture_web_screenshot': { verb: 'Capture', label: 'page' },
    'analyze_image': { verb: 'Analyze', label: 'image' },
    'git_commit': { verb: 'Commit', label: 'changes' },
    'present_plan': { verb: 'Present', label: 'plan' },
    'spawn_subagent': { verb: 'Spawn', label: 'agent' },
    'solve': { verb: 'Dispatch', label: 'job' },
    'get_solve_result': { verb: 'Collect', label: 'dispatch result' },
    'task_complete': { verb: 'Complete', label: 'task' },
    'invoke_skill': { verb: 'Invoke', label: 'skill' },
    'get_process_output': { verb: 'Get Output', label: 'process' },
    'list_processes': { verb: 'List', label: 'processes' },
    'kill_process': { verb: 'Kill', label: 'process' },
    'write_todos': { verb: 'Create', label: 'todos' },
    'update_todo': { verb: 'Update', label: 'todo' },
    'complete_todo': { verb: 'Complete', label: 'todo' },
    'list_todos': { verb: 'List', label: 'todos' },
    'clear_todos': { verb: 'Clear', label: 'todos' },
    'find_symbol': { verb: 'Find Symbol', label: 'symbol' },
    'find_referencing_symbols': { verb: 'Find References', label: 'symbol' },
    'insert_before_symbol': { verb: 'Insert Before', label: 'symbol' },
    'insert_after_symbol': { verb: 'Insert After', label: 'symbol' },
    'replace_symbol_body': { verb: 'Replace Symbol', label: 'symbol' },
    'rename_symbol': { verb: 'Rename Symbol', label: 'symbol' },
    'notebook_edit': { verb: 'Edit', label: 'notebook' },
    'ask_user': { verb: 'Ask', label: 'user' },
    'web_search': { verb: 'Search', label: 'web' },
    'get_subagent_output': { verb: 'Get Output', label: 'subagent' },
    'search_tools': { verb: 'Search Tools', label: 'MCP' },
    'batch_tool': { verb: 'Batch', label: 'tools' },
    'apply_patch': { verb: 'Apply', label: 'patch' },
    'git': { verb: 'Git', label: 'command' },
    'browser': { verb: 'Browser', label: 'action' },
    'schedule': { verb: 'Schedule', label: 'task' },
    'send_message': { verb: 'Send', label: 'message' },
    'memory_search': { verb: 'Search', label: 'memory' },
    'memory_write': { verb: 'Write', label: 'memory' },
    'list_sessions': { verb: 'List', label: 'sessions' },
    'get_session_history': { verb: 'Get', label: 'session history' },
    'list_subagents': { verb: 'List', label: 'subagents' },
    'list_agents': { verb: 'List', label: 'agents' },
  };

  if (toolName.startsWith('mcp__')) {
    const parts = toolName.split('__');
    if (parts.length >= 3) {
      return { verb: 'MCP', label: `${parts[1]}/${parts.slice(2).join('__')}` };
    }
    if (parts.length === 2) {
      return { verb: 'MCP', label: parts[1] };
    }
    return { verb: 'MCP', label: 'tool' };
  }

  if (toolMap[toolName]) return toolMap[toolName];

  // Smart fallback: parse tool_name tokens into verb + label
  const tokens = toolName.replace(/-/g, '_').split('_').filter(Boolean);
  if (tokens.length === 0) return { verb: 'Call', label: 'tool' };
  const verb = tokens[0].charAt(0).toUpperCase() + tokens[0].slice(1);
  if (tokens.length === 1) return { verb, label: '' };
  return { verb, label: tokens.slice(1).join(' ') };
}

function summarizeToolArgs(toolName: string, toolArgs: any): string {
  if (!toolArgs || typeof toolArgs !== 'object') return '';

  const primaryKeys: Record<string, string[]> = {
    'read_file': ['file_path', 'path'],
    'read_pdf': ['file_path'],
    'write_file': ['file_path', 'path'],
    'edit_file': ['file_path', 'path'],
    'delete_file': ['file_path', 'path'],
    'list_files': ['path', 'directory'],
    'list_directory': ['path', 'directory'],
    'search_code': ['pattern', 'query'],
    'search': ['pattern', 'query'],
    'run_command': ['command'],
    'bash_execute': ['command'],
    'fetch_url': ['url'],
    'open_browser': ['url'],
    'capture_screenshot': ['target', 'path'],
    'capture_web_screenshot': ['url'],
    'analyze_image': ['image_path', 'file_path'],
    'git_commit': ['message'],
    'present_plan': ['plan_file_path'],
    'spawn_subagent': ['subagent_type', 'description'],
    'task_complete': ['summary'],
    'invoke_skill': ['skill_name'],
    'get_process_output': ['pid', 'command'],
    'kill_process': ['pid'],
    'write_todos': ['todos'],
    'update_todo': ['id', 'status'],
    'complete_todo': ['id'],
    'find_symbol': ['name', 'symbol'],
    'find_referencing_symbols': ['name', 'symbol'],
    'replace_symbol_body': ['name', 'symbol'],
    'rename_symbol': ['name', 'new_name'],
    'notebook_edit': ['file_path', 'path'],
    'ask_user': ['question'],
    'web_search': ['query'],
    'get_subagent_output': ['agent_id'],
    'search_tools': ['query'],
    'batch_tool': ['commands'],
    'apply_patch': ['patch', 'file_path'],
    'git': ['command', 'args'],
    'memory_search': ['query'],
    'memory_write': ['key', 'content'],
    'list_sessions': [],
    'list_subagents': [],
  };

  const keys = primaryKeys[toolName] || Object.keys(toolArgs);
  for (const key of keys) {
    if (toolArgs[key] && typeof toolArgs[key] === 'string') {
      return toolArgs[key];
    }
  }
  return '';
}

// Tool result summarization functions (based on StyleFormatter from terminal UI)
function formatToolResult(toolName: string, toolArgs: any, result: any): string[] {
  if (result?.success === false) {
    const errorMsg = result?.error || 'Unknown error';
    if (errorMsg.toLowerCase().includes('interrupted')) {
      return ['User interrupted'];
    }
    return [`Error: ${errorMsg}`];
  }

  if (toolName === 'read_file') {
    return formatReadFileResult(toolArgs, result);
  } else if (toolName === 'write_file') {
    return formatWriteFileResult(toolArgs, result);
  } else if (toolName === 'edit_file') {
    return formatEditFileResult(toolArgs, result);
  } else if (toolName === 'search' || toolName === 'search_code') {
    return formatSearchResult(toolArgs, result);
  } else if (toolName === 'run_command' || toolName === 'bash_execute') {
    return formatShellResult(toolArgs, result);
  } else if (toolName === 'list_files') {
    return formatListFilesResult(toolArgs, result);
  } else if (toolName === 'fetch_url') {
    return formatFetchUrlResult(toolArgs, result);
  } else if (toolName === 'present_plan') {
    return formatPresentPlanResult(toolArgs, result);
  } else if (toolName === 'spawn_subagent') {
    return formatSpawnSubagentResult(toolArgs, result);
  } else if (toolName === 'task_complete') {
    return formatTaskCompleteResult(toolArgs, result);
  } else if (toolName === 'write_todos') {
    return formatTodosResult(toolArgs, result);
  } else if (toolName === 'update_todo' || toolName === 'complete_todo') {
    return formatTodoUpdateResult(toolName, toolArgs, result);
  } else if (toolName === 'web_search') {
    return formatSearchResult(toolArgs, result);
  } else if (toolName === 'ask_user') {
    return ['Question answered'];
  } else if (toolName === 'read_pdf') {
    return formatReadFileResult(toolArgs, result);
  } else if (toolName === 'notebook_edit') {
    return formatEditFileResult(toolArgs, result);
  } else if (toolName === 'apply_patch') {
    return formatEditFileResult(toolArgs, result);
  } else if (toolName === 'list_todos') {
    return formatListTodosResult(toolArgs, result);
  } else if (toolName === 'search_tools') {
    return formatSearchToolsResult(toolArgs, result);
  } else if (toolName === 'analyze_image') {
    return [result?.summary || 'Analysis complete'];
  } else if (toolName === 'get_process_output') {
    return formatGenericResult(toolArgs, result);
  } else if (toolName === 'list_directory') {
    return formatListFilesResult(toolArgs, result);
  } else if (toolName === 'delete_file') {
    const filePath = toolArgs?.file_path || toolArgs?.path || 'unknown';
    const fileName = filePath.split('/').pop() || filePath;
    return [`Deleted ${fileName}`];
  } else {
    return formatGenericResult(toolArgs, result);
  }
}

function formatReadFileResult(_toolArgs: any, result: any): string[] {
  const output = result?.output || result?.content || '';
  const sizeBytes = output.length;
  const sizeKb = sizeBytes / 1024;
  const lines = output ? output.split('\n').length : 0;

  const sizeDisplay = sizeKb >= 1 ? `${sizeKb.toFixed(1)} KB` : `${sizeBytes} B`;
  return [`Read ${lines} lines • ${sizeDisplay}`];
}

function formatWriteFileResult(toolArgs: any, _result: any): string[] {
  const filePath = toolArgs?.file_path || toolArgs?.path || 'unknown';
  const content = toolArgs?.content || '';
  const sizeBytes = content.length;
  const sizeKb = sizeBytes / 1024;
  const lines = content ? content.split('\n').length : 0;

  const fileName = filePath.split('/').pop() || filePath;
  const sizeDisplay = sizeKb >= 1 ? `${sizeKb.toFixed(1)} KB` : `${sizeBytes} B`;
  return [`Created ${fileName} • ${sizeDisplay} • ${lines} lines`];
}

function formatEditFileResult(toolArgs: any, _result: any): string[] {
  const filePath = toolArgs?.file_path || toolArgs?.path || 'unknown';
  const fileName = filePath.split('/').pop() || filePath;
  return [`Updated ${fileName}`];
}

function formatSearchResult(_toolArgs: any, result: any): string[] {
  const matches = result?.matches || [];
  const output = result?.output || '';

  if (matches.length > 0) {
    const summary = matches.slice(0, 3).map((match: any) => {
      const line = typeof match === 'string' ? match : match.line || match.content || '';
      const preview = line.length > 50 ? line.slice(0, 47) + '...' : line;
      return preview;
    });

    if (matches.length > 3) {
      summary.push(`... and ${matches.length - 3} more`);
    }
    return summary;
  }

  if (output) {
    const lines = output.split('\n');
    return lines.slice(0, 3);
  }

  return ['No matches found'];
}

function formatShellResult(toolArgs: any, result: any): string[] {
  const command = toolArgs?.command || '';
  const stdout = result?.stdout || result?.output || '';
  const stderr = result?.stderr || '';
  const exitCode = result?.exit_code;

  if (exitCode !== undefined && exitCode !== 0 && exitCode !== null) {
    return stderr ? [stderr.split('\n')[0]] : [`Exit code ${exitCode}`];
  }

  const normalizedCmd = command.toLowerCase();
  const normalizedStdout = stdout.toLowerCase();

  // Special git command handling
  if (normalizedCmd.includes('git ')) {
    if (normalizedCmd.includes('push')) return ['Changes pushed to remote'];
    if (normalizedCmd.includes('commit')) return ['Changes committed'];
    if (normalizedCmd.includes('pull')) return ['Changes pulled from remote'];
    return ['Git command completed'];
  }

  // Special npm command handling
  if (normalizedCmd.includes('npm install')) {
    if (normalizedStdout.includes('added') && normalizedStdout.includes('package')) {
      return ['Packages installed successfully'];
    }
    return ['npm install completed'];
  }

  if (stdout) {
    const lines = stdout.split('\n').filter((line: string) => line.trim());
    if (lines.length === 1 && lines[0].length < 80) {
      return [lines[0]];
    }
    const firstLine = lines[0];
    const preview = firstLine.length > 70 ? firstLine.slice(0, 70) + '...' : firstLine;
    return [`${preview} (${lines.length} lines)`];
  }

  if (stderr) {
    return [stderr.split('\n')[0]];
  }

  return ['Command completed with no output'];
}

function formatListFilesResult(_toolArgs: any, result: any): string[] {
  const entries = result?.entries;
  if (entries && Array.isArray(entries)) {
    return [`${entries.length} entries`];
  }

  const output = result?.output || '';
  if (!output) {
    return ['No files found'];
  }

  const lines = output.split('\n').filter((line: string) => line.trim());
  return lines.length > 0 ? [`${lines.length} items`] : ['No files found'];
}

function formatFetchUrlResult(_toolArgs: any, result: any): string[] {
  const status = result?.status_code || result?.status;
  const output = result?.output || '';

  if (status) {
    return [`Status ${status} • ${output.length} bytes`];
  }

  return [`${output.length} bytes received`];
}

function formatPresentPlanResult(_toolArgs: any, result: any): string[] {
  if (result?.plan_approved) {
    return result?.auto_approve
      ? ['Plan approved (auto-approve edits)']
      : ['Plan approved (review edits)'];
  }
  if (result?.requires_modification) {
    return ['Plan requires modifications'];
  }
  if (result?.plan_rejected) {
    return ['Plan rejected'];
  }
  return [typeof result?.output === 'string' ? result.output : 'Plan presented'];
}

function formatSpawnSubagentResult(toolArgs: any, result: any): string[] {
  const agentType = toolArgs?.subagent_type || toolArgs?.agent_type || 'agent';
  const output = typeof result?.output === 'string' ? result.output : '';
  if (result?.success === false) {
    return [`${agentType} agent failed`];
  }
  if (output) {
    const firstLine = output.split('\n')[0];
    return [firstLine.length > 80 ? firstLine.slice(0, 77) + '...' : firstLine];
  }
  return [`${agentType} agent completed`];
}

function formatTaskCompleteResult(_toolArgs: any, result: any): string[] {
  const raw = result?.output || result?.summary || '';
  const summary = typeof raw === 'string' ? raw : String(raw);
  if (summary) {
    return [summary.length > 100 ? summary.slice(0, 97) + '...' : summary];
  }
  return ['Task completed'];
}

function formatTodosResult(_toolArgs: any, result: any): string[] {
  const output = result?.output || '';
  const count = (output.match(/○|▶|✓/g) || []).length;
  return count > 0 ? [`${count} todo(s) created`] : ['Todos updated'];
}

function formatTodoUpdateResult(toolName: string, toolArgs: any, _result: any): string[] {
  const id = toolArgs?.id;
  const label = id !== undefined ? `todo-${Number(id) + 1}` : 'todo';
  const action = toolName === 'complete_todo' ? 'Completed' : 'Updated';
  return [`${action} ${label}`];
}

function formatListTodosResult(_toolArgs: any, result: any): string[] {
  const output = result?.output || '';
  const active = (output.match(/○/g) || []).length;
  const doing = (output.match(/▶/g) || []).length;
  const done = (output.match(/✓/g) || []).length;
  const total = active + doing + done;
  return total > 0 ? [`${total} todo(s) (${active} pending, ${doing} active, ${done} done)`] : ['No todos'];
}

function formatSearchToolsResult(_toolArgs: any, result: any): string[] {
  const output = result?.output || '';
  const lines = output.split('\n').filter((l: string) => l.trim());
  const toolCount = lines.filter((l: string) => l.startsWith('  - ') || l.startsWith('• ')).length;
  if (toolCount > 0) return [`Found ${toolCount} tool(s)`];
  if (output.includes('Found')) return [lines[0]];
  return ['Search complete'];
}

function formatGenericResult(_toolArgs: any, result: any): string[] {
  const output = result?.output || '';

  if (typeof output === 'string') {
    const lines = output.split('\n').filter((line: string) => line.trim());
    if (lines.length === 0) return [];
    return lines.slice(0, 3).concat(lines.length > 3 ? ['…'] : []);
  }

  if (Array.isArray(output)) {
    const summary = output.slice(0, 3).map((item: any) => String(item));
    if (output.length > 3) {
      summary.push('…');
    }
    return summary;
  }

  if (output && typeof output === 'object') {
    return ['Object received'];
  }

  return output ? [String(output)] : [];
}

interface ToolCallMessageExtProps extends ToolCallMessageProps {
  hasResult?: boolean;
}

export function ToolCallMessage({ message, hasResult }: ToolCallMessageExtProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const expandRef = useRef<HTMLDivElement>(null);
  const [expandHeight, setExpandHeight] = useState(0);

  useEffect(() => {
    const el = expandRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setExpandHeight(el.scrollHeight));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  if (message.role === 'tool_call') {
    const toolName = message.tool_name ||
                     (message.tool_calls && message.tool_calls[0]?.name) ||
                     (message as any)?.name || '';

    const toolArgs = message.tool_args || {};
    const toolResult = message.tool_result ?? {};
    const summaryOverride = message.tool_summary;
    const successOverride = message.tool_success;

    let { verb } = getToolDisplayParts(toolName);
    let summary =
      message.tool_args_display ??
      summarizeToolArgs(toolName, toolArgs);

    // format_tool_call returns "Verb(args)" — extract just the args part
    if (summary && summary.includes('(') && summary.endsWith(')')) {
      const parenIdx = summary.indexOf('(');
      summary = summary.slice(parenIdx + 1, -1);
    }

    // For spawn_subagent, use subagent type as verb and description as summary
    // to match TUI: "code-explorer(Auth flow overview)" → "▶ Code Explorer  Auth flow overview"
    if (toolName === 'spawn_subagent') {
      const subagentType = toolArgs?.subagent_type || toolArgs?.agent_type || '';
      if (subagentType) {
        verb = subagentType.split(/[-_]/).map((w: string) => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
        summary = toolArgs?.description || '';
      }
    }

    // Handle result processing
    let resultData = toolResult;
    if (typeof toolResult === 'string') {
      try {
        resultData = JSON.parse(toolResult);
      } catch {
        resultData = {
          output: toolResult,
          success: !toolResult.includes('::tool_error::') && !toolResult.includes('::interrupted::')
        };
      }
    }


    // Get result summary
    let summaryLines: string[] = [];
    if (summaryOverride) {
      summaryLines = Array.isArray(summaryOverride)
        ? summaryOverride
        : [summaryOverride];
    } else {
      try {
        summaryLines = formatToolResult(toolName, toolArgs, resultData);
      } catch {
        if (typeof toolResult === 'string') {
          const cleaned = toolResult.replace(/::tool_error::|::interrupted::/g, '').trim();
          summaryLines = cleaned.split('\n').slice(0, 3).filter((line: string) => line.trim());
          if (cleaned.split('\n').length > 3) {
            summaryLines.push('…');
          }
        } else {
          summaryLines = ['Tool completed'];
        }
      }
    }

    // Check for expandable content
    let fullOutput: string | undefined;
    if (typeof toolResult === 'string') {
      fullOutput = toolResult;
    } else if (resultData?.output) {
      fullOutput = typeof resultData.output === 'string'
        ? resultData.output
        : JSON.stringify(resultData.output, null, 2);
    } else if (Object.keys(resultData || {}).length > 0) {
      try {
        fullOutput = JSON.stringify(resultData, null, 2);
      } catch {
        fullOutput = String(resultData);
      }
    }
    const hasExpandableContent = !!fullOutput && fullOutput.length > 200;

    const isRunning = hasResult === false;

    return (
      <div className={`rounded-md border border-hairline-soft/50 overflow-hidden ${isRunning ? 'tool-executing' : ''}`}>
        {/* Header row */}
        <div
          className="flex items-center gap-2 px-3 py-2 cursor-pointer select-none hover:bg-surface-soft/40 transition-colors"
          onClick={hasExpandableContent ? () => setIsExpanded(!isExpanded) : undefined}
        >
          <span className="text-ink/25 text-[11px] select-none flex-shrink-0">·</span>
          <span className="text-[13px] font-[450] text-ink/65">{verb}</span>
          {summary && (
            <span className="text-[12px] text-ink/40 font-mono bg-surface-soft rounded px-1.5 py-[2px] ml-0.5 max-w-[260px] truncate">
              {summary}
            </span>
          )}
          {isRunning && (
            <span className="ml-auto inline-block w-3 h-3 border-[1.5px] border-ink/30 border-t-transparent rounded-full animate-spin flex-shrink-0" />
          )}
          {hasExpandableContent && !isRunning && (
            <ChevronDown className={`w-3 h-3 text-ink/25 ml-auto flex-shrink-0 transition-transform duration-fast ${isExpanded ? 'rotate-180' : ''}`} />
          )}
        </div>

        {/* Result summary */}
        {!(toolName === 'spawn_subagent' && isRunning) && summaryLines.length > 0 && (
          <div className="px-3 pb-2 pt-0.5 pl-5">
            {summaryLines.map((line: string, index: number) => {
              const lineStr = typeof line === 'string' ? line : String(line);
              const isError = message.tool_error
                ? true
                : lineStr.includes('Error') || lineStr.includes('Failed') || lineStr.includes('interrupted') || lineStr.includes('Exit code');
              const isSuccess = !isError && (successOverride ?? (
                lineStr.includes('Read') || lineStr.includes('Created') || lineStr.includes('Updated') ||
                lineStr.includes('Changes') || lineStr.includes('Packages installed') || lineStr.includes('completed')
              ));

              return (
                <div key={index} className={`font-mono text-[12px] leading-5 ${
                  isError ? 'text-block-coral' : isSuccess ? 'text-semantic-success' : 'text-ink/40'
                }`}>
                  {lineStr}
                </div>
              );
            })}
          </div>
        )}

        {/* Dispatch affordance — jump from chat to the live monitor */}
        {(toolName === 'solve' || toolName === 'get_solve_result') && (
          <div className="px-3 pb-2 pl-5">
            <Link
              to="/dispatch"
              className="inline-flex items-center gap-1.5 text-[12px] font-[450] text-semantic-success hover:underline cursor-pointer focus-visible:outline-none focus-visible:shadow-focus-ring rounded"
            >
              <Network className="w-3 h-3" strokeWidth={1.75} aria-hidden="true" />
              Mở Dispatch để theo dõi →
            </Link>
          </div>
        )}

        {/* Expanded raw output */}
        {hasExpandableContent && (
          <div
            className="overflow-hidden transition-all duration-base ease-motion-out"
            style={{ maxHeight: isExpanded ? `${expandHeight}px` : '0px' }}
          >
            <div ref={expandRef} className="px-3 pt-2 pb-3 border-t border-hairline-soft/40">
              {fullOutput && (
                <pre className="text-[12px] text-ink/50 font-mono bg-surface-soft rounded px-3 py-2.5 overflow-x-auto leading-[1.55]">
                  {fullOutput}
                </pre>
              )}
            </div>
          </div>
        )}
      </div>
    );
  }

  return null;
}
