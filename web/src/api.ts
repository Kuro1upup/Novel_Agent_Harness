import type {
  AgentRun,
  AuthUser,
  BillingBalance,
  BillingBills,
  BillingUsage,
  BibleDiff,
  Draft,
  ManuscriptChapter,
  ManuscriptOutline,
  ManuscriptPreview,
  ManuscriptVolume,
  MemoryHit,
  PlotPlan,
  Project,
  QualityIssue,
  QualityIssueList,
  StoryBible,
  StoryBibleVersionSummary,
  Workflow,
  WorkflowDetail,
} from './types'

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ||
  'http://localhost:8000'
const TOKEN_KEY = 'novel-harness-token'

let accessToken = window.localStorage.getItem(TOKEN_KEY) || ''

export const authSession = {
  hasToken: () => Boolean(accessToken),
  setToken: (token: string) => {
    accessToken = token
    window.localStorage.setItem(TOKEN_KEY, token)
  },
  clear: () => {
    accessToken = ''
    window.localStorage.removeItem(TOKEN_KEY)
  },
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message)
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      ...init?.headers,
    },
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    if (response.status === 401 && !path.endsWith('/login')) {
      authSession.clear()
      window.dispatchEvent(new Event('auth-expired'))
    }
    throw new ApiError(
      payload?.message || payload?.detail || payload?.error || `请求失败（${response.status}）`,
      response.status,
    )
  }
  return response.json() as Promise<T>
}

export const api = {
  login: (login: string, password: string) =>
    request<{ success: boolean; token: string; user: AuthUser }>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ login, password }),
    }),
  me: () => request<{ success: boolean; user: AuthUser }>('/api/auth/me'),
  authCapabilities: () =>
    request<{ phone_registration_enabled: boolean }>('/api/auth/capabilities'),
  sendRegisterCode: (method: 'email' | 'phone', value: string) =>
    request<{ success: boolean; message: string }>('/api/auth/send-code', {
      method: 'POST',
      body: JSON.stringify({
        method,
        email: method === 'email' ? value : '',
        phone: method === 'phone' ? value : '',
      }),
    }),
  register: (
    method: 'email' | 'phone',
    value: string,
    password: string,
    code: string,
  ) =>
    request<{ success: boolean; user: AuthUser }>('/api/auth/register', {
      method: 'POST',
      body: JSON.stringify({
        method,
        password,
        code,
        email: method === 'email' ? value : '',
        phone: method === 'phone' ? value : '',
      }),
    }),
  balance: () => request<BillingBalance & { success: boolean }>('/api/billing/balance'),
  billingUsage: () => request<BillingUsage & { success: boolean }>('/api/billing/usage'),
  billingBills: () => request<BillingBills & { success: boolean }>('/api/billing/bills'),
  projects: (includeArchived = false) =>
    request<Project[]>(`/projects?include_archived=${includeArchived}`),
  createProject: (payload: Partial<Project>) =>
    request<Project>('/projects', { method: 'POST', body: JSON.stringify(payload) }),
  updateProject: (projectId: string, payload: Partial<Project>) =>
    request<Project>(`/projects/${projectId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  manuscript: (projectId: string) =>
    request<ManuscriptOutline>(`/projects/${projectId}/manuscript`),
  createVolume: (
    projectId: string,
    payload: { title: string; description?: string },
  ) =>
    request<ManuscriptVolume>(`/projects/${projectId}/volumes`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  updateVolume: (volumeId: string, payload: Partial<ManuscriptVolume>) =>
    request<ManuscriptVolume>(`/volumes/${volumeId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  reorderVolumes: (projectId: string, orderedIds: string[]) =>
    request<ManuscriptVolume[]>(`/projects/${projectId}/volumes/reorder`, {
      method: 'POST',
      body: JSON.stringify({ ordered_ids: orderedIds }),
    }),
  createChapter: (
    projectId: string,
    payload: {
      volume_id: string
      title: string
      summary?: string
      draft_id?: string
    },
  ) =>
    request<ManuscriptChapter>(`/projects/${projectId}/chapters`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  updateChapter: (chapterId: string, payload: Partial<ManuscriptChapter>) =>
    request<ManuscriptChapter>(`/chapters/${chapterId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  reorderChapters: (
    projectId: string,
    volumeId: string,
    orderedIds: string[],
  ) =>
    request<ManuscriptChapter[]>(
      `/projects/${projectId}/volumes/${volumeId}/chapters/reorder`,
      {
        method: 'POST',
        body: JSON.stringify({ ordered_ids: orderedIds }),
      },
    ),
  bible: (projectId: string) => request<StoryBible>(`/projects/${projectId}/bible`),
  bibleVersions: (projectId: string) =>
    request<StoryBibleVersionSummary[]>(`/projects/${projectId}/bible/versions`),
  bibleVersion: (projectId: string, version: number) =>
    request<StoryBible>(`/projects/${projectId}/bible/versions/${version}`),
  bibleDiff: (projectId: string, fromVersion: number, toVersion: number) =>
    request<BibleDiff>(
      `/projects/${projectId}/bible/diff?from_version=${fromVersion}&to_version=${toVersion}`,
    ),
  addBibleEntry: (
    projectId: string,
    kind: 'rules' | 'factions' | 'locations',
    value: string | Record<string, unknown>,
    version: number,
  ) =>
    request<StoryBible>(`/projects/${projectId}/bible/${kind}`, {
      method: 'POST',
      body: JSON.stringify({ value, expected_version: version }),
    }),
  addForeshadowing: (projectId: string, description: string, version: number) =>
    request<StoryBible>(`/projects/${projectId}/bible/foreshadowing`, {
      method: 'POST',
      body: JSON.stringify({ description, expected_version: version }),
    }),
  addTimeline: (
    projectId: string,
    value: Record<string, unknown>,
    version: number,
  ) =>
    request<StoryBible>(`/projects/${projectId}/bible/timeline`, {
      method: 'POST',
      body: JSON.stringify({ ...value, expected_version: version }),
    }),
  resolveForeshadowing: (
    projectId: string,
    itemId: string,
    resolution: string,
    version: number,
  ) =>
    request<StoryBible>(
      `/projects/${projectId}/bible/foreshadowing/${itemId}/resolve`,
      {
        method: 'POST',
        body: JSON.stringify({ resolution, expected_version: version }),
      },
    ),
  proposeCharacter: (
    projectId: string,
    payload: { name: string; role: string; brief: string; apply: boolean },
  ) =>
    request<{ proposal: Record<string, unknown>; bible?: StoryBible }>(
      `/projects/${projectId}/agents/character`,
      { method: 'POST', body: JSON.stringify(payload) },
    ),
  proposeWorld: (projectId: string, goal: string, apply: boolean) =>
    request<{ proposal: Record<string, unknown>; bible?: StoryBible }>(
      `/projects/${projectId}/agents/worldbuilding`,
      { method: 'POST', body: JSON.stringify({ goal, apply }) },
    ),
  proposeForeshadowing: (projectId: string, sceneGoal: string, apply: boolean) =>
    request<{ proposal: Record<string, unknown>; bible?: StoryBible }>(
      `/projects/${projectId}/agents/foreshadowing`,
      {
        method: 'POST',
        body: JSON.stringify({ scene_goal: sceneGoal, max_actions: 3, apply }),
      },
    ),
  plan: (projectId: string, current: string, goal: string) =>
    request<PlotPlan>(`/projects/${projectId}/plot/plan`, {
      method: 'POST',
      body: JSON.stringify({ current, goal }),
    }),
  selectPlan: (projectId: string, planId: string, optionId: string) =>
    request<PlotPlan>(`/projects/${projectId}/plot/plans/${planId}/select`, {
      method: 'POST',
      body: JSON.stringify({ option_id: optionId }),
    }),
  write: (
    projectId: string,
    payload: {
      goal: string
      current: string
      plot_plan_id?: string
      selected_option_id?: string
      chapter_id?: string
    },
  ) =>
    request<{ draft: Draft }>(`/projects/${projectId}/write`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  drafts: (projectId: string) => request<Draft[]>(`/projects/${projectId}/drafts`),
  draft: (draftId: string) => request<Draft>(`/drafts/${draftId}`),
  acceptDraft: (draftId: string) =>
    request<StoryBible>(`/drafts/${draftId}/accept`, { method: 'POST' }),
  rejectDraft: (draftId: string, reason: string) =>
    request<Draft>(`/drafts/${draftId}/reject`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    }),
  reviseDraft: (draftId: string, instruction: string) =>
    request<{ draft: Draft }>(`/drafts/${draftId}/revise`, {
      method: 'POST',
      body: JSON.stringify({ instruction }),
    }),
  manuallyReviseDraft: (
    draftId: string,
    body: string,
    note: string,
    runChecks = false,
  ) =>
    request<{ draft: Draft }>(`/drafts/${draftId}/manual-revision`, {
      method: 'POST',
      body: JSON.stringify({ body, note, run_checks: runChecks }),
    }),
  diffDrafts: (fromId: string, toId: string) =>
    request<{ unified_diff: string }>(`/drafts/${fromId}/diff/${toId}`),
  qualityIssues: (
    projectId: string,
    filters: {
      issue_type?: 'continuity' | 'fact' | 'memory' | ''
      issue_status?: 'open' | 'resolved' | 'ignored' | ''
    } = {},
  ) => {
    const params = new URLSearchParams()
    if (filters.issue_type) params.set('issue_type', filters.issue_type)
    if (filters.issue_status) params.set('issue_status', filters.issue_status)
    const query = params.toString()
    return request<QualityIssueList>(
      `/projects/${projectId}/quality/issues${query ? `?${query}` : ''}`,
    )
  },
  updateQualityIssue: (
    issueId: string,
    payload: { status?: 'open' | 'resolved' | 'ignored'; resolution_note?: string },
  ) =>
    request<QualityIssue>(`/quality/issues/${issueId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  reviseFromQualityIssue: (issueId: string, instruction?: string) =>
    request<{ draft: Draft }>(`/quality/issues/${issueId}/revise`, {
      method: 'POST',
      body: JSON.stringify({ instruction: instruction || undefined }),
    }),
  workflows: (projectId: string) =>
    request<Workflow[]>(`/projects/${projectId}/workflows`),
  workflow: (runId: string) => request<WorkflowDetail>(`/workflows/${runId}`),
  startWorkflow: (
    projectId: string,
    goal: string,
    current: string,
    chapterId?: string,
    researchTopic?: string,
  ) =>
    request<WorkflowDetail>(`/projects/${projectId}/workflows`, {
      method: 'POST',
      body: JSON.stringify({
        goal,
        current,
        chapter_id: chapterId,
        research_topic: researchTopic || undefined,
      }),
    }),
  approveWorkflow: (runId: string, step: string, selectedOptionId?: string) =>
    request<WorkflowDetail>(`/workflows/${runId}/steps/${step}/approval`, {
      method: 'POST',
      body: JSON.stringify({
        decision: 'approve',
        actor: 'author',
        selected_option_id: selectedOptionId,
      }),
    }),
  rejectWorkflow: (runId: string, step: string, note: string) =>
    request<WorkflowDetail>(`/workflows/${runId}/steps/${step}/approval`, {
      method: 'POST',
      body: JSON.stringify({ decision: 'reject', actor: 'author', note }),
    }),
  retryWorkflow: (runId: string, fromStep?: string) =>
    request<WorkflowDetail>(`/workflows/${runId}/retry`, {
      method: 'POST',
      body: JSON.stringify({ from_step: fromStep }),
    }),
  cancelWorkflow: (runId: string) =>
    request<WorkflowDetail>(`/workflows/${runId}/cancel`, { method: 'POST' }),
  memory: (projectId: string, query: string) =>
    request<{ revision: number; hits: MemoryHit[]; conflicts: unknown[] }>(
      `/projects/${projectId}/memory/query`,
      { method: 'POST', body: JSON.stringify({ query, limit: 20 }) },
    ),
  agentRuns: (projectId: string) =>
    request<AgentRun[]>(`/projects/${projectId}/agent-runs?limit=50`),
  downloadDraft: async (draftId: string) => {
    const response = await fetch(`${API_URL}/drafts/${draftId}/download`, {
      headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
    })
    if (!response.ok) {
      if (response.status === 401) {
        authSession.clear()
        window.dispatchEvent(new Event('auth-expired'))
      }
      throw new ApiError(`下载失败（${response.status}）`, response.status)
    }
    return response.blob()
  },
  manuscriptPreview: (projectId: string) =>
    request<ManuscriptPreview>(`/projects/${projectId}/export/preview`),
  downloadManuscript: async (
    projectId: string,
    format: 'markdown' | 'docx' | 'zip',
  ) => {
    const response = await fetch(`${API_URL}/projects/${projectId}/export?format=${format}`, {
      headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
    })
    if (!response.ok) {
      const payload = await response.json().catch(() => null)
      if (response.status === 401) {
        authSession.clear()
        window.dispatchEvent(new Event('auth-expired'))
      }
      throw new ApiError(
        payload?.message || payload?.detail || `导出失败（${response.status}）`,
        response.status,
      )
    }
    return response.blob()
  },
}
