export interface BaseData {
  type: string;
}

export interface BasicData extends BaseData {
  type: 'basic';
  content: string;
}

export interface LanggraphButtonData extends BaseData {
  type: 'langgraphButton';
  link: string;
}

export interface DifferencesData extends BaseData {
  type: 'differences';
  content: string;
  output: string;
}

export interface QuestionData extends BaseData {
  type: 'question';
  content: string;
}

export interface ChatData extends BaseData {
  type: 'chat';
  content: string;
  metadata?: any; // For storing search results and other contextual information
}

export interface ClarificationRequestData extends BaseData {
  type: 'clarification_request';
  request_id: string;
  stage: 'subqueries';
  query?: string;
  generated_subqueries: string[];
  clarification_questions: string[];
  defaults?: ClarificationConstraints;
}

export interface ClarificationConstraints {
  scope: string | null;
  time_window: string | null;
  language: string | null;
  output_preference: string | null;
}

export interface ClarificationRequestPayload {
  request_id: string;
  stage: 'subqueries';
  query?: string;
  generated_subqueries: string[];
  clarification_questions: string[];
  defaults?: ClarificationConstraints;
}

export interface ClarificationResponsePayload {
  request_id: string;
  approved_subqueries: string[];
  constraints: ClarificationConstraints;
  notes: string | null;
}

export type Data =
  | BasicData
  | LanggraphButtonData
  | DifferencesData
  | QuestionData
  | ChatData
  | ClarificationRequestData;

export interface MCPConfig {
  name: string;
  command: string;
  args: string[];
  env: Record<string, string>;
}

export interface ChatBoxSettings {
  report_type: string;
  report_source: string;
  tone: string;
  domains: string[];
  defaultReportType: string;
  layoutType: string;
  mcp_enabled: boolean;
  mcp_configs: MCPConfig[];
  mcp_strategy?: string;
  medical_mode: boolean;
  medical_collection?: string;
}

export interface Domain {
  value: string;
}

export interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
  timestamp?: number;
  metadata?: any; // For storing search results and other contextual information
}

export interface ResearchHistoryItem {
  id: string;
  question: string;
  answer: string;
  timestamp: number;
  orderedData: Data[];
  chatMessages?: ChatMessage[];
} 
