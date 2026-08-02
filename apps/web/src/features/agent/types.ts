import type { components } from "@/generated/gateway";

export type AgentCapabilities = components["schemas"]["AgentCapabilitiesResponse"];
export type AgentRun = components["schemas"]["AgentRunResponse"];
export type AgentThread = components["schemas"]["AgentThreadResponse"];
export type AgentMessage = components["schemas"]["AgentMessageResponse"];
export type AgentToolCall = components["schemas"]["AgentToolCallResponse"];
export type AgentApproval = components["schemas"]["AgentApprovalResponse"];
export type AgentToolDecision = components["schemas"]["AgentToolDecisionResponse"];
export type AgentDraftProposal = components["schemas"]["DraftProposal"];

export type AgentEvent = {
  id: string;
  type: string;
  runId: string;
  threadId: string;
  sequence: number;
  data: Record<string, unknown>;
};

export type AgentImageCandidate = {
  id: string;
  type: "image";
  title: string;
  mediaType: string;
  sizeBytes?: number;
  width?: number | null;
  height?: number | null;
};

export type AgentImageResult = {
  toolCallId: string;
  purpose: "first-frame" | "last-frame" | "style-reference";
  assets: AgentImageCandidate[];
  partial: boolean;
  errorCode: string | null;
};
