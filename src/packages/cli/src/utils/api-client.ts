import { loadConfig } from "./config";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface ScanRequest {
  path: string;
  framework?: string;
  rules?: string[];
  use_llm?: boolean;
  llm_provider?: string;
}

export interface FixRequest {
  path: string;
  scan_id?: string;
  violation_ids?: string[];
  dry_run?: boolean;
}

export interface Violation {
  id: string;
  rule: string;
  severity: "critical" | "serious" | "moderate" | "minor";
  element: string;
  description: string;
  suggestion: string;
  code_snippet?: string;
  location?: { file: string; line: number; column: number };
  confidence: number;
  fix_available: boolean;
  ai_generated: boolean;
  wcag_criterion?: string;
}

export interface ScanResult {
  scan_id: string;
  target: string;
  framework: string;
  violations: Violation[];
  total_files_scanned: number;
  scan_duration_ms: number;
  llm_provider?: string;
  created_at?: string;
}

export interface Fix {
  violation_id: string;
  file: string;
  original_code: string;
  fixed_code: string;
  description: string;
  applied: boolean;
  diff?: string;
}

export interface FixResponse {
  fixes_applied: number;
  fixes_skipped: number;
  fixes: Fix[];
  errors: string[];
}

export interface HealthResponse {
  status: string;
  version: string;
  llm_available: boolean;
  llm_provider?: string;
}

// ── Client ────────────────────────────────────────────────────────────────────

export class VeraApiClient {
  private baseUrl: string;

  constructor(baseUrl?: string) {
    this.baseUrl = baseUrl ?? loadConfig().backend_url ?? "http://localhost:8000";
  }

  private async request<T>(
    method: string,
    endpoint: string,
    body?: object
  ): Promise<T> {
    const url = `${this.baseUrl}${endpoint}`;
    const options: RequestInit = {
      method,
      headers: { "Content-Type": "application/json" },
    };
    if (body) options.body = JSON.stringify(body);

    let res: Response;
    try {
      res = await fetch(url, options);
    } catch (err: any) {
      throw new Error(
        `Cannot reach Vera backend at ${this.baseUrl}. Is it running?\n` +
          `Start with: docker-compose up -d\n` +
          `Or: cd src/packages/core && uvicorn vera.api:app --reload`
      );
    }

    if (!res.ok) {
      const text = await res.text();
      let detail = text;
      try {
        detail = JSON.parse(text).detail ?? text;
      } catch {}
      throw new Error(`API error ${res.status}: ${detail}`);
    }

    return res.json() as Promise<T>;
  }

  async health(): Promise<HealthResponse> {
    return this.request<HealthResponse>("GET", "/health");
  }

  async scan(req: ScanRequest): Promise<ScanResult> {
    return this.request<ScanResult>("POST", "/scan", req);
  }

  async fix(req: FixRequest): Promise<FixResponse> {
    return this.request<FixResponse>("POST", "/fix", req);
  }

  async getReport(scanId: string): Promise<ScanResult> {
    return this.request<ScanResult>("GET", `/report/${scanId}`);
  }

  async listReports(): Promise<object[]> {
    return this.request<object[]>("GET", "/reports");
  }

  async describe(req: DescribeRequest): Promise<DescribeResponse> {
    return this.request<DescribeResponse>("POST", "/describe", req);
  }
}

// ── Vera-Describe (opt-in) ─────────────────────────────────────────────────────

export interface DescribeRequest {
  path: string;
  api_key?: string;
  model?: string;
}

export interface AltEvaluation {
  src: string;
  file: string;
  line: number;
  role: string;
  verdict: "pass" | "weak" | "missing" | "skipped";
  score: number;
  reasons: string[];
  existing_alt?: string | null;
  suggested_alt?: string | null;
  note?: string | null;
}

export interface DescribeResponse {
  target: string;
  images_found: number;
  summary: { pass: number; weak: number; missing: number; skipped: number };
  evaluations: AltEvaluation[];
  human_summary: string;
}

// ── Singleton ─────────────────────────────────────────────────────────────────

export function createClient(backendUrl?: string): VeraApiClient {
  return new VeraApiClient(backendUrl);
}
