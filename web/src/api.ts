import type {
  AgentRun,
  Draft,
  MemoryHit,
  PlotPlan,
  Project,
  StoryBible,
  Workflow,
  WorkflowDetail,
} from './types'

const API_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ||
  'http://localhost:8000'

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
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    throw new ApiError(payload?.message || `请求失败（${response.status}）`, response.status)
  }
  return response.json() as Promise<T>
}

export const api = {
  projects: () => request<Project[]>('/projects'),
  createProject: (payload: Partial<Project>) =>
    request<Project>('/projects', { method: 'POST', body: JSON.stringify(payload) }),
  bible: (projectId: string) => request<StoryBible>(`/projects/${projectId}/bible`),
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
  diffDrafts: (fromId: string, toId: string) =>
    request<{ unified_diff: string }>(`/drafts/${fromId}/diff/${toId}`),
  workflows: (projectId: string) =>
    request<Workflow[]>(`/projects/${projectId}/workflows`),
  workflow: (runId: string) => request<WorkflowDetail>(`/workflows/${runId}`),
  startWorkflow: (projectId: string, goal: string, current: string) =>
    request<WorkflowDetail>(`/projects/${projectId}/workflows`, {
      method: 'POST',
      body: JSON.stringify({ goal, current }),
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
  memory: (projectId: string, query: string) =>
    request<{ revision: number; hits: MemoryHit[]; conflicts: unknown[] }>(
      `/projects/${projectId}/memory/query`,
      { method: 'POST', body: JSON.stringify({ query, limit: 20 }) },
    ),
  agentRuns: (projectId: string) =>
    request<AgentRun[]>(`/projects/${projectId}/agent-runs?limit=50`),
  downloadUrl: (draftId: string) => `${API_URL}/drafts/${draftId}/download`,
}
