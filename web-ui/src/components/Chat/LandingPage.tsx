import {
  FileText,
  Image,
  Loader2,
  Paperclip,
  Plus,
  SendHorizontal,
  X,
} from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { KeyboardEvent, useEffect, useRef, useState } from "react";
import TextareaAutosize from "react-textarea-autosize";
import { useChatStore } from "../../stores/chat";
import { useProjectsStore } from "../../stores/projects";
import { AnimatedHeadline } from "../ui/AnimatedHeadline";
import { transitions } from "../ui/motion";

export function LandingPage() {
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showPlusMenu, setShowPlusMenu] = useState(false);
  const [attachedFiles, setAttachedFiles] = useState<File[]>([]);

  const textareaRef = useRef<HTMLTextAreaElement>(null); // kept for focus()
  const plusMenuRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const fileAcceptRef = useRef<string>("");

  const isConnected = useChatStore((state) => state.isConnected);
  const sendMessage = useChatStore((state) => state.sendMessage);

  const { createWorkspaceConversation } = useProjectsStore();
  const reduce = useReducedMotion();

  // Click-outside to dismiss menus
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (
        plusMenuRef.current &&
        !plusMenuRef.current.contains(e.target as Node)
      ) {
        setShowPlusMenu(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleSend = async () => {
    if (!input.trim() || isLoading || !isConnected) return;
    setIsLoading(true);
    setError(null);
    try {
      await createWorkspaceConversation("New Chat");
      sendMessage(input.trim());
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load conversation",
      );
      setIsLoading(false);
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleFileUpload = (accept: string) => {
    fileAcceptRef.current = accept;
    setShowPlusMenu(false);
    setTimeout(() => {
      if (fileInputRef.current) {
        fileInputRef.current.accept = accept;
        fileInputRef.current.click();
      }
    }, 0);
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files) setAttachedFiles((prev) => [...prev, ...Array.from(files)]);
    e.target.value = "";
  };

  const removeFile = (index: number) => {
    setAttachedFiles((prev) => prev.filter((_, i) => i !== index));
  };


  return (
    <div className="relative flex flex-col items-center justify-center h-full px-6 bg-canvas overflow-hidden">
      {/* Background watermark — oversized editorial wordmark */}
      <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
        <span
          className="font-sans select-none animate-breathe"
          style={{
            fontSize: "clamp(160px, 22vw, 320px)",
            fontWeight: 340,
            letterSpacing: "-0.06em",
            color: "hsl(var(--surface-soft))",
            lineHeight: 1,
          }}
        >
          Atria
        </span>
        <div
          className="absolute animate-spin-slow"
          style={{ width: 360, height: 360 }}
        >
          {Array.from({ length: 24 }).map((_, i) => {
            const angle = (i / 24) * 360;
            return (
              <span
                key={i}
                className="absolute text-lg font-mono text-bg-300 braille-ring-char"
                style={
                  {
                    left: "50%",
                    top: "50%",
                    transform: `rotate(${angle}deg) translateX(180px) rotate(-${angle}deg)`,
                    "--braille-delay": `${-(i / 24).toFixed(3)}s`,
                  } as React.CSSProperties
                }
                aria-hidden="true"
              />
            );
          })}
        </div>
      </div>

      {/* Centered input card */}
      <div className="relative z-10 w-full max-w-2xl animate-fade-in">
        <div className="mb-8 text-center">
          <motion.span
            initial={reduce ? false : { opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={transitions.chrome}
            className="font-mono uppercase tracking-[0.54px] text-[12px] text-ink/60 block"
          >
            New conversation
          </motion.span>
          <AnimatedHeadline
            as="h2"
            text={"What are we building?"}
            className="mt-3 text-[40px] md:text-display-lg font-sans font-[340] tracking-[-0.96px] leading-[1.05] text-ink"
            step={20}
            startDelay={140}
          />
        </div>
        <motion.div
          initial={reduce ? false : { opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ ...transitions.editorial, delay: 0.45 }}
          className="rounded-lg border border-hairline-soft bg-canvas shadow-soft"
        >
          {/* Textarea */}
          <div className="px-5 pt-5 pb-2 rounded-t-2xl">
            <TextareaAutosize
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="How can I help you today?"
              disabled={isLoading || !isConnected}
              className="w-full bg-transparent text-text-000 placeholder-text-400 resize-none border-0 text-base leading-relaxed disabled:opacity-50 disabled:cursor-not-allowed"
              minRows={3}
              maxRows={8}
            />

            {/* Attached file chips */}
            {attachedFiles.length > 0 && (
              <div className="flex flex-wrap gap-2 mt-2">
                {attachedFiles.map((file, i) => (
                  <span
                    key={i}
                    className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-bg-200 text-text-200 text-xs border border-border-300/15"
                  >
                    <Paperclip className="w-3.5 h-3.5 text-text-400" />
                    {file.name}
                    <button
                      onClick={() => removeFile(i)}
                      className="ml-0.5 text-text-400 hover:text-danger-100"
                    >
                      <X className="w-3 h-3" strokeWidth={2.5} />
                    </button>
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* Bottom utility bar */}
          <div className="flex items-center justify-between px-4 py-3 border-t border-border-300/10 rounded-b-2xl">
            {/* Left: + button */}
            <div className="relative" ref={plusMenuRef}>
              <button
                onClick={() => setShowPlusMenu(!showPlusMenu)}
                className="w-8 h-8 rounded-full flex items-center justify-center bg-bg-200 hover:bg-bg-300 text-text-300 hover:text-text-100 transition-colors"
                title="Attach files"
              >
                <Plus className="w-4 h-4" />
              </button>

              {showPlusMenu && (
                <div className="absolute bottom-full left-0 mb-2 w-48 bg-bg-000 border border-border-300/20 rounded-xl shadow-soft overflow-hidden z-50 animate-fade-in">
                  <button
                    onClick={() =>
                      handleFileUpload(".png,.jpg,.jpeg,.gif,.webp")
                    }
                    className="w-full px-4 py-2.5 text-left text-sm text-text-100 hover:bg-bg-200 flex items-center gap-2.5"
                  >
                    <Image className="w-4 h-4 text-text-400" />
                    Upload image
                  </button>
                  <button
                    onClick={() => handleFileUpload(".pdf,.docx")}
                    className="w-full px-4 py-2.5 text-left text-sm text-text-100 hover:bg-bg-200 flex items-center gap-2.5"
                  >
                    <FileText className="w-4 h-4 text-text-400" />
                    Upload document
                  </button>
                </div>
              )}
            </div>

            {/* Right: conversation picker + send */}
            <div className="flex items-center gap-2">
              {/* Send button */}
              <button
                onClick={handleSend}
                disabled={!input.trim() || isLoading || !isConnected}
                className="w-8 h-8 rounded-lg flex items-center justify-center bg-accent-main-100 hover:bg-accent-main-200 text-white disabled:opacity-40 disabled:cursor-not-allowed disabled:bg-bg-300 disabled:text-text-500 transition-colors"
                title="Send (Enter)"
              >
                {isLoading ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <SendHorizontal className="w-4 h-4" />
                )}
              </button>
            </div>
          </div>
        </motion.div>

        {error && (
          <p className="mt-3 text-sm text-danger-100 text-center animate-fade-in">
            {error}
          </p>
        )}

        <p className="mt-4 text-xs text-text-400 text-center">
          <kbd className="px-1.5 py-0.5 bg-bg-200 border border-border-300/20 rounded text-xs">
            Enter
          </kbd>{" "}
          to send &middot;{" "}
          <kbd className="px-1.5 py-0.5 bg-bg-200 border border-border-300/20 rounded text-xs">
            Shift + Enter
          </kbd>{" "}
          for new line
        </p>
      </div>

      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        className="hidden"
        onChange={handleFileChange}
      />

    </div>
  );
}
