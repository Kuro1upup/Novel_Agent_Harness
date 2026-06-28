export interface Project {
  id: string
  name: string
  genre: string
  sub_genre?: string
  premise: string
  target_audience: string
  tone: string
  created_at: string
}

export interface Character {
  id: string
  name: string
  role: string
  age?: number
  motivation?: string
  speech_style?: string
}

export interface Foreshadowing {
  id: string
  description: string
  expected_payoff?: string
  status: 'planned' | 'planted' | 'resolved' | 'abandoned'
}

export interface StoryBible {
  id: string
  project_id: string
  version: number
  world_summary: string
  rules: Array<Record<string, unknown> | string>
  factions: Array<Record<string, unknown>>
  characters: Character[]
  timeline: Array<Record<string, unknown>>
  locations: Array<Record<string, unknown>>
  unresolved_threads: Array<Record<string, unknown> | string>
  foreshadowing_items: Foreshadowing[]
  resolved_threads: Array<Record<string, unknown> | string>
  canon_events: Array<Record<string, unknown> | string>
}

export interface PlotOption {
  id: string
  title: string
  summary: string
  conflict: string
  payoff: string
  risks: string[]
  foreshadowing: string[]
  canon_risks: string[]
}

export interface PlotPlan {
  id: string
  current_arc: string
  arc_goal: string
  conflict: string
  stakes: string
  next_chapter_options: PlotOption[]
  selected_option_id?: string
}

export interface Draft {
  id: string
  project_id: string
  body: string
  creative_notes: string
  factual_basis_summary: string
  research_gaps: string[]
  status: 'draft' | 'accepted' | 'rejected' | 'superseded'
  object_key?: string
  bible_version: number
  plot_plan_id?: string
  selected_option_id?: string
  parent_draft_id?: string
  revision_number: number
  revision_instruction: string
  created_at: string
}

export interface WorkflowStep {
  id: string
  name: string
  status: string
  requires_approval: boolean
  result: Record<string, unknown>
}

export interface Workflow {
  id: string
  status: string
  current_step?: string
  parameters: Record<string, unknown>
  result: Record<string, unknown>
  created_at: string
}

export interface WorkflowDetail {
  run: Workflow
  steps: WorkflowStep[]
  events: Array<Record<string, unknown>>
}

export interface MemoryHit {
  memory: {
    id: string
    kind: string
    subject: string
    statement: string
    canon_version: number
  }
  score: number
}

export interface AgentRun {
  id: string
  agent_name: string
  provider: string
  model: string
  status: string
  duration_ms?: number
  prompt_tokens: number
  completion_tokens: number
  estimated_cost: number
  prompt_version: string
  created_at: string
}
