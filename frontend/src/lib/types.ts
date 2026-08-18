export type Role = 'super_admin' | 'client_admin' | 'manager' | 'employee'

// Display-only rename: the stored role value stays `client_admin` (renaming
// it would mean a migration touching every user row for no real benefit) —
// only what's shown in the UI changes, from "Client Admin" to "Admin".
export const ROLE_LABEL: Record<Role, string> = {
  super_admin: 'Super Admin',
  client_admin: 'Admin',
  manager: 'Manager',
  employee: 'Employee',
}

export interface Branding {
  accent_color: string
  logo_url: string | null
}

export interface Organization {
  id: string
  name: string
  slug: string
  status: string
  timezone: string
  branding?: Branding | null
}

export interface User {
  id: string
  email: string
  full_name: string
  job_title?: string | null
  department?: string | null
  phone?: string | null
  org_name?: string | null
  role: Role
  status: string
  must_change_password: boolean
  manager_ids?: string[]
  last_login_at?: string | null
  created_at?: string
  feedback_count?: number
}

export interface SessionResponse {
  access_token: string
  token_type: string
  expires_at: string
  csrf_token: string
  user: User | null
  organization: Organization | null
}

export interface ApiErrorBody {
  error: {
    code: string
    message: string
    details?: Record<string, string[]>
    request_id?: string
  }
}

export type DateRangePreset =
  | 'today'
  | 'yesterday'
  | 'last_7_days'
  | 'last_30_days'
  | 'last_90_days'
  | 'this_month'
  | 'last_month'
  | 'this_quarter'
  | 'this_year'
  | 'custom'

export interface FilterState {
  search?: string | null
  date_range: { preset: DateRangePreset; start?: string | null; end?: string | null }
  org_ids: string[]
  actor_ids: string[]
  actions: string[]
  severities: string[]
  sort?: string | null
  sort_dir: 'asc' | 'desc'
  page: number
  page_size: number
}

export const emptyFilters = (): FilterState => ({
  search: '',
  date_range: { preset: 'last_30_days' },
  org_ids: [],
  actor_ids: [],
  actions: [],
  severities: [],
  sort_dir: 'desc',
  page: 1,
  page_size: 25,
})

export interface ReportColumn {
  key: string
  label: string
  kind: 'text' | 'number' | 'datetime' | 'badge'
  align: string
  detail_only: boolean
}

export interface ReportMeta {
  key: string
  title: string
  description: string
  columns: ReportColumn[]
  filters_supported: string[]
  formats: string[]
}

export interface ReportResult {
  key: string
  title: string
  rows: Record<string, unknown>[]
  total: number
  page: number
  page_size: number
  window: { label: string; start_at: string; end_at: string }
  applied_filters: [string, string][]
}

export interface LookupItem {
  id: string
  label: string
  sublabel?: string | null
}

export interface CoverageSlice {
  target_type: string
  label: string
  count: number
  domain: 'internal' | 'external'
}

export interface DashboardData {
  scope: 'platform' | 'organization'
  organization: { id: string; name: string; timezone: string } | null
  metrics: {
    users_total: number
    users_active: number
    users_pending: number
    contacts: number
    templates: number
    my_pending_feedback: number
    my_results: number
  }
  coverage: CoverageSlice[]
  activity_14d: { date: string; count: number }[]
  attention?: {
    open_cycles?: number
    open_campaigns?: number
    closing_soon?: number
    proposals_awaiting_outcome?: number
  }
  recent_activity: {
    id: string
    action: string
    severity: string
    summary: string
    actor_name: string | null
    occurred_at: string
  }[]
  platform?: {
    orgs_total: number
    orgs_pending: number
    orgs_active: number
    orgs_suspended: number
    client_admins: number
  }
}

export interface OrgDetail {
  id: string
  name: string
  slug: string
  status: string
  registration_source: string
  contact_name: string
  contact_email: string
  contact_phone?: string | null
  country?: string | null
  timezone: string
  seat_limit?: number | null
  approved_at?: string | null
  rejection_reason?: string | null
  suspension_reason?: string | null
  created_at: string
  user_count: number
  branding?: { accent_color: string; logo_url: string | null } | null
  invite_url?: string | null
}

export interface Paged<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}