import clsx from 'clsx'
import { useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { IconSettings, IconShield, IconUpload } from '../components/icons'
import { Banner, Card, Field, Modal, Spinner } from '../components/ui'
import { PageHeader } from '../layout/AppShell'
import { ApiError, api, uploadFile } from '../lib/api'
import { useAuth } from '../store/auth'

interface BrandingDetail {
  accent_color: string
  email_footer_note: string | null
  logo_url: string | null
  logo_updated_at: string | null
}

interface ReminderSettings {
  enabled: boolean
  cooldown_days: number
  max_reminders: number
  quiet_period_hours: number
  escalate_to_owner: boolean
}
interface AnonymitySettings {
  default_min_responses_to_reveal: number
  upward_anonymous_by_default: boolean
}
interface AiSettings {
  enabled: boolean
  min_responses_for_summary: number
  monthly_token_budget: number
}
interface AuditSettings {
  retention_days: number
}
interface EmailSettings {
  invitation_subject: string | null
  feedback_request_subject: string | null
}
interface OrgSettings {
  reminders: ReminderSettings
  anonymity: AnonymitySettings
  ai: AiSettings
  audit: AuditSettings
  email: EmailSettings
}
interface SettingsResponse {
  settings: OrgSettings
  platform_floors: Record<string, number>
}

const HEX_RE = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/

function BrandingCard() {
  const { organization, updateOrganization } = useAuth()
  const [branding, setBranding] = useState<BrandingDetail | null>(
    organization?.branding
      ? {
          accent_color: organization.branding.accent_color,
          email_footer_note: null,
          logo_url: organization.branding.logo_url,
          logo_updated_at: null,
        }
      : null,
  )
  const [accent, setAccent] = useState(organization?.branding?.accent_color ?? '#B4633A')
  const [footerNote, setFooterNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const [pendingFile, setPendingFile] = useState<File | null>(null)
  const [pendingRemove, setPendingRemove] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!organization) return
    // The session's organization only carries accent_color and logo_url, so
    // the footer note (and a freshly authoritative accent) come from the full
    // org record.
    api
      .get<{ branding: BrandingDetail | null }>(`/orgs/${organization.id}`)
      .then((detail) => {
        if (detail.branding) {
          setBranding(detail.branding)
          setAccent(detail.branding.accent_color)
          setFooterNote(detail.branding.email_footer_note ?? '')
        }
      })
      .catch(() => {})
  }, [organization?.id])

  if (!organization) return null

  const effectiveLogoUrl = pendingFile ? preview : pendingRemove ? null : branding?.logo_url ?? null

  const applyLocally = (next: BrandingDetail) => {
    setBranding(next)
    updateOrganization({
      ...organization,
      branding: { accent_color: next.accent_color, logo_url: next.logo_url },
    })
  }

  const saveColour = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!HEX_RE.test(accent)) {
      setError('Enter a valid hex colour such as #B4633A.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      // The logo change commits first, in the same submit, so "Save
      // branding" is the single moment anything actually reaches the
      // server — not the moment a file was picked or Remove was clicked.
      if (pendingFile) {
        await uploadFile<BrandingDetail>(`/orgs/${organization.id}/logo`, pendingFile)
      } else if (pendingRemove) {
        await api.delete<BrandingDetail>(`/orgs/${organization.id}/logo`)
      }
      const result = await api.put<BrandingDetail>(`/orgs/${organization.id}/branding`, {
        accent_color: accent,
        email_footer_note: footerNote || null,
      })
      applyLocally(result)
      if (preview) URL.revokeObjectURL(preview)
      setPreview(null)
      setPendingFile(null)
      setPendingRemove(false)
      setNotice('Branding saved. Your dashboard, emails and feedback forms now reflect these changes.')
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Could not save branding.')
    } finally {
      setBusy(false)
    }
  }

  const uploadLogo = async (file: File) => {
    // Staged locally only. Nothing reaches the server until "Save branding"
    // is clicked — picking a file here must not be indistinguishable from
    // actually saving it.
    if (preview) URL.revokeObjectURL(preview)
    setPreview(URL.createObjectURL(file))
    setPendingFile(file)
    setPendingRemove(false)
  }

  const stageRemoveLogo = () => {
    if (pendingFile) {
      // Undo an as-yet-unsaved pick — nothing was ever sent to the server.
      if (preview) URL.revokeObjectURL(preview)
      setPreview(null)
      setPendingFile(null)
      return
    }
    setPendingRemove(true)
  }

  const undoRemoveLogo = () => setPendingRemove(false)

  return (
    <Card
      title="Branding"
      hint="Applied to your dashboard header, outgoing emails, and every feedback form your organization sends. Never shown to any other tenant."
    >
      {notice && (
        <Banner tone="success" className="mb-4" onDismiss={() => setNotice(null)}>
          {notice}
        </Banner>
      )}
      {error && (
        <Banner tone="error" className="mb-4">
          {error}
        </Banner>
      )}

      <div className="flex flex-wrap items-start gap-6">
        <div>
          <p className="mb-1.5 text-sm font-medium text-ink-700 dark:text-ink-200">Logo</p>
          <div className="flex h-20 w-40 items-center justify-center rounded-lg border border-dashed border-ink-300 bg-ink-50 dark:border-ink-700 dark:bg-ink-900">
            {effectiveLogoUrl ? (
              <img
                src={effectiveLogoUrl}
                alt={organization.name}
                className={clsx('max-h-16 max-w-[130px] object-contain', busy && 'opacity-60')}
              />
            ) : (
              <span className="text-2xs text-ink-400">No logo yet</span>
            )}
          </div>
          <input
            ref={fileInput}
            type="file"
            accept="image/png,image/jpeg,image/webp,image/svg+xml"
            className="hidden"
            onChange={(event) => {
              const file = event.target.files?.[0]
              if (file) void uploadLogo(file)
              event.target.value = ''
            }}
          />
          <button
            type="button"
            className="btn-secondary mt-2 flex items-center gap-1.5 px-3 py-1.5 text-sm"
            disabled={busy}
            onClick={() => fileInput.current?.click()}
          >
            <IconUpload width={14} height={14} />
            {effectiveLogoUrl ? 'Replace logo' : 'Upload logo'}
          </button>
          {effectiveLogoUrl && (
            <button
              type="button"
              className="btn-ghost mt-2 ml-2 px-3 py-1.5 text-sm text-critical"
              disabled={busy}
              onClick={stageRemoveLogo}
            >
              Remove logo
            </button>
          )}
          {pendingRemove && (
            <button
              type="button"
              className="btn-ghost mt-2 ml-2 px-3 py-1.5 text-sm"
              disabled={busy}
              onClick={undoRemoveLogo}
            >
              Undo remove
            </button>
          )}
          <p className="mt-1.5 max-w-[180px] text-2xs text-ink-400">
            PNG, JPEG, WebP or SVG, up to 2 MB. A wide transparent PNG works best.
          </p>
          {(pendingFile || pendingRemove) && (
            <p className="mt-1 max-w-[180px] text-2xs text-caution">
              Not saved yet — click &quot;Save branding&quot; below to apply.
            </p>
          )}
        </div>

        <form onSubmit={saveColour} className="min-w-[240px] flex-1">
          <div className="flex items-end gap-3">
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
                Accent colour
              </span>
              <div className="flex items-center gap-2">
                <input
                  type="color"
                  value={HEX_RE.test(accent) ? accent.slice(0, 7) : '#B4633A'}
                  onChange={(event) => setAccent(event.target.value)}
                  className="h-9 w-9 cursor-pointer rounded border border-ink-200 dark:border-ink-700"
                />
                <input
                  className="field w-32 font-mono"
                  value={accent}
                  onChange={(event) => setAccent(event.target.value)}
                  maxLength={7}
                />
              </div>
            </label>
          </div>

          <Field
            label="Email footer note (optional)"
            className="mt-3"
            value={footerNote}
            onChange={(event) => setFooterNote(event.target.value)}
            placeholder="e.g. a support contact or a compliance line"
            maxLength={500}
          />

          <button type="submit" className="btn-primary mt-3 px-3 py-1.5 text-sm" disabled={busy}>
            {busy && <Spinner />}
            Save branding
          </button>
        </form>
      </div>
    </Card>
  )
}

function NumberField({
  label,
  hint,
  value,
  min,
  max,
  onChange,
}: {
  label: string
  hint?: string
  value: number
  min: number
  max: number
  onChange: (value: number) => void
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-medium text-ink-700 dark:text-ink-200">
        {label}
      </span>
      <input
        type="number"
        className="field w-28"
        min={min}
        max={max}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      />
      {hint && <span className="mt-1 block text-2xs text-ink-400">{hint}</span>}
    </label>
  )
}

function Toggle({
  label,
  hint,
  checked,
  onChange,
}: {
  label: string
  hint?: string
  checked: boolean
  onChange: (value: boolean) => void
}) {
  return (
    <label className="flex cursor-pointer items-start gap-3">
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="mt-0.5 h-4 w-4 accent-[color:var(--accent)]"
      />
      <span>
        <span className="block text-sm font-medium text-ink-700 dark:text-ink-200">
          {label}
        </span>
        {hint && <span className="block text-2xs text-ink-400">{hint}</span>}
      </span>
    </label>
  )
}

function PolicyCard() {
  const [data, setData] = useState<SettingsResponse | null>(null)
  const [draft, setDraft] = useState<OrgSettings | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [preview, setPreview] = useState<{ subject: string; html: string } | null>(null)
  const [previewBusy, setPreviewBusy] = useState<'invitation' | 'feedback_request' | null>(null)

  const openPreview = async (kind: 'invitation' | 'feedback_request') => {
    setPreviewBusy(kind)
    setError(null)
    try {
      const rendered = await api.get<{ subject: string; html: string }>(
        `/settings/email-preview?kind=${kind}`,
      )
      setPreview(rendered)
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Could not render the preview.')
    } finally {
      setPreviewBusy(null)
    }
  }

  const load = () => {
    api
      .get<SettingsResponse>('/settings')
      .then((response) => {
        setData(response)
        setDraft(response.settings)
      })
      .catch((caught) =>
        setError(caught instanceof ApiError ? caught.message : 'Could not load settings.'),
      )
  }

  useEffect(load, [])

  if (!data || !draft) {
    return (
      <Card title="Policy" hint="Loading…">
        <div className="h-40" />
      </Card>
    )
  }

  const floor = data.platform_floors

  const save = async () => {
    setBusy(true)
    setError(null)
    try {
      const result = await api.put<SettingsResponse>('/settings', draft)
      setData(result)
      setDraft(result.settings)
      setNotice('Settings saved.')
    } catch (caught) {
      if (caught instanceof ApiError) {
        setError(caught.message)
      } else {
        setError('Could not save settings.')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <IconSettings width={16} height={16} className="accent-text" />
          Policy
        </span>
      }
      hint="Thresholds may be made stricter than the platform default, never looser — these are safety properties, not preferences."
    >
      {notice && (
        <Banner tone="success" className="mb-4" onDismiss={() => setNotice(null)}>
          {notice}
        </Banner>
      )}
      {error && (
        <Banner tone="error" className="mb-4">
          {error}
        </Banner>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <section>
          <h3 className="mb-3 text-sm font-semibold text-ink-900 dark:text-ink-50">
            Reminders
          </h3>
          <div className="space-y-3">
            <Toggle
              label="Send automatic reminders"
              hint="Chases non-responders on open rounds, subject to the limits below."
              checked={draft.reminders.enabled}
              onChange={(value) =>
                setDraft({ ...draft, reminders: { ...draft.reminders, enabled: value } })
              }
            />
            <div className="flex flex-wrap gap-4">
              <NumberField
                label="Cooldown (days)"
                hint="Minimum gap between reminders to the same person."
                min={1}
                max={30}
                value={draft.reminders.cooldown_days}
                onChange={(value) =>
                  setDraft({
                    ...draft,
                    reminders: { ...draft.reminders, cooldown_days: value },
                  })
                }
              />
              <NumberField
                label="Maximum reminders"
                hint="Past this, silence is treated as an answer."
                min={0}
                max={10}
                value={draft.reminders.max_reminders}
                onChange={(value) =>
                  setDraft({
                    ...draft,
                    reminders: { ...draft.reminders, max_reminders: value },
                  })
                }
              />
            </div>
            <Toggle
              label="Escalate to the round owner"
              hint="One digest naming who is still outstanding, sent once the cap is reached."
              checked={draft.reminders.escalate_to_owner}
              onChange={(value) =>
                setDraft({
                  ...draft,
                  reminders: { ...draft.reminders, escalate_to_owner: value },
                })
              }
            />
          </div>
        </section>

        <section>
          <h3 className="mb-3 text-sm font-semibold text-ink-900 dark:text-ink-50">
            Anonymity defaults
          </h3>
          <div className="space-y-3">
            <NumberField
              label="Minimum responses to reveal"
              hint="Applied to new templates. 0 shows results immediately, with no anonymity suppression."
              min={0}
              max={50}
              value={draft.anonymity.default_min_responses_to_reveal}
              onChange={(value) =>
                setDraft({
                  ...draft,
                  anonymity: { ...draft.anonymity, default_min_responses_to_reveal: value },
                })
              }
            />
            <Toggle
              label="Upward feedback anonymous by default"
              hint="New manager-effectiveness templates start anonymous."
              checked={draft.anonymity.upward_anonymous_by_default}
              onChange={(value) =>
                setDraft({
                  ...draft,
                  anonymity: { ...draft.anonymity, upward_anonymous_by_default: value },
                })
              }
            />
          </div>
        </section>

        <section>
          <h3 className="mb-3 flex items-center gap-1.5 text-sm font-semibold text-ink-900 dark:text-ink-50">
            <IconShield width={13} height={13} />
            AI
          </h3>
          <div className="space-y-3">
            <Toggle
              label="Enable AI analysis"
              hint="Sentiment and summaries. Turning this off here stops it for your organization only."
              checked={draft.ai.enabled}
              onChange={(value) =>
                setDraft({ ...draft, ai: { ...draft.ai, enabled: value } })
              }
            />
            <NumberField
              label="Minimum responses for a summary"
              hint={`Cannot go below the platform floor of ${floor.ai_min_responses_for_summary}. You may raise it.`}
              min={floor.ai_min_responses_for_summary}
              max={50}
              value={draft.ai.min_responses_for_summary}
              onChange={(value) =>
                setDraft({ ...draft, ai: { ...draft.ai, min_responses_for_summary: value } })
              }
            />
          </div>
        </section>

        <section>
          <h3 className="mb-3 text-sm font-semibold text-ink-900 dark:text-ink-50">
            Audit retention
          </h3>
          <NumberField
            label="Retain audit history for (days)"
            hint={`0 keeps everything. Cannot be set below ${floor.audit_retention_min_days} once enabled.`}
            min={0}
            max={3650}
            value={draft.audit.retention_days}
            onChange={(value) =>
              setDraft({ ...draft, audit: { ...draft.audit, retention_days: value } })
            }
          />
        </section>

        <section>
          <h3 className="mb-3 text-sm font-semibold text-ink-900 dark:text-ink-50">
            Email subjects
          </h3>
          <div className="space-y-3">
            <div className="flex items-end gap-2">
              <div className="flex-1">
                <Field
                  label="Invitation email subject (optional)"
                  hint="Use {org_name} for your organization's name. Left blank uses the default."
                  value={draft.email.invitation_subject ?? ''}
                  onChange={(event) =>
                    setDraft({
                      ...draft,
                      email: { ...draft.email, invitation_subject: event.target.value || null },
                    })
                  }
                  placeholder="You have been invited to {org_name}"
                  maxLength={200}
                />
              </div>
              <button
                type="button"
                className="btn-secondary mb-0.5 shrink-0 px-2.5 py-1.5 text-sm"
                disabled={previewBusy === 'invitation'}
                onClick={() => openPreview('invitation')}
              >
                {previewBusy === 'invitation' && <Spinner />}
                Preview
              </button>
            </div>
            <div className="flex items-end gap-2">
              <div className="flex-1">
                <Field
                  label="Feedback request email subject (optional)"
                  hint="Use {org_name} and {subject_label} (what the feedback is about)."
                  value={draft.email.feedback_request_subject ?? ''}
                  onChange={(event) =>
                    setDraft({
                      ...draft,
                      email: {
                        ...draft.email,
                        feedback_request_subject: event.target.value || null,
                      },
                    })
                  }
                  placeholder="Your feedback on {subject_label}"
                  maxLength={200}
                />
              </div>
              <button
                type="button"
                className="btn-secondary mb-0.5 shrink-0 px-2.5 py-1.5 text-sm"
                disabled={previewBusy === 'feedback_request'}
                onClick={() => openPreview('feedback_request')}
              >
                {previewBusy === 'feedback_request' && <Spinner />}
                Preview
              </button>
            </div>
          </div>
        </section>
      </div>

      {preview && (
        <Modal
          title="Email preview"
          hint={`Subject: ${preview.subject}`}
          onClose={() => setPreview(null)}
          className="max-w-xl"
        >
          <iframe
            title="Email preview"
            srcDoc={preview.html}
            className="h-[520px] w-full rounded-md border border-ink-200 bg-white dark:border-ink-700"
          />
        </Modal>
      )}

      <button
        type="button"
        className="btn-primary mt-6 px-3 py-1.5 text-sm"
        disabled={busy}
        onClick={save}
      >
        {busy && <Spinner />}
        Save settings
      </button>
    </Card>
  )
}

export function Settings() {
  const location = useLocation()
  const cameFromDashboard = (location.state as { from?: string } | null)?.from === 'dashboard'
  return (
    <>
      <PageHeader
        title="Settings"
        backTo={cameFromDashboard ? '/' : undefined}
        backLabel="Dashboard"
        description="Branding applied to everything your organization sends, and the policy thresholds that govern reminders, anonymity, AI and audit history."
      />
      <div className="space-y-5">
        <BrandingCard />
        <PolicyCard />
      </div>
    </>
  )
}