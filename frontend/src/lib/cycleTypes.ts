export type Relationship =
  | 'self'
  | 'manager'
  | 'upward'
  | 'peer'
  | 'skip_level'
  | 'external'

/** How each direction is described to the person being asked. */
export const RELATIONSHIP_LABEL: Record<Relationship, string> = {
  self: 'Self-assessment',
  manager: 'You manage them',
  upward: 'They manage you',
  peer: 'You work alongside them',
  skip_level: 'Skip level',
  external: 'External',
}

export const RELATIONSHIP_SHORT: Record<Relationship, string> = {
  self: 'Self',
  manager: 'Downward',
  upward: 'Upward',
  peer: 'Peer',
  skip_level: 'Skip level',
  external: 'External',
}

export interface CycleProgress {
  total: number
  submitted: number
  pending: number
  in_progress: number
  declined: number
  completion_pct: number
}

export interface Cycle {
  id: string
  name: string
  description: string | null
  status: 'draft' | 'open' | 'closed' | 'cancelled'
  is_anonymous: boolean
  min_responses_to_reveal: number
  template_version_id: string
  template_name: string | null
  template_version: number | null
  opens_at: string | null
  closes_at: string | null
  opened_at: string | null
  closed_at: string | null
  created_at: string
  progress: CycleProgress
}

export interface Assignment {
  id: string
  cycle_id: string
  cycle_name: string
  target_id: string
  target_label: string
  target_type: string
  relationship: Relationship
  status: 'pending' | 'in_progress' | 'submitted' | 'declined' | 'expired'
  is_anonymous: boolean
  due_at: string | null
  submitted_at: string | null
}

export interface FormQuestion {
  key: string
  text: string
  type: 'scale' | 'choice' | 'text' | 'boolean'
  required: boolean
  options: string[]
}

export interface FormSection {
  key: string
  title: string
  questions: FormQuestion[]
}

export interface FeedbackForm {
  intro: string
  scale: { min: number; max: number; labels: Record<string, string> }
  sections: FormSection[]
  closing: { comment_prompt: string; comment_required: boolean }
}

export interface AssignmentForm {
  assignment: Assignment
  form: FeedbackForm
}

export interface ResultRow {
  target_id: string
  target: string
  target_type: string | null
  responses: number
  revealed: boolean
  overall_average: number | null
  self_average: number | null
}

export interface QuestionResult {
  key: string
  text: string
  section: string
  count: number
  average: number | null
  distribution: Record<string, number>
}

export interface TargetResults {
  found: boolean
  target: { id: string; label: string; target_type: string }
  cycle: {
    id: string
    name: string
    status: string
    is_anonymous: boolean
    min_responses_to_reveal: number
  }
  response_count: number
  self_response_count: number
  revealed: boolean
  threshold: number
  suppressed_reason?: string
  overall_average?: number | null
  self_average?: number | null
  self_awareness_gap?: number | null
  scale?: { min: number; max: number }
  by_relationship?: {
    relationship: Relationship
    count: number
    revealed: boolean
    average: number | null
  }[]
  questions?: QuestionResult[]
  comments?: { comment: string; relationship: Relationship }[]
}

export interface TemplateVersionSummary {
  id: string
  version: number
  status: string
  published_at: string | null
}

export interface TemplateDetail {
  id: string
  name: string
  description: string | null
  scope: string
  target_type: string
  is_anonymous: boolean
  min_responses_to_reveal: number
  editable: boolean
  versions: TemplateVersionSummary[]
  latest: {
    id: string
    version: number
    status: string
    definition: Record<string, unknown>
    form: FeedbackForm
  } | null
}
