export type Option = { name: string; description?: string; label?: string };
export type ModelOption = { id: string; label: string | null };

export type Options = {
  disclaimer: string;
  demo_notice: string | null;
  examples: string[];
  default_strategy: string;
  strategies: Option[];
  answer_models: ModelOption[];
  answering_modes: Option[];
};

export type Jurisdiction = "EU" | "DE" | "US";

export type FounderProfile = {
  stage: "idea" | "pre_incorporation" | "incorporated_pre_revenue" | "revenue_or_seed";
  company_seat: "DE" | "other_eu" | "none";
  target_markets: Jurisdiction[];
  ai_involvement: "none" | "internal_tools" | "product_on_third_party_model" | "trains_or_finetunes" | "offers_gpai_model";
  customers: "b2b" | "b2c" | "both";
  children_possible: boolean;
  headcount: "1-9" | "10-49" | "50-249" | "250+";
  revenue: "<2m" | "2-10m" | "10-50m" | ">50m";
};

export type Settings = {
  strategy: string;
  answerModel: string;
  answeringMode: string;
  jurisdictions: Jurisdiction[];
  profile: FounderProfile | null;
};

export type Hit = {
  n: number;
  label: string;
  source_id: string;
  source_title: string;
  tier: number;
  jurisdiction: string;
  legal_status: string;
  language: string;
  url: string | null;
  score: number;
  excerpt: string;
};

export type ProgressEvent = { type: "progress"; step: string; label: string };

export type RetrievalEvent = {
  type: "retrieval";
  strategy: string;
  query: string;
  queries: { text: string; language: string | null }[];
  candidates: number;
  reranked: boolean;
  hits: Hit[];
};

export type GuardEvent = {
  type: "guard";
  personal_data: string[];
  triggers: { id: number; label: string; urgent: boolean }[];
  tax_question: boolean;
  method: string;
};

export type ToolEvent = {
  type: "tool";
  name: string;
  args: Record<string, unknown>;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  result: any;
};

export type AnswerEvent = {
  type: "answer";
  text: string;
  citations: { cited: number[]; invalid: number[]; ok: boolean };
  usage: { input_tokens: number; output_tokens: number; total_tokens: number; cost_usd?: number | null };
  answering_mode: string;
  escalations: number[];
  strategy: string;
  disclaimer: string;
};

export type ChatEvent =
  | ProgressEvent
  | RetrievalEvent
  | AnswerEvent
  | GuardEvent
  | ToolEvent
  | { type: "token"; text: string }
  | { type: "error"; message: string }
  | { type: "done"; disclaimer: string };

export type Turn = {
  id: string;
  question: string;
  settings: Settings;
  status: "streaming" | "done" | "error";
  progress: ProgressEvent[];
  searches: RetrievalEvent[];
  tools: ToolEvent[];
  guard?: GuardEvent;
  draft: string;
  answer?: AnswerEvent;
  error?: string;
};

export type ChangeRecord = {
  id: number;
  source_id: string;
  source: string;
  jurisdiction: string | null;
  tier: number | null;
  url: string | null;
  language: string;
  kind: "added" | "changed";
  status: "applied" | "review_needed" | "approved" | "rejected";
  old_version: string | null;
  new_version: string;
  summary: { added: string[]; removed: string[]; modified: string[] };
  detected_at: string;
  decided_at: string | null;
};

export type UpdateEvent =
  | { type: "progress"; source_id: string; position: number; total: number }
  | { type: "failed"; source_id: string; error: string }
  | ({ type: "change" } & Omit<ChangeRecord, "source" | "jurisdiction" | "tier" | "url">)
  | { type: "summary"; unchanged: number; applied: number; review_needed: number; failed: { source_id: string; error: string }[] }
  | { type: "error"; message: string }
  | { type: "done" };

export type Dashboard = {
  coverage: { legal_area: string; jurisdiction: string; depth: string; required: number; indexed: number; missing: string[] }[];
  usage: {
    requests: number;
    errors: number;
    cost_usd: number;
    escalations: number;
    gap_signals: number;
    by_model: Record<string, { requests: number; cost_usd: number; tokens: number; median_seconds: number | null }>;
  };
  gap_signals: { at: string; question: string; signal: string; strategy: string }[];
  evaluations: {
    file: string;
    reviewed_only: boolean;
    runs: Record<string, string | number | null>[];
  }[];
  pending_reviews: number;
};
