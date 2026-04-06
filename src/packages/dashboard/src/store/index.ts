import { configureStore, createSlice, PayloadAction, createAsyncThunk } from "@reduxjs/toolkit";

// ── Types ─────────────────────────────────────────────────────────────────────

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

export interface VeraState {
  scan: ScanResult | null;
  reports: ScanResult[];
  fixes: Fix[];
  loading: boolean;
  fixing: boolean;
  error: string | null;
  selectedViolation: Violation | null;
  fixPreview: Fix | null;
  backendUrl: string;
  scanPath: string;
}

// ── Initial State ─────────────────────────────────────────────────────────────

const initialState: VeraState = {
  scan: null,
  reports: [],
  fixes: [],
  loading: false,
  fixing: false,
  error: null,
  selectedViolation: null,
  fixPreview: null,
  backendUrl: (import.meta as any).env?.VITE_BACKEND_URL ?? "http://localhost:8000",
  scanPath: "./src",
};

// ── API helpers ───────────────────────────────────────────────────────────────

function apiUrl(state: VeraState, endpoint: string): string {
  return `${state.backendUrl}${endpoint}`;
}

// ── Thunks ────────────────────────────────────────────────────────────────────

export const runScan = createAsyncThunk(
  "vera/runScan",
  async ({ path, useLlm }: { path: string; useLlm: boolean }, { getState, rejectWithValue }) => {
    const state = (getState() as { vera: VeraState }).vera;
    try {
      const res = await fetch(apiUrl(state, "/scan"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path, use_llm: useLlm }),
      });
      if (!res.ok) {
        const err = await res.json();
        return rejectWithValue(err.detail ?? "Scan failed");
      }
      return (await res.json()) as ScanResult;
    } catch (e: any) {
      return rejectWithValue(e.message ?? "Network error");
    }
  }
);

export const runFix = createAsyncThunk(
  "vera/runFix",
  async (
    { path, scanId, violationIds, dryRun }: { path: string; scanId?: string; violationIds?: string[]; dryRun: boolean },
    { getState, rejectWithValue }
  ) => {
    const state = (getState() as { vera: VeraState }).vera;
    try {
      const res = await fetch(apiUrl(state, "/fix"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path, scan_id: scanId, violation_ids: violationIds, dry_run: dryRun }),
      });
      if (!res.ok) {
        const err = await res.json();
        return rejectWithValue(err.detail ?? "Fix failed");
      }
      return await res.json();
    } catch (e: any) {
      return rejectWithValue(e.message ?? "Network error");
    }
  }
);

export const loadReports = createAsyncThunk(
  "vera/loadReports",
  async (_, { getState, rejectWithValue }) => {
    const state = (getState() as { vera: VeraState }).vera;
    try {
      const res = await fetch(apiUrl(state, "/reports"));
      if (!res.ok) return rejectWithValue("Failed to load reports");
      return await res.json();
    } catch (e: any) {
      return rejectWithValue(e.message);
    }
  }
);

// ── Slice ─────────────────────────────────────────────────────────────────────

const veraSlice = createSlice({
  name: "vera",
  initialState,
  reducers: {
    selectViolation: (state, action: PayloadAction<Violation | null>) => {
      state.selectedViolation = action.payload;
    },
    setFixPreview: (state, action: PayloadAction<Fix | null>) => {
      state.fixPreview = action.payload;
    },
    clearError: (state) => {
      state.error = null;
    },
    setBackendUrl: (state, action: PayloadAction<string>) => {
      state.backendUrl = action.payload;
    },
    setScanPath: (state, action: PayloadAction<string>) => {
      state.scanPath = action.payload;
    },
  },
  extraReducers: (builder) => {
    builder
      // runScan
      .addCase(runScan.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(runScan.fulfilled, (state, action) => {
        state.loading = false;
        state.scan = action.payload;
      })
      .addCase(runScan.rejected, (state, action) => {
        state.loading = false;
        state.error = action.payload as string;
      })
      // runFix
      .addCase(runFix.pending, (state) => {
        state.fixing = true;
        state.error = null;
      })
      .addCase(runFix.fulfilled, (state, action) => {
        state.fixing = false;
        state.fixes = action.payload.fixes ?? [];
      })
      .addCase(runFix.rejected, (state, action) => {
        state.fixing = false;
        state.error = action.payload as string;
      })
      // loadReports
      .addCase(loadReports.fulfilled, (state, action) => {
        state.reports = action.payload;
      });
  },
});

export const {
  selectViolation,
  setFixPreview,
  clearError,
  setBackendUrl,
  setScanPath,
} = veraSlice.actions;

// ── Store ─────────────────────────────────────────────────────────────────────

export const store = configureStore({
  reducer: { vera: veraSlice.reducer },
});

export type RootState = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;
