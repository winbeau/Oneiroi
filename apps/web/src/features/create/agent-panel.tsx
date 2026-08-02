import {
  AlertTriangle,
  ArrowRight,
  Bot,
  Check,
  CheckCircle2,
  ImageIcon,
  LoaderCircle,
  Paperclip,
  Send,
  ShieldCheck,
  Sparkles,
  Square,
  WandSparkles,
  X,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  agentKeys,
  useAgentCapabilities,
  useAgentMessages,
  useAgentRunStream,
  useAgentThread,
  useAgentToolDecision,
  useCancelAgentRun,
  useCreateAgentRun,
} from "@/features/agent/hooks";
import type {
  AgentApproval,
  AgentDraftProposal,
  AgentEvent,
  AgentImageCandidate,
  AgentImageResult,
  AgentRun,
  AgentToolCall,
} from "@/features/agent/types";
import { useCreateConversation, useAssets } from "@/features/studio/hooks";
import type { GenerationDraft, StudioAsset } from "@/features/studio/types";
import { apiUrl } from "@/lib/api-client";
import { cn } from "@/lib/utils";
import { useStudioStore } from "@/store/studio-store";
import { useQueryClient } from "@tanstack/react-query";

const runningStatuses = new Set([
  "queued",
  "streaming",
  "waiting_approval",
  "executing_tool",
  "cancelling",
  "recovering",
]);

const errorCopy: Record<string, string> = {
  AGENT_IMAGE_NOT_SUPPORTED: "当前 Agent 模型没有通过图片能力检查。",
  AGENT_IMAGE_INVALID: "生成图片未通过安全校验，请重新发起一次请求。",
  AGENT_IMAGE_REJECTED: "图片内容被安全策略拒绝，已保留其他成功结果。",
  AGENT_RESOURCE_NOT_FOUND: "引用的资产不存在或不属于当前账号。",
  AGENT_RUN_TIMEOUT: "本次助理任务已达到运行时限，请重新发起。",
  AGENT_TOOL_RECOVERY_REQUIRED: "生成结果状态未知，为避免重复计费不会自动重试。",
  AGENT_OUTPUT_INVALID: "模型输出格式无效，请重新发起一次请求。",
  AGENT_NOT_CONFIGURED: "Oneiroi 助理尚未完成服务端配置。",
};

type PendingApproval = {
  toolCall: AgentToolCall;
  approval: AgentApproval;
};

export function AgentPanel({ defaultOpen = false }: { defaultOpen?: boolean }) {
  const capabilities = useAgentCapabilities();
  const available = capabilities.data?.available === true;
  const imageToolAvailable = Boolean(
    capabilities.data?.imageGeneration &&
      capabilities.data.toolsEnabled &&
      capabilities.data.tools?.some(
        (tool) => tool.name === "generate_reference_image" && tool.requiresApproval,
      ),
  );
  const draft = useStudioStore((state) => state.draft);
  const updateDraft = useStudioStore((state) => state.updateDraft);
  const activeConversationId = useStudioStore((state) => state.activeConversationId);
  const setActiveConversation = useStudioStore((state) => state.setActiveConversation);
  const [open, setOpen] = useState(defaultOpen);
  const [message, setMessage] = useState("");
  const [lastMessage, setLastMessage] = useState("");
  const [activeRun, setActiveRun] = useState<AgentRun | null>(null);
  const [threadIdOverride, setThreadIdOverride] = useState("");
  const [pendingApproval, setPendingApproval] = useState<PendingApproval | null>(null);
  const [imageResults, setImageResults] = useState<AgentImageResult[]>([]);
  const [, setStreamBuffer] = useState("");
  const [streamText, setStreamText] = useState("");
  const [runError, setRunError] = useState("");
  const [decisionError, setDecisionError] = useState("");
  const [appliedProposals, setAppliedProposals] = useState<Set<string>>(new Set());
  const [savedAssets, setSavedAssets] = useState<Set<string>>(new Set());
  const queryClient = useQueryClient();
  const createConversation = useCreateConversation();
  const createRun = useCreateAgentRun();
  const decideTool = useAgentToolDecision();
  const cancelRun = useCancelAgentRun();
  const threadQuery = useAgentThread(activeConversationId, open && available);
  const threadId = threadIdOverride || threadQuery.data?.id || "";
  const messagesQuery = useAgentMessages(threadId, open && available);
  const assetsQuery = useAssets();
  const assets = assetsQuery.data ?? [];
  const previousConversationId = useRef(activeConversationId);

  useEffect(() => {
    const previous = previousConversationId.current;
    previousConversationId.current = activeConversationId;
    if (!previous || previous === activeConversationId) return;
    setActiveRun(null);
    setThreadIdOverride("");
    setPendingApproval(null);
    setImageResults([]);
    setStreamBuffer("");
    setStreamText("");
    setRunError("");
    setDecisionError("");
  }, [activeConversationId]);

  const onAgentEvent = useCallback(
    (event: AgentEvent) => {
      if (event.type === "agent.run.started" || event.type === "agent.run.resumed") {
        setActiveRun((current) =>
          current ? { ...current, status: "streaming", startedAt: current.startedAt ?? new Date().toISOString() } : current,
        );
      }
      if (event.type === "agent.message.delta") {
        const delta = typeof event.data.delta === "string" ? event.data.delta : "";
        if (delta) {
          setStreamBuffer((current) => {
            const next = current + delta;
            setStreamText(extractVisibleAgentText(next));
            return next;
          });
        }
      }
      if (event.type === "agent.approval.required") {
        const toolCall = readToolCall(event.data.toolCall);
        const approval = readApproval(event.data.approval);
        if (toolCall && approval) {
          setPendingApproval({ toolCall, approval });
          setActiveRun((current) =>
            current ? { ...current, status: "waiting_approval" } : current,
          );
        }
      }
      if (event.type === "agent.tool.started") {
        setActiveRun((current) =>
          current ? { ...current, status: "executing_tool" } : current,
        );
      }
      if (event.type === "agent.tool.completed") {
        const toolCall = readToolCall(event.data.toolCall);
        if (toolCall?.toolName === "generate_reference_image") {
          const result = readImageResult(toolCall);
          if (result) {
            setImageResults((items) => [
              ...items.filter((item) => item.toolCallId !== result.toolCallId),
              result,
            ]);
            void queryClient.invalidateQueries({ queryKey: ["assets"] });
          }
        }
        setPendingApproval(null);
        setActiveRun((current) =>
          current ? { ...current, status: "streaming" } : current,
        );
      }
      if (event.type === "agent.tool.failed") {
        const toolCall = readToolCall(event.data.toolCall);
        setPendingApproval(null);
        setRunError(
          friendlyAgentError(toolCall?.errorCode ?? "AGENT_TOOL_FAILED", toolCall?.errorMessage),
        );
      }
      if (event.type === "agent.run.completed") {
        setActiveRun((current) =>
          current ? { ...current, status: "completed", finishedAt: new Date().toISOString() } : current,
        );
        setPendingApproval(null);
        setStreamBuffer("");
        setStreamText("");
        void queryClient.invalidateQueries({ queryKey: agentKeys.messages(event.threadId) });
        void queryClient.invalidateQueries({ queryKey: ["assets"] });
      }
      if (event.type === "agent.run.failed") {
        const code = typeof event.data.code === "string" ? event.data.code : "AGENT_RUN_FAILED";
        setRunError(friendlyAgentError(code));
        setActiveRun((current) =>
          current ? { ...current, status: "failed", errorCode: code } : current,
        );
        setPendingApproval(null);
      }
      if (event.type === "agent.run.cancelled") {
        setActiveRun((current) =>
          current ? { ...current, status: "cancelled", finishedAt: new Date().toISOString() } : current,
        );
        setPendingApproval(null);
      }
    },
    [queryClient],
  );

  const stream = useAgentRunStream(activeRun?.id ?? "", onAgentEvent);
  const isRunning = Boolean(activeRun && runningStatuses.has(activeRun.status));
  const attachedAssetIds = useMemo(
    () =>
      capabilities.data?.imageInput
        ? [draft.firstFrame?.assetId, draft.lastFrame?.assetId].filter(
            (assetId): assetId is string => Boolean(assetId),
          )
        : [],
    [capabilities.data?.imageInput, draft.firstFrame?.assetId, draft.lastFrame?.assetId],
  );

  if (!available) return null;

  const sendMessage = async () => {
    const trimmed = message.trim();
    if (!trimmed || isRunning || createRun.isPending) return;
    setRunError("");
    setDecisionError("");
    setStreamBuffer("");
    setStreamText("");
    try {
      let conversationId = activeConversationId;
      if (!conversationId) {
        const conversation = await createConversation.mutateAsync(
          trimmed.slice(0, 18) || "Oneiroi 助理会话",
        );
        conversationId = conversation.id;
        setActiveConversation(conversation.id);
      }
      const run = await createRun.mutateAsync({
        conversationId,
        message: trimmed,
        draft,
        assetIds: attachedAssetIds,
        mode: attachedAssetIds.length > 0 && /分析|参考|画面|图片|图像/.test(trimmed)
          ? "image-analysis"
          : "assist",
      });
      setActiveRun(run);
      setThreadIdOverride(run.threadId);
      setLastMessage(trimmed);
      setMessage("");
    } catch (error) {
      setRunError(error instanceof Error ? error.message : "Oneiroi 助理暂时不可用");
    }
  };

  const makeDecision = async (decision: "approve" | "reject") => {
    if (!pendingApproval) return;
    setDecisionError("");
    try {
      const response = await decideTool.mutateAsync({
        toolCallId: pendingApproval.toolCall.id,
        decision,
      });
      setActiveRun(response.run);
      setPendingApproval(null);
    } catch (error) {
      setDecisionError(error instanceof Error ? error.message : "审批状态更新失败");
    }
  };

  const applyProposal = (messageId: string, proposal: AgentDraftProposal) => {
    updateDraft(proposalPatch(proposal, assets));
    setAppliedProposals((items) => new Set(items).add(messageId));
  };

  const applyImage = (candidate: AgentImageCandidate, target: "firstFrame" | "lastFrame") => {
    const stored = assets.find((asset) => asset.id === candidate.id);
    updateDraft({
      [target]: {
        name: candidate.title,
        assetId: candidate.id,
        url: stored?.previewUrl ?? apiUrl(`/v1/assets/${candidate.id}/file`),
      },
    });
    setSavedAssets((items) => new Set(items).add(candidate.id));
  };

  return (
    <motion.section
      className="overflow-hidden rounded-[8px] border border-[var(--color-border)] bg-white/72 backdrop-blur-sm"
      layout
      transition={{ duration: 0.16, ease: "easeOut" }}
    >
      <button
        aria-expanded={open}
        aria-label={open ? "收起 Oneiroi 助理" : "展开 Oneiroi 助理"}
        className="flex w-full items-center gap-3 px-3.5 py-3 text-left transition-colors hover:bg-white/72 md:px-4"
        onClick={() => setOpen((value) => !value)}
        type="button"
      >
        <span className="relative grid size-9 shrink-0 place-items-center rounded-[7px] border border-[var(--color-border-strong)] bg-[var(--color-canvas)] text-[var(--color-text)]">
          <Bot aria-hidden="true" className="size-4" />
          <span className="absolute -right-0.5 -top-0.5 size-2 rounded-full border-2 border-white bg-[var(--color-accent)]" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold">Oneiroi 助理</span>
            <span className="rounded-[4px] bg-[var(--color-accent-soft)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--color-accent)]">
              {capabilities.data?.model ?? "GPT"}
            </span>
            {imageToolAvailable && (
              <span className="inline-flex items-center gap-1 text-[10px] text-[var(--color-text-faint)]">
                <ShieldCheck className="size-3" /> 参考图需确认
              </span>
            )}
          </span>
          <span className="mt-0.5 block truncate text-xs text-[var(--color-text-muted)]">
            理解当前 Prompt 与参考帧，给出可确认的创作建议。
          </span>
        </span>
        <ArrowRight
          aria-hidden="true"
          className={cn("size-3.5 text-[var(--color-text-faint)] transition-transform", open && "rotate-90")}
        />
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            animate={{ height: "auto", opacity: 1 }}
            className="overflow-hidden"
            exit={{ height: 0, opacity: 0 }}
            initial={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.18, ease: "easeOut" }}
          >
            <div className="border-t border-[var(--color-border)] px-3.5 pb-3.5 pt-3 md:px-4">
              <div className="scrollbar-notion max-h-[310px] space-y-2.5 overflow-y-auto pr-1">
                {(messagesQuery.data ?? [])
                  .filter((item) => item.role === "user" || item.role === "assistant")
                  .map((item) => (
                    <div
                      className={cn(
                        "max-w-[92%] rounded-[7px] border px-3 py-2.5 text-sm leading-6",
                        item.role === "user"
                          ? "ml-auto border-[var(--color-border)] bg-[var(--color-surface-muted)]"
                          : "border-[var(--color-accent)]/14 bg-[var(--color-accent-faint)]/42",
                      )}
                      key={item.id}
                    >
                      <p className="whitespace-pre-wrap">{item.content.text}</p>
                      {item.content.draftProposal && (
                        <DraftProposalCard
                          applied={appliedProposals.has(item.id)}
                          onApply={() => applyProposal(item.id, item.content.draftProposal!)}
                          proposal={item.content.draftProposal}
                          rationale={item.content.rationale ?? []}
                          warnings={item.content.warnings ?? []}
                        />
                      )}
                    </div>
                  ))}

                {isRunning && activeRun?.status !== "waiting_approval" && (
                  <div className="max-w-[92%] rounded-[7px] border border-[var(--color-border)] bg-[var(--color-canvas)] px-3 py-2.5 text-sm">
                    <div className="flex items-center gap-2 text-[var(--color-text-muted)]">
                      <LoaderCircle className="size-3.5 animate-spin" />
                      {activeRun?.status === "executing_tool"
                        ? "正在安全生成参考图…"
                        : streamText || "正在整理创作建议…"}
                    </div>
                  </div>
                )}

                {pendingApproval && (
                  <ApprovalCard
                    decisionError={decisionError}
                    disabled={decideTool.isPending}
                    onApprove={() => void makeDecision("approve")}
                    onReject={() => void makeDecision("reject")}
                    pending={pendingApproval}
                  />
                )}

                {imageResults.map((result) => (
                  <ImageResultCard
                    assets={assets}
                    key={result.toolCallId}
                    onApply={applyImage}
                    onSave={(assetId) => setSavedAssets((items) => new Set(items).add(assetId))}
                    result={result}
                    savedAssets={savedAssets}
                  />
                ))}

                {runError && (
                  <div className="rounded-[7px] border border-[var(--color-danger)]/20 bg-[var(--color-danger)]/5 p-3">
                    <div className="flex gap-2 text-sm text-[var(--color-danger)]">
                      <AlertTriangle className="mt-1 size-3.5 shrink-0" />
                      <span>{runError}</span>
                    </div>
                    {lastMessage && !isRunning && (
                      <button
                        className="mt-2 text-xs font-medium text-[var(--color-accent)] hover:underline"
                        onClick={() => setMessage(lastMessage)}
                        type="button"
                      >
                        重新填写这条请求
                      </button>
                    )}
                  </div>
                )}

                {(messagesQuery.data ?? []).length === 0 && !isRunning && !runError && (
                  <div className="rounded-[7px] border border-dashed border-[var(--color-border-strong)] px-3 py-4 text-center text-xs leading-5 text-[var(--color-text-muted)]">
                    助理只提出建议；应用 Prompt、首帧或尾帧都需要你明确确认。
                  </div>
                )}
              </div>

              <div className="mt-3 rounded-[7px] border border-[var(--color-border-strong)] bg-white p-2">
                <textarea
                  aria-label="向 Oneiroi 助理发送消息"
                  className="min-h-[68px] w-full resize-none bg-transparent px-1 text-sm leading-6 outline-none placeholder:text-[var(--color-text-faint)]"
                  disabled={isRunning}
                  onChange={(event) => setMessage(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.shiftKey) {
                      event.preventDefault();
                      void sendMessage();
                    }
                  }}
                  placeholder="让助理优化 Prompt、分析参考帧，或提出参考图方案…"
                  value={message}
                />
                <div className="mt-1.5 flex flex-wrap items-center gap-1.5 border-t border-[var(--color-border)] pt-2">
                  {attachedAssetIds.length > 0 ? (
                    <span className="inline-flex items-center gap-1 text-[10px] text-[var(--color-text-muted)]">
                      <Paperclip className="size-3" /> 已附带 {attachedAssetIds.length} 张参考图
                    </span>
                  ) : draft.firstFrame || draft.lastFrame ? (
                    <span className="text-[10px] text-[var(--color-warning)]">
                      当前模型未开放图片理解，参考帧不会发送
                    </span>
                  ) : null}
                  <div className="ml-auto flex items-center gap-1.5">
                    {isRunning && activeRun && activeRun.status !== "waiting_approval" && (
                      <Button
                        aria-label="停止 Oneiroi 助理"
                        disabled={cancelRun.isPending}
                        onClick={() => cancelRun.mutate(activeRun.id)}
                        size="icon"
                        type="button"
                        variant="ghost"
                      >
                        <Square className="size-3.5 fill-current" />
                      </Button>
                    )}
                    <Button
                      aria-label="发送给 Oneiroi 助理"
                      disabled={!message.trim() || isRunning || createRun.isPending}
                      onClick={() => void sendMessage()}
                      size="icon"
                      type="button"
                      variant="primary"
                    >
                      {createRun.isPending ? (
                        <LoaderCircle className="size-4 animate-spin" />
                      ) : (
                        <Send className="size-4" />
                      )}
                    </Button>
                  </div>
                </div>
              </div>

              <div className="mt-2 flex flex-wrap gap-1.5">
                <QuickPrompt
                  icon={<WandSparkles className="size-3" />}
                  label="优化当前 Prompt"
                  onClick={() => setMessage("请优化当前 Prompt，并给出可以明确确认的草稿修改建议。")}
                />
                {capabilities.data?.imageInput && attachedAssetIds.length > 0 && (
                  <QuickPrompt
                    icon={<ImageIcon className="size-3" />}
                    label="分析参考帧"
                    onClick={() => setMessage("请分析当前参考帧与 Prompt 的一致性，并提出改进建议。")}
                  />
                )}
                {imageToolAvailable && (
                  <QuickPrompt
                    icon={<Sparkles className="size-3" />}
                    label="生成首帧参考图"
                    onClick={() => setMessage("请根据当前 Prompt 生成一张首帧参考图。")}
                  />
                )}
              </div>

              {stream.reconnecting && isRunning && (
                <p className="mt-2 text-[10px] text-[var(--color-warning)]">
                  事件流正在重连，已从最后确认的事件继续，不会重复审批。
                </p>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.section>
  );
}

function QuickPrompt({
  icon,
  label,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      className="inline-flex items-center gap-1 rounded-[4px] border border-[var(--color-border)] bg-[var(--color-canvas)] px-2 py-1 text-[10px] text-[var(--color-text-muted)] transition-colors hover:bg-[var(--color-surface-muted)] hover:text-[var(--color-text)]"
      onClick={onClick}
      type="button"
    >
      {icon}
      {label}
    </button>
  );
}

function ApprovalCard({
  pending,
  disabled,
  decisionError,
  onApprove,
  onReject,
}: {
  pending: PendingApproval;
  disabled: boolean;
  decisionError: string;
  onApprove: () => void;
  onReject: () => void;
}) {
  const argumentsValue = pending.toolCall.arguments;
  const purpose = purposeLabel(argumentsValue.purpose);
  const ratio = typeof argumentsValue.ratio === "string" ? argumentsValue.ratio : "—";
  const count = typeof argumentsValue.count === "number" ? argumentsValue.count : 1;
  const references = Array.isArray(argumentsValue.referenceAssetIds)
    ? argumentsValue.referenceAssetIds.length
    : 0;
  return (
    <div
      aria-label="Agent 图片生成审批"
      className="rounded-[7px] border border-[var(--color-warning)]/30 bg-[var(--color-warning)]/6 p-3"
      role="group"
    >
      <div className="flex items-start gap-2">
        <span className="grid size-7 shrink-0 place-items-center rounded-[5px] bg-[var(--color-warning)]/12 text-[var(--color-warning)]">
          <ShieldCheck className="size-3.5" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold">确认生成参考图片</p>
          <p className="mt-0.5 text-[11px] text-[var(--color-text-muted)]">
            参数已由服务端锁定；如需修改，请拒绝后重新发送请求。
          </p>
        </div>
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 rounded-[5px] border border-[var(--color-border)] bg-white/70 p-2.5 text-xs sm:grid-cols-4">
        <ReadOnlyField label="用途" value={purpose} />
        <ReadOnlyField label="比例" value={ratio} />
        <ReadOnlyField label="数量" value={`${count} 张`} />
        <ReadOnlyField label="参考图" value={references > 0 ? `${references} 张` : "无"} />
      </dl>
      {pending.approval.estimatedCost && (
        <p className="mt-2 text-[11px] text-[var(--color-text-muted)]">
          预计成本：{pending.approval.estimatedCost}
        </p>
      )}
      {decisionError && <p className="mt-2 text-xs text-[var(--color-danger)]">{decisionError}</p>}
      <div className="mt-3 flex gap-2">
        <Button disabled={disabled} onClick={onApprove} size="sm" type="button" variant="primary">
          <Check className="size-3.5" /> 同意生成
        </Button>
        <Button disabled={disabled} onClick={onReject} size="sm" type="button" variant="ghost">
          <X className="size-3.5" /> 拒绝
        </Button>
      </div>
    </div>
  );
}

function ReadOnlyField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[9px] uppercase tracking-[0.08em] text-[var(--color-text-faint)]">{label}</dt>
      <dd className="mt-0.5 font-medium">{value}</dd>
    </div>
  );
}

function DraftProposalCard({
  proposal,
  rationale,
  warnings,
  applied,
  onApply,
}: {
  proposal: AgentDraftProposal;
  rationale: string[];
  warnings: string[];
  applied: boolean;
  onApply: () => void;
}) {
  const changes = proposalLabels(proposal);
  return (
    <div className="mt-2.5 border-t border-[var(--color-accent)]/12 pt-2.5">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs font-semibold text-[var(--color-accent)]">草稿修改建议</p>
        <span className="text-[10px] text-[var(--color-text-faint)]">{changes.length} 项</span>
      </div>
      <ul className="mt-1.5 space-y-1 text-xs text-[var(--color-text-muted)]">
        {changes.map((change) => (
          <li className="flex gap-2" key={change}>
            <span className="text-[var(--color-accent)]">·</span>
            <span>{change}</span>
          </li>
        ))}
      </ul>
      {rationale.length > 0 && (
        <p className="mt-2 text-[11px] text-[var(--color-text-faint)]">{rationale.join("；")}</p>
      )}
      {warnings.map((warning) => (
        <p className="mt-1 text-[11px] text-[var(--color-warning)]" key={warning}>
          {warning}
        </p>
      ))}
      <Button className="mt-2.5" disabled={applied} onClick={onApply} size="sm" type="button" variant="secondary">
        {applied ? <CheckCircle2 className="size-3.5" /> : <WandSparkles className="size-3.5" />}
        {applied ? "已应用" : "应用到草稿"}
      </Button>
    </div>
  );
}

function ImageResultCard({
  result,
  assets,
  savedAssets,
  onApply,
  onSave,
}: {
  result: AgentImageResult;
  assets: StudioAsset[];
  savedAssets: Set<string>;
  onApply: (candidate: AgentImageCandidate, target: "firstFrame" | "lastFrame") => void;
  onSave: (assetId: string) => void;
}) {
  return (
    <div
      aria-label="Agent 参考图候选"
      className="rounded-[7px] border border-[var(--color-border)] bg-white/78 p-3"
      role="group"
    >
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold">参考图候选</p>
          <p className="text-[11px] text-[var(--color-text-muted)]">
            已安全保存为资产，不会自动替换草稿。
          </p>
        </div>
        <span className="rounded-[4px] bg-[var(--color-surface-muted)] px-1.5 py-0.5 text-[10px] text-[var(--color-text-muted)]">
          {purposeLabel(result.purpose)}
        </span>
      </div>
      <div className={cn("mt-3 grid gap-2.5", result.assets.length > 1 && "sm:grid-cols-2") }>
        {result.assets.map((candidate) => {
          const stored = assets.find((asset) => asset.id === candidate.id);
          const previewUrl = stored?.previewUrl ?? apiUrl(`/v1/assets/${candidate.id}/file`);
          const saved = savedAssets.has(candidate.id);
          return (
            <article className="overflow-hidden rounded-[6px] border border-[var(--color-border)]" key={candidate.id}>
              <img alt={candidate.title} className="aspect-video w-full bg-[var(--color-surface-muted)] object-cover" src={previewUrl} />
              <div className="p-2.5">
                <p className="truncate text-xs font-semibold">{candidate.title}</p>
                <p className="mt-0.5 text-[10px] text-[var(--color-text-faint)]">
                  {candidate.width && candidate.height ? `${candidate.width} × ${candidate.height}` : "PNG"}
                </p>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {result.purpose !== "style-reference" && (
                    <>
                      <Button onClick={() => onApply(candidate, "firstFrame")} size="sm" type="button" variant="secondary">
                        设为首帧
                      </Button>
                      <Button onClick={() => onApply(candidate, "lastFrame")} size="sm" type="button" variant="secondary">
                        设为尾帧
                      </Button>
                    </>
                  )}
                  <Button disabled={saved} onClick={() => onSave(candidate.id)} size="sm" type="button" variant="ghost">
                    {saved ? <Check className="size-3.5" /> : null}
                    {saved ? "已保存" : "仅保存"}
                  </Button>
                </div>
              </div>
            </article>
          );
        })}
      </div>
      {result.partial && (
        <p className="mt-2 flex items-center gap-1.5 text-[11px] text-[var(--color-warning)]">
          <AlertTriangle className="size-3" /> 部分图片生成失败，已保留成功结果。
        </p>
      )}
      {result.errorCode && !result.partial && (
        <p className="mt-2 text-[11px] text-[var(--color-danger)]">
          {friendlyAgentError(result.errorCode)}
        </p>
      )}
    </div>
  );
}

function proposalPatch(
  proposal: AgentDraftProposal,
  assets: StudioAsset[],
): Partial<GenerationDraft> {
  const patch: Partial<GenerationDraft> = {};
  if (proposal.prompt != null) patch.prompt = proposal.prompt;
  if (proposal.negativePrompt != null) patch.negativePrompt = proposal.negativePrompt;
  if (proposal.ratio != null) patch.ratio = proposal.ratio;
  if (proposal.resolution != null) patch.resolution = proposal.resolution;
  if (proposal.duration != null) patch.duration = proposal.duration;
  if (proposal.seed != null) patch.seed = proposal.seed;
  if (proposal.firstStrength != null) patch.firstStrength = proposal.firstStrength;
  if (proposal.lastStrength != null) patch.lastStrength = proposal.lastStrength;
  if (proposal.firstFrameAssetId !== undefined) {
    patch.firstFrame = assetReference(proposal.firstFrameAssetId, assets);
  }
  if (proposal.lastFrameAssetId !== undefined) {
    patch.lastFrame = assetReference(proposal.lastFrameAssetId, assets);
  }
  return patch;
}

function assetReference(assetId: string | null, assets: StudioAsset[]) {
  if (!assetId) return null;
  const asset = assets.find((item) => item.id === assetId);
  return {
    assetId,
    name: asset?.title ?? "Agent 参考图",
    url: asset?.previewUrl ?? apiUrl(`/v1/assets/${assetId}/file`),
  };
}

function proposalLabels(proposal: AgentDraftProposal): string[] {
  const labels: string[] = [];
  if (proposal.prompt != null) labels.push("更新 Prompt");
  if (proposal.negativePrompt != null) labels.push("更新负向提示词");
  if (proposal.ratio != null) labels.push(`画面比例 ${proposal.ratio}`);
  if (proposal.resolution != null) labels.push(`分辨率 ${proposal.resolution}`);
  if (proposal.duration != null) labels.push(`时长 ${proposal.duration} 秒`);
  if (proposal.seed != null) labels.push(`随机种子 ${proposal.seed}`);
  if (proposal.firstStrength != null) labels.push("调整首帧强度");
  if (proposal.lastStrength != null) labels.push("调整尾帧强度");
  if (proposal.firstFrameAssetId !== undefined) labels.push("更新首帧资产");
  if (proposal.lastFrameAssetId !== undefined) labels.push("更新尾帧资产");
  return labels;
}

function readToolCall(value: unknown): AgentToolCall | null {
  if (!isRecord(value) || typeof value.id !== "string" || typeof value.toolName !== "string") {
    return null;
  }
  return value as unknown as AgentToolCall;
}

function readApproval(value: unknown): AgentApproval | null {
  if (!isRecord(value) || typeof value.id !== "string" || typeof value.toolCallId !== "string") {
    return null;
  }
  return value as unknown as AgentApproval;
}

function readImageResult(toolCall: AgentToolCall): AgentImageResult | null {
  if (!isRecord(toolCall.result) || !Array.isArray(toolCall.result.assets)) return null;
  const candidates = toolCall.result.assets
    .filter(
      (asset): asset is Record<string, unknown> =>
        isRecord(asset) &&
        asset.type === "image" &&
        typeof asset.id === "string" &&
        typeof asset.title === "string" &&
        typeof asset.mediaType === "string",
    )
    .map((asset) => ({
      id: asset.id as string,
      type: "image" as const,
      title: asset.title as string,
      mediaType: asset.mediaType as string,
      sizeBytes: typeof asset.sizeBytes === "number" ? asset.sizeBytes : undefined,
      width: typeof asset.width === "number" ? asset.width : null,
      height: typeof asset.height === "number" ? asset.height : null,
    }));
  const purpose = readPurpose(toolCall.arguments.purpose);
  if (!purpose || candidates.length === 0) return null;
  return {
    toolCallId: toolCall.id,
    purpose,
    assets: candidates,
    partial: toolCall.result.partial === true,
    errorCode: typeof toolCall.result.errorCode === "string" ? toolCall.result.errorCode : null,
  };
}

function readPurpose(value: unknown): AgentImageResult["purpose"] | null {
  return value === "first-frame" || value === "last-frame" || value === "style-reference"
    ? value
    : null;
}

function purposeLabel(value: unknown) {
  if (value === "last-frame") return "尾帧";
  if (value === "style-reference") return "风格参考";
  return "首帧";
}

function extractVisibleAgentText(buffer: string): string {
  try {
    const parsed = JSON.parse(buffer) as unknown;
    return isRecord(parsed) && typeof parsed.text === "string" ? parsed.text : "";
  } catch {
    return "";
  }
}

function friendlyAgentError(code: string, fallback?: string | null) {
  return errorCopy[code] ?? fallback ?? "Oneiroi 助理任务失败，请重新发起一次请求。";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
