export type Role = "owner" | "admin" | "member" | "viewer";

export interface Me {
  id: string;
  email: string;
  name: string;
  organizations: { id: string; name: string; slug: string; role: Role; plan: string }[];
}

export interface Project {
  id: string;
  organization_id: string;
  name: string;
  description: string;
  base_url: string | null;
  created_at: string;
  test_count: number;
  last_execution: { id: string; status: string; created_at: string; passed: number; failed: number; total: number } | null;
}

export interface Target {
  strategy: string;
  value: string;
  name?: string;
  exact?: boolean;
}

export interface Step {
  id?: string;
  action: string;
  target: Target | null;
  value: string | null;
  options: Record<string, any>;
  description: string;
}

export interface ValidationMessage {
  level: "error" | "warning" | "info";
  code: string;
  message: string;
  step: number | null;
}

export interface TestCase {
  id: string;
  project_id: string;
  title: string;
  description: string;
  kind: "ui" | "api";
  category: string;
  priority: "high" | "medium" | "low";
  status: "draft" | "generated" | "ready" | "archived";
  source: string;
  source_ref: string | null;
  expectation_basis: string;
  tags: string[];
  validation_status: string;
  validation_messages: ValidationMessage[];
  version: number;
  created_at: string;
  updated_at: string;
  step_count: number;
  last_result: { status: string; execution_id: string; at: string } | null;
  steps?: Step[];
}

export interface Execution {
  id: string;
  project_id: string;
  status: string;
  trigger: string;
  browser: string;
  headless: boolean;
  workers: number;
  retries: number;
  timeout_ms: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  total: number;
  passed: number;
  failed: number;
  skipped: number;
  flaky: number;
  error_message: string | null;
}

export interface Failure {
  category: string;
  label: string;
  confidence: number;
  summary: string;
  evidence: { verified: string[]; hypotheses: string[]; next_actions: string[]; label: string };
}

export interface Artifact {
  id: string;
  kind: string;
  name: string;
  content_type: string;
  size_bytes: number;
  url: string;
}

export interface HealingSuggestion {
  id: string;
  original_target: Target;
  suggested_target: Target;
  confidence: number;
  rationale: string;
  status: "pending" | "accepted" | "rejected";
}

export interface Result {
  id: string;
  execution_id: string;
  test_case_id: string | null;
  test_title: string;
  status: string;
  browser: string;
  duration_ms: number | null;
  retries_used: number;
  error_message: string | null;
  failed_step_index: number | null;
  failure: Failure | null;
  error_stack?: string | null;
  step_results?: { title: string; duration_ms: number; status: string; error: string | null }[];
  generated_code?: string | null;
  log?: string | null;
  artifacts?: Artifact[];
  healing_suggestions?: HealingSuggestion[];
}

export interface ExecutionDetail extends Execution {
  results: Result[];
  summary: { pass_rate: number; failure_categories: Record<string, number>; slowest: { title: string; duration_ms: number }[] };
  recommendations: string[];
  reports: Artifact[];
}

export interface Environment {
  id: string;
  name: string;
  base_url: string | null;
  is_default: boolean;
  variables: { id: string; key: string; is_secret: boolean; value: string | null; has_value: boolean }[];
}

export interface DiscoveredPage {
  id: string;
  url: string;
  title: string;
  status_code: number | null;
  depth: number;
  requires_login: boolean;
  screenshot_url: string | null;
  headings: { level: number; text: string }[];
  forms: { name: string; fields: { label: string; type: string; required: boolean }[] }[];
  links: { text: string; href: string; in_nav: boolean }[];
  buttons: { text: string }[];
  tables: { caption: string; headers: string[] }[];
  counts: { forms: number; links: number; buttons: number; tables: number; fields: number };
}

export interface Discovery {
  id: string;
  url: string;
  status: string;
  page_count: number;
  uses_login: boolean;
  login_result: { success: boolean; landed_on?: string; error?: string } | null;
  skipped: { url: string; reason: string }[];
  error_message: string | null;
  created_at: string;
  pages?: DiscoveredPage[];
}

export interface Job {
  id: string;
  kind: string;
  status: string;
  engine: string;
  model: string | null;
  result: { created?: number; test_case_ids?: string[]; invalid?: number; ai?: { used: boolean; error?: string; model?: string; added?: number; rejected?: { title: string; reason: string }[] } };
  error_message: string | null;
}

export interface Endpoint {
  id: string;
  method: string;
  path: string;
  summary: string;
  tags: string[];
  responses: Record<string, { description: string; has_schema: boolean }>;
  requires_auth: boolean;
  parameters: { name: string; in: string; required: boolean }[];
}

export interface Collection {
  id: string;
  name: string;
  source_type: string;
  base_url: string | null;
  endpoint_count: number;
  created_at: string;
  endpoints?: Endpoint[];
  security_schemes: Record<string, any>;
}

export interface Dashboard {
  projects: number;
  tests: number;
  executions: number;
  results: { passed: number; failed: number; total: number };
  pass_rate: number | null;
  trend: { date: string; passed: number; failed: number }[];
  recent: { id: string; project_id: string; status: string; total: number; passed: number; failed: number; browser: string; created_at: string; duration_ms: number | null }[];
  failure_categories: Record<string, number>;
  flaky_tests: { test_case_id: string; title: string; runs: number; passed: number; failed: number }[];
  critical_failures: { test_case_id: string; title: string; execution_id: string; category: string }[];
  recommendations: string[];
}

export interface StepAction {
  action: string;
  label: string;
  target: "required" | "optional" | "none";
  value: "required" | "optional" | "none";
  kind: string;
  assertion: boolean;
  value_label: string;
  help: string;
}

export interface Plan {
  kind: "plan";
  title: string;
  steps: Step[];
  interpretation: { clause: string; steps: number[]; note: string }[];
  questions: string[];
  prerequisites: { variable: string; description: string; secret: boolean }[];
  warnings: string[];
  engine: string;
  model: string | null;
  validation: { status: string; messages: ValidationMessage[] };
  test_case_id?: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  payload: any;
  created_at: string;
}
