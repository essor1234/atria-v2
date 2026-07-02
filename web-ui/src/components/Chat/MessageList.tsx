import { memo, useEffect, useRef, useState, useMemo } from 'react';
import { Virtuoso, type VirtuosoHandle } from 'react-virtuoso';
import { ChevronDown, ChevronRight, Loader2 } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import type { Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Message } from '../../types';
import { useChatStore } from '../../stores/chat';
import { ToolCallMessage } from './ToolCallMessage';
import { ModuleActivityLine } from './ModuleActivityLine';
import { SolveDispatchCard } from './SolveDispatchCard';
import { TodoListCard } from './TodoListCard';
import { SubagentCard } from './SubagentCard';
import { groupActivity, summarizeActivity, type RenderItem } from '../../lib/activityGroups';
import { ThinkingBlock } from './ThinkingBlock';
import { SearchResultBlock } from './SearchResultBlock';
import { DeepResearchBlock } from './DeepResearchBlock';
import { DeepAnalyzeBlock } from './DeepAnalyzeBlock';
import { ImageMessage } from './ImageMessage';
import { DataMessage } from './DataMessage/DataMessage';
import { SandboxedBlock } from './SandboxedBlock';
import { THINKING_VERBS } from '../../constants/spinner';
import { computeTurns, type TurnInfo } from '../../lib/turns';
import { MessageActions } from './MessageActions';
import { useMessageActions } from '../../hooks/useMessageActions';

// Stable module-level components map — passing a new object per render
// makes ReactMarkdown discard its internal memoization on every parent tick.
const MARKDOWN_COMPONENTS: Components = {
  pre({ children }) {
    return (
      <pre className="rounded-md p-4 overflow-x-auto my-4 bg-inverse-canvas text-inverse-ink">
        {children}
      </pre>
    );
  },
  code({ className, children, ...props }) {
    const language = /language-(\w+)/.exec(className || '')?.[1];
    if (language) {
      return <code className="text-inverse-ink text-[14px] font-mono leading-relaxed" data-language={language} {...props}>{children}</code>;
    }
    return (
      <code className="text-[14px] px-1.5 py-0.5 rounded-sm font-mono bg-canvas/60 text-ink border border-hairline-soft" {...props}>
        {children}
      </code>
    );
  },
  p({ children }) {
    return <p className="mb-3 last:mb-0 text-ink text-body leading-relaxed">{children}</p>;
  },
  ul({ children }) {
    return <ul className="list-disc pl-6 space-y-1.5 mb-3 text-ink text-body">{children}</ul>;
  },
  ol({ children }) {
    return <ol className="list-decimal pl-6 space-y-1.5 mb-3 text-ink text-body">{children}</ol>;
  },
  li({ children }) {
    return <li className="text-ink text-body">{children}</li>;
  },
  strong({ children }) {
    return <strong className="font-[540] text-ink">{children}</strong>;
  },
  a({ children, href }) {
    return <a href={href} className="link-underline text-ink underline underline-offset-4 hover:decoration-2" target="_blank" rel="noopener noreferrer">{children}</a>;
  },
  h1({ children }) { return <h1 className="text-headline tracking-[-0.26px] font-[540] mt-4 mb-3 text-ink">{children}</h1>; },
  h2({ children }) { return <h2 className="text-headline tracking-[-0.26px] font-[540] mt-4 mb-3 text-ink">{children}</h2>; },
  h3({ children }) { return <h3 className="text-[20px] leading-snug tracking-[-0.14px] font-[540] mt-3 mb-2 text-ink">{children}</h3>; },
  table({ children }) {
    return (
      <div className="my-4 overflow-x-auto rounded-md border border-hairline-soft">
        <table className="w-full border-collapse text-[14px] text-ink">{children}</table>
      </div>
    );
  },
  thead({ children }) {
    return <thead className="bg-canvas/60">{children}</thead>;
  },
  tbody({ children }) {
    return <tbody>{children}</tbody>;
  },
  tr({ children }) {
    return <tr className="border-b border-hairline-soft last:border-b-0">{children}</tr>;
  },
  th({ children, style }) {
    return (
      <th
        style={style}
        className="px-3 py-2 text-left font-[540] text-ink border-r border-hairline-soft last:border-r-0"
      >
        {children}
      </th>
    );
  },
  td({ children, style }) {
    return (
      <td
        style={style}
        className="px-3 py-2 align-top text-ink/90 border-r border-hairline-soft last:border-r-0"
      >
        {children}
      </td>
    );
  },
};

const AssistantMarkdown = memo(function AssistantMarkdown({ content }: { content: string }) {
  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <div className="w-[18px] h-[18px] rounded-full bg-ink flex items-center justify-center flex-shrink-0">
          <span className="text-[8px] text-canvas font-[700] leading-none tracking-tight">A</span>
        </div>
        <span className="font-mono text-[11px] uppercase tracking-[0.54px] text-ink/40">Atria</span>
      </div>
      <div className="prose max-w-none code-hover pl-[26px]">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
          {content}
        </ReactMarkdown>
      </div>
    </div>
  );
});

const UserTurn = memo(function UserTurn({ content }: { content: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[80%] md:max-w-[70%]">
        <div className="bg-surface-soft rounded-[18px] rounded-tr-[6px] px-4 py-3">
          <div className="text-[15px] text-ink whitespace-pre-wrap leading-relaxed">
            {content}
          </div>
        </div>
      </div>
    </div>
  );
});

function LoadingSpinner({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2.5 py-1">
      <div className="w-[18px] h-[18px] rounded-full bg-ink flex items-center justify-center flex-shrink-0">
        <span className="text-[8px] text-canvas font-[700] leading-none tracking-tight">A</span>
      </div>
      <span className="braille-spinner text-sm text-ink/40" aria-hidden="true" />
      <span className="text-sm text-ink/45">{label}</span>
    </div>
  );
}

function ThinkingSpinner() {
  const [verbIndex, setVerbIndex] = useState(0);
  useEffect(() => {
    const id = setInterval(() => {
      setVerbIndex(prev => (prev + 1) % THINKING_VERBS.length);
    }, 2500);
    return () => clearInterval(id);
  }, []);
  return <LoadingSpinner label={`${THINKING_VERBS[verbIndex]}...`} />;
}

function WelcomeScreen() {
  return (
    <div className="relative flex items-center justify-center h-full px-6 bg-canvas overflow-hidden">
      <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
        <span
          className="font-sans select-none"
          style={{
            fontSize: 'clamp(140px, 20vw, 280px)',
            fontWeight: 340,
            letterSpacing: '-0.06em',
            color: 'hsl(var(--surface-soft))',
            lineHeight: 1,
          }}
        >
          Atria
        </span>
      </div>
      <div className="relative z-10 max-w-xl w-full">
        <div className="glass-card rounded-xl px-8 py-9 md:px-12 md:py-10 text-center">
          <span className="font-sans uppercase tracking-[0.24em] text-[13px] font-[500] text-text-muted block mb-4">
            Welcome
          </span>
          <h2 className="text-[40px] md:text-display-lg font-sans font-[600] leading-[1.02] tracking-[-0.03em] text-gradient-brand">
            Let&rsquo;s get to work.
          </h2>
          <p className="mt-5 text-body-sm text-text-secondary">
            Start a conversation with your AI coding assistant.
          </p>
        </div>
      </div>
    </div>
  );
}

// ─── per-item renderer ────────────────────────────────────────────────────────

interface ListContext {
  isLoading: boolean;
  progressMessage: string | null;
  totalCount: number;
  turnByIndex: Map<number, { turn: TurnInfo; isLastInTurn: boolean }>;
  actions: ReturnType<typeof useMessageActions>;
}

// Renders the body for a single message based on its role. Shared by standalone
// MessageItem rows and the expanded contents of an ActivityGroup.
function MessageBody({
  message,
  index,
  context,
}: {
  message: Message;
  index: number;
  context: ListContext;
}) {
  const { isLoading, totalCount } = context;
  const simpleMode = useChatStore(s => s.status?.simple_mode ?? true);

  if (message.role === 'todos') return <TodoListCard message={message} />;
  if (message.role === 'tool_call') {
    const hasResult = message.tool_result != null && Object.keys(message.tool_result).length > 0;
    if (message.tool_name === 'solve') {
      // Dispatch card: request text + strategy + live job progress.
      return <SolveDispatchCard message={message} />;
    }
    if (message.tool_name === 'spawn_subagent') {
      // Always show subagents as a distinct card, even in Simple Mode.
      return <SubagentCard message={message} hasResult={hasResult} />;
    }
    return simpleMode
      ? <ModuleActivityLine message={message} hasResult={hasResult} />
      : <ToolCallMessage message={message} hasResult={hasResult} />;
  }
  if (message.role === 'thinking') {
    const isLastThinking = (isLoading || !!message.streaming) && index === totalCount - 1;
    return <ThinkingBlock content={message.content} level={message.metadata?.level} isActive={isLastThinking} />;
  }
  if (message.role === 'search_result') return <SearchResultBlock message={message} />;
  if (message.role === 'data_message') return <DataMessage message={message} />;
  if (message.role === 'image_message') return <ImageMessage message={message} />;
  if (message.role === 'custom_block' && message.block_id && message.block_src) {
    return (
      <SandboxedBlock
        blockId={message.block_id}
        src={message.block_src}
        props={message.block_props || {}}
        height={message.block_height}
        title={message.block_title}
      />
    );
  }
  if (message.role === 'deep_research') return <DeepResearchBlock message={message} />;
  if (message.role === 'deep_analyze') return <DeepAnalyzeBlock message={message} />;
  return message.role === 'user'
    ? <UserTurn content={message.content} />
    : <AssistantMarkdown content={message.content} />;
}

const MessageItem = memo(function MessageItem({
  message,
  index,
  context,
}: {
  message: Message;
  index: number;
  context: ListContext;
}) {
  const { turnByIndex, actions } = context;
  const turnEntry = turnByIndex.get(index);

  const showBlockActions = !!turnEntry?.isLastInTurn;
  const align = message.role === 'user' ? 'right' : 'left';

  return (
    <div className="group relative">
      <MessageBody message={message} index={index} context={context} />
      <MessageActions
        align={align}
        onCopyMessage={() => actions.copyMessage(message)}
        onCopyBlock={showBlockActions && turnEntry ? () => actions.copyTurn(turnEntry.turn) : undefined}
        onDeleteBlock={showBlockActions && turnEntry ? () => actions.deleteTurn(turnEntry.turn) : undefined}
        deleteDisabled={actions.isLoading}
      />
    </div>
  );
});

// ─── activity group: collapses intra-turn thinking + tool exec ───────────────

function activitySummaryText(s: ReturnType<typeof summarizeActivity>): string {
  const parts: string[] = [];
  if (s.reads) parts.push(`${s.reads} đọc`);
  if (s.edits) parts.push(`${s.edits} sửa`);
  if (s.commands) parts.push(`${s.commands} lệnh`);
  if (s.other) parts.push(`${s.other} khác`);
  if (s.thinking) parts.push(`${s.thinking} suy nghĩ`);
  return parts.join(' · ');
}

const ActivityGroupItem = memo(function ActivityGroupItem({
  entries,
  context,
  isTail,
}: {
  entries: Array<{ message: Message; index: number }>;
  context: ListContext;
  isTail: boolean;
}) {
  const running = isTail && context.isLoading;
  // Collapsed by default once finished; while running, stay collapsed but show a
  // live status line so the user sees progress without the wall of steps.
  const [expanded, setExpanded] = useState(false);

  const summary = summarizeActivity(entries);
  const stepCount = summary.steps;
  const summaryText = activitySummaryText(summary);

  // Live label = the last entry's current action (for the running state).
  const last = entries[entries.length - 1]?.message;
  const liveLabel =
    last?.role === 'thinking'
      ? 'Đang suy nghĩ…'
      : last?.activity?.running || (last?.tool_name ? `Đang chạy ${last.tool_name}…` : 'Đang xử lý…');

  return (
    <div className="rounded-md border border-hairline-soft/40 bg-surface-soft/20 overflow-hidden">
      <button
        type="button"
        onClick={() => setExpanded(v => !v)}
        aria-expanded={expanded}
        className="w-full flex items-center gap-2 px-3 py-2 cursor-pointer select-none hover:bg-surface-soft/40 transition-colors text-left focus-visible:outline-none focus-visible:shadow-focus-ring"
      >
        {running ? (
          <Loader2 className="w-3.5 h-3.5 text-ink/45 flex-shrink-0 animate-spin motion-reduce:animate-none" strokeWidth={1.75} aria-hidden="true" />
        ) : (
          <ChevronRight className={`w-3.5 h-3.5 text-ink/35 flex-shrink-0 transition-transform duration-fast ${expanded ? 'rotate-90' : ''}`} aria-hidden="true" />
        )}
        <span className="text-[13px] font-[450] text-ink/55">
          {running ? liveLabel : 'Activity'}
        </span>
        <span className="text-[12px] text-ink/35 font-mono ml-0.5">
          {stepCount > 0 ? `${stepCount} bước` : `${entries.length} mục`}
          {summaryText ? ` · ${summaryText}` : ''}
        </span>
        {!running && (
          <span className="ml-auto text-[11px] text-ink/30">{expanded ? 'thu gọn' : 'bung'}</span>
        )}
      </button>

      {expanded && (
        <div className="border-t border-hairline-soft/30 px-2 py-1.5 space-y-1">
          {entries.map(({ message, index }) => (
            <div
              key={index}
              style={message.depth ? { paddingLeft: `${message.depth * 1.25}rem` } : undefined}
            >
              <MessageBody message={message} index={index} context={context} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
});

// ─── footer: progress / thinking spinner ─────────────────────────────────────

function ListFooter({ context }: { context?: ListContext }) {
  if (!context?.isLoading) return null;
  return (
    <div className="max-w-4.5xl mx-auto px-4 md:px-8 pb-8 pt-1">
      {context.progressMessage
        ? <LoadingSpinner label={context.progressMessage} />
        : <ThinkingSpinner />
      }
    </div>
  );
}

// ─── main component ───────────────────────────────────────────────────────────

export function MessageList() {
  const currentSessionId = useChatStore(state => state.currentSessionId);
  const allMessages = useChatStore(state => {
    const sid = state.currentSessionId;
    return sid ? state.sessionStates[sid]?.messages ?? [] : [];
  });
  const isLoading = useChatStore(state => {
    const sid = state.currentSessionId;
    return sid ? state.sessionStates[sid]?.isLoading ?? false : false;
  });
  const progressMessage = useChatStore(state => {
    const sid = state.currentSessionId;
    return sid ? state.sessionStates[sid]?.progressMessage ?? null : null;
  });
  const thinkingLevel = useChatStore(state => state.thinkingLevel);

  const virtuosoRef = useRef<VirtuosoHandle>(null);
  // Ref for synchronous reads inside effects/events — avoids stale closure issues
  const atBottomRef = useRef(true);
  const [atBottom, setAtBottom] = useState(true);
  const scrollerRef = useRef<HTMLElement | null>(null);

  // Exclude thinking messages when the user has thinking display turned off
  const messages = useMemo(
    () => allMessages.filter(m => !(m.role === 'thinking' && thinkingLevel === 'Off')),
    [allMessages, thinkingLevel]
  );

  // Coalesce runs of intra-turn activity (thinking + tool exec) into collapsible
  // groups so real messages stay prominent.
  const renderItems = useMemo(() => groupActivity(messages), [messages]);

  const turnInfos = useMemo(() => computeTurns(messages), [messages]);
  const turnByIndex = useMemo(() => {
    const map = new Map<number, { turn: TurnInfo; isLastInTurn: boolean }>();
    for (const t of turnInfos) {
      for (let i = t.startIndex; i <= t.endIndex; i++) {
        map.set(i, { turn: t, isLastInTurn: i === t.endIndex });
      }
    }
    return map;
  }, [turnInfos]);

  const actions = useMessageActions();

  // Passed into Virtuoso so Footer/itemContent always see current values
  const context = useMemo<ListContext>(
    () => ({ isLoading, progressMessage, totalCount: messages.length, turnByIndex, actions }),
    [isLoading, progressMessage, messages.length, turnByIndex, actions]
  );

  // On conversation switch, jump to the latest message once. The component does
  // not remount between conversations, so initialTopMostItemIndex (mount-only)
  // isn't enough. After this, Virtuoso's followOutput keeps the viewport pinned
  // during streaming as long as the user stays at the bottom — we deliberately
  // do NOT scroll on every message update, which previously fought the user's
  // own scrolling and made the view jump/bounce.
  useEffect(() => {
    atBottomRef.current = true;
    setAtBottom(true);
    const id = requestAnimationFrame(() => {
      virtuosoRef.current?.scrollToIndex({ index: 'LAST', align: 'end', behavior: 'auto' });
    });
    return () => cancelAnimationFrame(id);
  }, [currentSessionId]);

  // Auto-follow during streaming is handled SOLELY by Virtuoso's own
  // `followOutput` (see the prop below). We deliberately do NOT run a manual
  // scroll effect per message update: a manual scrollToIndex fired per streamed
  // token reads the last item's *previous* (smaller) height while it's still
  // growing, so its target lands above the current position and the view
  // visibly jumps UP — the flicker/bounce. `followOutput` scrolls only after
  // Virtuoso has re-measured, so it sticks to the bottom smoothly.

  // PageUp / PageDown keyboard scrolling
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const el = scrollerRef.current;
      if (!el) return;
      if (e.key === 'PageUp') { e.preventDefault(); el.scrollBy({ top: -300, behavior: 'auto' }); }
      else if (e.key === 'PageDown') { e.preventDefault(); el.scrollBy({ top: 300, behavior: 'auto' }); }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  if (allMessages.length === 0) return <WelcomeScreen />;

  return (
    <div className="flex-1 min-h-0 relative bg-canvas">
      <Virtuoso<RenderItem, ListContext>
        ref={virtuosoRef}
        style={{ height: '100%' }}
        data={renderItems}
        context={context}
        // Sole auto-follow authority. Sticks to the bottom (instant, no animation
        // bounce) while at the bottom — for both new message arrivals AND the
        // last message growing during streaming — and stops the moment the user
        // scrolls up. No competing manual scroll effect (that caused the flicker).
        followOutput={(isAtBottom) => isAtBottom ? 'auto' : false}
        atBottomStateChange={(bottom) => {
          atBottomRef.current = bottom;
          setAtBottom(bottom);
        }}
        // Generous threshold so fast streaming growth doesn't briefly flip
        // "at bottom" off (which would stop the follow mid-stream).
        atBottomThreshold={100}
        increaseViewportBy={{ top: 400, bottom: 400 }}
        initialTopMostItemIndex={renderItems.length - 1}
        // Stable per-item identity so re-renders don't remount/re-measure items.
        computeItemKey={(_index, item) =>
          item.kind === 'activity'
            ? item.key
            : (item.message.tool_call_id ?? item.message.data_message_id ?? `${item.message.role}:${item.index}`)
        }
        scrollerRef={(el) => { scrollerRef.current = el as HTMLElement | null; }}
        itemContent={(itemIndex, item, ctx) => (
          <div
            className="max-w-4.5xl mx-auto px-4 md:px-8 pb-5 md:pb-6"
            style={item.kind === 'message' && item.message.depth
              ? { paddingLeft: `calc(${item.message.depth * 1.5}rem + 1rem)` }
              : undefined}
          >
            {item.kind === 'activity'
              ? <ActivityGroupItem entries={item.entries} context={ctx} isTail={itemIndex === renderItems.length - 1} />
              : <MessageItem message={item.message} index={item.index} context={ctx} />}
          </div>
        )}
        components={{
          Header: () => <div className="h-8 md:h-10" aria-hidden="true" />,
          Footer: ListFooter,
        }}
      />

      {/* Scroll-to-bottom pill — appears when user has scrolled up into history */}
      {!atBottom && (
        <button
          onClick={() => virtuosoRef.current?.scrollToIndex({ index: 'LAST', align: 'end', behavior: 'auto' })}
          data-surface="dark"
          className="absolute bottom-4 right-6 z-10 flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-ink text-inverse-ink text-xs font-medium shadow-soft hover:shadow-hover hover:bg-ink/80 transition-colors active:scale-[0.98] whitespace-nowrap"
          aria-label="Jump to latest message"
        >
          <ChevronDown className="w-3.5 h-3.5" />
          Latest
        </button>
      )}
    </div>
  );
}
