import { useEffect, useRef, useState } from 'react'
import { IconTrash } from '../components/icons'
import { Banner, Card, Chip, ConfirmDialog, Modal, Skeleton, Spinner, Switch } from '../components/ui'
import { useToast } from '../components/Toast'
import { PageHeader } from '../layout/AppShell'
import { ApiError, api } from '../lib/api'
import type { EmailTemplateKind, EmailTemplateLibrary, EmailTemplateOut } from '../lib/types'
import { useAuth } from '../store/auth'

// Kept in sync with AppShell.tsx's CREATE_FEEDBACK_TYPES by hand, same as
// that file's own note about feedback.py's kind list — this page only needs
// label/color, not the rest of that config.
const KIND_META: Record<EmailTemplateKind, { label: string; color: string }> = {
  client: { label: 'Client Review', color: '#B4633A' },
  employee: { label: 'Employees Review', color: '#3B82F6' },
  management: { label: 'Management Review', color: '#8B5CF6' },
  product: { label: 'Product Review', color: '#10B981' },
  service: { label: 'Service Review', color: '#F59E0B' },
  proposal: { label: 'Proposal Review', color: '#EC4899' },
}
const KIND_ORDER: EmailTemplateKind[] = [
  'client',
  'employee',
  'management',
  'product',
  'service',
  'proposal',
]

interface Draft {
  name: string
  subject_template: string
  heading: string
  body_text: string
  body_format: 'text' | 'html'
  signature: string
  signature_format: 'text' | 'html'
}

function toDraft(source: EmailTemplateOut): Draft {
  return {
    name: source.name,
    subject_template: source.subject_template,
    heading: source.heading,
    body_text: source.body_text,
    body_format: source.body_format,
    signature: source.signature,
    signature_format: source.signature_format,
  }
}

const EMPTY_DRAFT: Draft = { name: '', subject_template: '', heading: '', body_text: '', body_format: 'text', signature: '', signature_format: 'text' }


// ---------------------------------------------------------------------------
// Placeholder insert chips — friendly label in, correct {token} out.
//
// The admin never types a raw token (and so can't misspell one into a silent
// send-time failure); they click a labelled chip and the exact token lands at
// the cursor. Which chips appear depends on the review kind, because the two
// send paths fill different context (verified against services/email.py):
//   internal (employee, management):      first_name, org_name, subject_label, cycle_name
//   external (client/product/service/proposal): first_name, org_name, subject_label, deadline
//
// TEMPORARY SOURCE. This is a second copy of a list the backend already holds
// inline (in those two send dicts). It stays here only until the backend
// exposes it as one source of truth (planned GET
// /email-templates/{kind}/placeholders). When that lands, replace chipsForKind
// with a fetch — nothing else here changes, since the UI below only ever
// consumes {token,label} pairs.
// ---------------------------------------------------------------------------
interface PlaceholderChip {
  token: string
  label: string
}

// AFTER
// The one place a placeholder token maps to its friendly label. Both the
// insert chips and the read-only humanizer below read from this, so a label
// is defined once and can't drift between the editor and the list views.
const TOKEN_LABELS: Record<string, string> = {
  '{first_name}': "Recipient's first name",
  '{org_name}': 'Organization name',
  '{subject_label}': 'Feedback topic',
  '{cycle_name}': 'Name of this review round',
  '{deadline}': 'Feedback deadline',
}

const chip = (token: string): PlaceholderChip => ({ token, label: TOKEN_LABELS[token] ?? token })

// Replace every known {token} in read-only text with its friendly label, so
// list/summary views never show raw {cycle_name} syntax to an admin. The
// stored value is never changed — this is display-only.
function humanizeTokens(text: string): string {
  return text.replace(/\{[a-zA-Z_]+\}/g, (match) => {
    const label = TOKEN_LABELS[match]
    return label ? `[${label}]` : match
  })
}

const SHARED_CHIPS: PlaceholderChip[] = [chip('{first_name}'), chip('{org_name}'), chip('{subject_label}')]
const INTERNAL_KINDS: EmailTemplateKind[] = ['employee', 'management']

function chipsForKind(kind: EmailTemplateKind): PlaceholderChip[] {
  // {deadline} is intentionally not offered as a chip — the expiry date is
  // always appended automatically below the message, so letting an admin
  // insert it into the body would be redundant and contradictory.
  return INTERNAL_KINDS.includes(kind)
    ? [...SHARED_CHIPS, chip('{cycle_name}')]
    : [...SHARED_CHIPS]
}

// Insert `token` at the field's caret (not the end), then restore focus with
// the caret just past what was inserted. requestAnimationFrame is required:
// the value change is a React state update, so at onClick time the DOM node
// still holds the old text and selection — we reposition on the next frame,
// after React has committed the new value.
function insertToken(
  el: HTMLInputElement | HTMLTextAreaElement | null,
  value: string,
  onChange: (next: string) => void,
  token: string,
) {
  if (!el) {
    onChange(value + token)
    return
  }
  const start = el.selectionStart ?? value.length
  const end = el.selectionEnd ?? value.length
  onChange(value.slice(0, start) + token + value.slice(end))
  const caret = start + token.length
  requestAnimationFrame(() => {
    el.focus()
    el.setSelectionRange(caret, caret)
  })
}

function PlaceholderChips({
  kind,
  getEl,
  value,
  onChange,
}: {
  kind: EmailTemplateKind
  getEl: () => HTMLInputElement | HTMLTextAreaElement | null
  value: string
  onChange: (next: string) => void
}) {
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
      <span className="text-xs text-ink-400">Insert:</span>
      {chipsForKind(kind).map((chip) => (
        <button
          key={chip.token}
          type="button"
          title={`Inserts ${chip.token}`}
          onClick={() => insertToken(getEl(), value, onChange, chip.token)}
          className="rounded-full border border-ink-200 px-2 py-0.5 text-xs text-ink-600 transition hover:border-ink-300 hover:bg-ink-50 dark:border-ink-700 dark:text-ink-300 dark:hover:bg-ink-800"
        >
          + {chip.label}
        </button>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Rich text field — a Plain text / HTML toggle over one field, with a small
// formatting toolbar in HTML mode. Used for Message and Signature.
//
// The contentEditable is intentionally *uncontrolled*: innerHTML is written
// only when the incoming `value` diverges from what's already in the DOM
// (external changes — a chip insert, switching templates, a mode switch),
// never on each keystroke. Re-writing innerHTML every keystroke is exactly
// what makes a React contentEditable jump the caret to the start; the
// `innerHTML !== value` guard below is what prevents that.
//
// Whatever is typed here is sanitized AGAIN on the backend by nh3 before it
// reaches any inbox (services/email.py::_render_rich). This toolbar only
// decides what an admin *can* enter, never what is trusted.
// ---------------------------------------------------------------------------
const RICH_MARKS: { cmd: string; label: string; content: string }[] = [
  { cmd: 'bold', label: 'Bold', content: 'B' },
  { cmd: 'italic', label: 'Italic', content: 'I' },
  { cmd: 'underline', label: 'Underline', content: 'U' },
  { cmd: 'strikeThrough', label: 'Strikethrough', content: 'S' },
]

const BLOCK_FORMATS: { value: string; label: string }[] = [
  { value: 'p', label: 'Normal' },
  { value: 'h1', label: 'Heading 1' },
  { value: 'h2', label: 'Heading 2' },
  { value: 'h3', label: 'Heading 3' },
]


function escapeHtml(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}
// Plain -> HTML on mode switch: escape entities first, then keep line breaks
// as <br> so nothing the admin already typed silently collapses.
function textToHtml(text: string): string {
  return escapeHtml(text).replace(/\n/g, '<br>')
}
// HTML -> plain on mode switch: <br>/</p> become newlines, everything else
// is dropped to its text. Downgrading loses formatting, which is expected.
function htmlToText(html: string): string {
  const tmp = html.replace(/<br\s*\/?>/gi, '\n').replace(/<\/p>/gi, '\n')
  const el = document.createElement('div')
  el.innerHTML = tmp
  return (el.textContent ?? '').replace(/\n{3,}/g, '\n\n').trim()
}
function isHtmlEmpty(html: string): boolean {
  return html.replace(/<br\s*\/?>/gi, '').replace(/&nbsp;/gi, '').trim() === ''
}

// Clean pasted HTML: keep the visible formatting (colour, bold/italic/
// underline, links, line structure) and drop everything else — the Tailwind
// `--tw-*` vars and layout styles that otherwise bloat a paste to tens of KB.
function sanitizePastedHtml(html: string): string {
  const ALLOWED = new Set([
    'B', 'STRONG', 'I', 'EM', 'U', 'S', 'A', 'BR', 'P', 'DIV', 'SPAN',
    'UL', 'OL', 'LI', 'H1', 'H2', 'H3',
  ])
  const KEEP_STYLE = ['color', 'font-weight', 'font-style', 'text-decoration']
  const doc = new DOMParser().parseFromString(html, 'text/html')

  const walk = (node: Node) => {
    for (const child of Array.from(node.childNodes)) {
      if (child.nodeType !== Node.ELEMENT_NODE) continue
      const el = child as HTMLElement
      walk(el)
      if (!ALLOWED.has(el.tagName)) {
        el.replaceWith(...Array.from(el.childNodes)) // unwrap unknown tags, keep text
        continue
      }
      const href = el.tagName === 'A' ? el.getAttribute('href') : null
      const kept = KEEP_STYLE
        .map((p) => [p, el.style.getPropertyValue(p)] as const)
        .filter(([, v]) => v)
      for (const attr of Array.from(el.attributes)) el.removeAttribute(attr.name)
      if (kept.length) el.setAttribute('style', kept.map(([p, v]) => `${p}: ${v}`).join('; '))
      if (href) el.setAttribute('href', href)
    }
  }
  walk(doc.body)
  return doc.body.innerHTML
}

function RichTextField({
  label,
  required,
  hint,
  error,
  readOnly,
  kind,
  value,
  format,
  placeholder,
  rows,
  maxLength,
  onChange,
  onModeChange,
  onBlur,
}: {
  label: string
  required?: boolean
  hint?: string
  error?: string
  readOnly: boolean
  kind: EmailTemplateKind
  value: string
  format: 'text' | 'html'
  placeholder?: string
  rows: number
  maxLength: number
  onChange: (value: string) => void
  onModeChange: (format: 'text' | 'html', value: string) => void
  onBlur?: () => void
}) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const editorRef = useRef<HTMLDivElement | null>(null)
  const savedRange = useRef<Range | null>(null)

  // The ONLY thing that writes into the editor: seed it when the node first
  // appears (or reappears after a Plain->HTML switch) and its content doesn't
  // already match. During normal typing/re-renders innerHTML === value, so
  // this does nothing — which is why your text is never redrawn away. There is
  // deliberately no sync effect; that effect was what wiped edits on blur.
  const attachEditor = (node: HTMLDivElement | null) => {
    editorRef.current = node
    if (node && node.innerHTML !== value) node.innerHTML = value
  }

  const commit = () => {
    const el = editorRef.current
    if (el) onChange(el.innerHTML)
  }

  // Remember the caret while it's still inside the editor, so the Style
  // dropdown and colour picker (which steal focus) can put it back.
  const saveSelection = () => {
    const sel = window.getSelection()
    if (sel && sel.rangeCount > 0 && editorRef.current?.contains(sel.anchorNode)) {
      savedRange.current = sel.getRangeAt(0).cloneRange()
    }
  }
  const restoreSelection = () => {
    const el = editorRef.current
    if (!el) return
    el.focus()
    const sel = window.getSelection()
    if (savedRange.current && sel) {
      sel.removeAllRanges()
      sel.addRange(savedRange.current)
    }
  }

  const run = (cmd: string, arg?: string) => {
    restoreSelection()
    document.execCommand(cmd, false, arg)
    commit()
    saveSelection()
  }

  const applyColor = (color: string) => {
    restoreSelection()
    document.execCommand('styleWithCSS', false, 'true')
    document.execCommand('foreColor', false, color)
    document.execCommand('styleWithCSS', false, 'false')
    commit()
    saveSelection()
  }

  const setBlock = (tag: string) => run('formatBlock', `<${tag}>`)

  const addLink = () => {
    const url = window.prompt('Link address', 'https://')
    if (url) run('createLink', url)
  }
  const addImage = () => {
    const url = window.prompt('Image URL (must be a hosted https link)', 'https://')
    if (url) run('insertImage', url)
  }
  const clearFormatting = () => {
    restoreSelection()
    document.execCommand('removeFormat')
    document.execCommand('formatBlock', false, '<p>')
    commit()
    saveSelection()
  }

  const insertChip = (token: string) => {
    if (format === 'html') {
      restoreSelection()
      document.execCommand('insertText', false, token)
      commit()
      saveSelection()
    } else {
      insertToken(textareaRef.current, value, onChange, token)
    }
  }

  const btn =
    'flex h-7 min-w-[1.75rem] items-center justify-center rounded px-1.5 text-sm text-ink-700 hover:bg-ink-100 dark:text-ink-200 dark:hover:bg-ink-800'
  const Sep = () => <span className="mx-0.5 h-5 w-px bg-ink-200 dark:bg-ink-700" />

  return (
    <div className="block">
      <span className="mb-1.5 flex items-center justify-between gap-2">
        <span className="text-xs font-semibold uppercase tracking-wide text-ink-500 dark:text-ink-400">
          {label} {required && <span className="text-red-500">*</span>}
        </span>
        {!readOnly && (
          <span className="inline-flex overflow-hidden rounded-md border border-ink-200 dark:border-ink-700">
            {(['text', 'html'] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() =>
                  onModeChange(m, m === 'html' ? textToHtml(value) : htmlToText(value))
                }
                className={`px-2 py-0.5 text-xs transition ${
                  format === m
                    ? 'bg-ink-800 text-white dark:bg-ink-200 dark:text-ink-900'
                    : 'bg-transparent text-ink-500 hover:bg-ink-50 dark:hover:bg-ink-800'
                }`}
              >
                {m === 'text' ? 'Plain Text' : 'HTML Editor'}
              </button>
            ))}
          </span>
        )}
      </span>

      {format === 'html' ? (
        <div
          className={`rounded-md border ${error ? 'border-red-400' : 'border-ink-200 dark:border-ink-700'}`}
        >
          {!readOnly && (
            <div className="flex flex-wrap items-center gap-0.5 border-b border-ink-200 p-1.5 dark:border-ink-700">
              {RICH_MARKS.map((m) => (
                <button
                  key={m.cmd}
                  type="button"
                  title={m.label}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => run(m.cmd)}
                  className={btn}
                  style={{
                    fontWeight: m.cmd === 'bold' ? 700 : undefined,
                    fontStyle: m.cmd === 'italic' ? 'italic' : undefined,
                    textDecoration:
                      m.cmd === 'underline'
                        ? 'underline'
                        : m.cmd === 'strikeThrough'
                          ? 'line-through'
                          : undefined,
                  }}
                >
                  {m.content}
                </button>
              ))}
              <Sep />
              <button type="button" title="Bullet list" onMouseDown={(e) => e.preventDefault()} onClick={() => run('insertUnorderedList')} className={btn}>•</button>
              <button type="button" title="Numbered list" onMouseDown={(e) => e.preventDefault()} onClick={() => run('insertOrderedList')} className={btn}>1.</button>
              <button type="button" title="Decrease indent" onMouseDown={(e) => e.preventDefault()} onClick={() => run('outdent')} className={btn}>⇤</button>
              <button type="button" title="Increase indent" onMouseDown={(e) => e.preventDefault()} onClick={() => run('indent')} className={btn}>⇥</button>
              <Sep />
              <select
                title="Text style"
                onMouseDown={saveSelection}
                onChange={(e) => {
                  setBlock(e.target.value)
                  e.target.selectedIndex = 0
                }}
                className="h-7 rounded border border-ink-200 bg-transparent px-1 text-xs text-ink-700 dark:border-ink-700 dark:text-ink-200"
                defaultValue="p"
              >
                {BLOCK_FORMATS.map((b) => (
                  <option key={b.value} value={b.value}>
                    {b.label}
                  </option>
                ))}
              </select>
              <Sep />
              {/* Full native colour picker — whole spectrum + eyedropper. */}
              <label title="Text colour" className="flex h-7 items-center gap-1 rounded px-1 text-sm text-ink-700 hover:bg-ink-100 dark:text-ink-200 dark:hover:bg-ink-800">
                <span className="font-semibold">A</span>
                <input
                  type="color"
                  defaultValue="#111827"
                  onMouseDown={saveSelection}
                  onChange={(e) => applyColor(e.target.value)}
                  className="h-5 w-5 cursor-pointer rounded border border-ink-200 bg-transparent p-0 dark:border-ink-700"
                />
              </label>
              <Sep />
              <button type="button" title="Insert image by URL" onMouseDown={(e) => e.preventDefault()} onClick={addImage} className={btn}>Image</button>
              <button type="button" title="Insert link" onMouseDown={(e) => e.preventDefault()} onClick={addLink} className={btn}>Link</button>
              <button type="button" title="Horizontal line" onMouseDown={(e) => e.preventDefault()} onClick={() => run('insertHorizontalRule')} className={btn}>—</button>
              <Sep />
              <button type="button" title="Clear formatting" onMouseDown={(e) => e.preventDefault()} onClick={clearFormatting} className={`${btn} text-red-600`}>Clear</button>
            </div>
          )}
          <div className="relative">
            {!readOnly && isHtmlEmpty(value) && (
              <span className="pointer-events-none absolute left-3 top-2 text-sm text-ink-400">
                {placeholder}
              </span>
            )}
            <div
              ref={attachEditor}
              contentEditable={!readOnly}
              suppressContentEditableWarning
              onInput={commit}
              onPaste={(e) => {
                // Keep colour/bold/links from the paste, but strip the junk
                // (Tailwind vars, layout styles) via sanitizePastedHtml.
                e.preventDefault()
                const html = e.clipboardData.getData('text/html')
                const text = e.clipboardData.getData('text/plain')
                if (html) {
                  document.execCommand('insertHTML', false, sanitizePastedHtml(html))
                } else {
                  document.execCommand('insertText', false, text)
                }
                commit()
              }}
              onKeyUp={saveSelection}
              onMouseUp={saveSelection}
              onBlur={() => {
                commit()
                onBlur?.()
              }}
              role="textbox"
              aria-multiline="true"
              className="w-full overflow-auto px-3 py-2 text-sm text-ink-900 outline-none dark:text-ink-50 [&_a]:text-blue-600 [&_a]:underline [&_h1]:text-xl [&_h1]:font-bold [&_h2]:text-lg [&_h2]:font-bold [&_h3]:text-base [&_h3]:font-semibold [&_ul]:list-disc [&_ul]:pl-6 [&_ol]:list-decimal [&_ol]:pl-6 [&_blockquote]:border-l-2 [&_blockquote]:border-ink-300 [&_blockquote]:pl-3 [&_hr]:my-2"
              style={{ minHeight: `${rows * 1.8}rem` }}
            />
          </div>
        </div>
      ) : (
        <textarea
          className={`field resize-y${error ? ' border-red-400' : ''}`}
          rows={rows}
          maxLength={maxLength}
          ref={textareaRef}
          placeholder={placeholder}
          value={value}
          disabled={readOnly}
          onChange={(e) => onChange(e.target.value)}
          onBlur={onBlur}
          aria-invalid={error ? true : undefined}
        />
      )}

      {error && <span className="mt-1 block text-xs text-red-500">{error}</span>}
      {hint && <span className="mt-1 block text-xs text-ink-400">{hint}</span>}

      {!readOnly && (
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
          <span className="text-xs text-ink-400">Insert:</span>
          {chipsForKind(kind).map((c) => (
            <button
              key={c.token}
              type="button"
              title={`Inserts ${c.token}`}
              onClick={() => insertChip(c.token)}
              className="rounded-full border border-ink-200 px-2 py-0.5 text-xs text-ink-600 transition hover:border-ink-300 hover:bg-ink-50 dark:border-ink-700 dark:text-ink-300 dark:hover:bg-ink-800"
            >
              + {c.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}


function TemplateForm({
  meta,
  draft,
  setDraft,
  readOnly,
  kind,
}: {
  meta: { label: string; color: string }
  draft: Draft
  setDraft: (draft: Draft) => void
  readOnly: boolean
  kind: EmailTemplateKind
}) {
  const toast = useToast()
  const [previewing, setPreviewing] = useState(false)
  const [preview, setPreview] = useState<{ subject: string; html: string } | null>(null)
  const subjectRef = useRef<HTMLInputElement>(null)
  const headingRef = useRef<HTMLInputElement>(null)
  const [touched, setTouched] = useState<{ name: boolean; subject: boolean; body: boolean }>({
    name: false,
    subject: false,
    body: false,
  })
  const markTouched = (field: 'name' | 'subject' | 'body') =>
    setTouched((prev) => ({ ...prev, [field]: true }))
  const errors = {
    name: touched.name && !draft.name.trim() ? 'Template name is required' : '',
    subject: touched.subject && !draft.subject_template.trim() ? 'Subject is required' : '',
    body:
      touched.body &&
      (draft.body_format === 'html' ? isHtmlEmpty(draft.body_text) : !draft.body_text.trim())
        ? 'Message is required'
        : '',
  }

  const runPreview = async () => {
    setPreviewing(true)
    try {
      const rendered = await api.post<{ subject: string; html: string }>(
        `/email-templates/${kind}/preview`,
        {
          subject_template: draft.subject_template,
          heading: draft.heading,
          body_text: draft.body_text,
          body_format: draft.body_format,
          signature: draft.signature,
          signature_format: draft.signature_format,
        },
      )
      setPreview(rendered)
    } catch (caught) {
      toast.show(
        'critical',
        'Could not render the preview',
        caught instanceof ApiError ? caught.message : undefined,
      )
    } finally {
      setPreviewing(false)
    }
  }

  return (
    <>
      <div className="mb-4 flex items-center gap-2 text-sm text-ink-500 dark:text-ink-400">
        <span
          className="h-2 w-2 shrink-0 rounded-full"
          style={{ background: meta.color }}
          aria-hidden="true"
        />
        {meta.label}
      </div>

      <div className="space-y-5">
        {!readOnly && (
          <label className="block">
            <span className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-ink-500 dark:text-ink-400">
              Template name <span className="text-red-500">*</span>
            </span>
            <input
              className={`field${errors.name ? ' border-red-400' : ''}`}
              maxLength={150}
              value={draft.name}
              onChange={(event) => setDraft({ ...draft, name: event.target.value })}
              onBlur={() => markTouched('name')}
              aria-invalid={errors.name ? true : undefined}
              placeholder="e.g. Formal pitch"
            />
            {errors.name && (
              <span className="mt-1 block text-xs text-red-500">{errors.name}</span>
            )}
          </label>
        )}

        <label className="block">
          <span className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-ink-500 dark:text-ink-400">
            Subject <span className="text-red-500">*</span>
          </span>
          <input
            className={`field${errors.subject ? ' border-red-400' : ''}`}
            maxLength={200}
            ref={subjectRef}
            placeholder="e.g. Please share your feedback"
            value={draft.subject_template}
            disabled={readOnly}
            onChange={(event) => setDraft({ ...draft, subject_template: event.target.value })}
            onBlur={() => markTouched('subject')}
            aria-invalid={errors.subject ? true : undefined}
          />
          {errors.subject && (
            <span className="mt-1 block text-xs text-red-500">{errors.subject}</span>
          )}
          {!readOnly && (
            <PlaceholderChips
              kind={kind}
              getEl={() => subjectRef.current}
              value={draft.subject_template}
              onChange={(next) => setDraft({ ...draft, subject_template: next })}
            />
          )}
        </label>

        <label className="block">
          <span className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-ink-500 dark:text-ink-400">
            Heading (optional)
          </span>
          <input
            className="field"
            maxLength={200}
            ref={headingRef}
            placeholder="e.g. Share your feedback"
            value={draft.heading}
            disabled={readOnly}
            onChange={(event) => setDraft({ ...draft, heading: event.target.value })}
          />
          {!readOnly && (
            <PlaceholderChips
              kind={kind}
              getEl={() => headingRef.current}
              value={draft.heading}
              onChange={(next) => setDraft({ ...draft, heading: next })}
            />
          )}
        </label>

        <RichTextField
          label="Message"
          required
          readOnly={readOnly}
          kind={kind}
          value={draft.body_text}
          format={draft.body_format}
          placeholder="Type the email message here…"
          rows={6}
          maxLength={20000}
          error={errors.body}
          hint="The link, expiry date, and footer are always added automatically below this."
          onChange={(v) => setDraft({ ...draft, body_text: v })}
          onModeChange={(f, v) => setDraft({ ...draft, body_text: v, body_format: f })}
          onBlur={() => markTouched('body')}
        />

        <RichTextField
          label="Signature"
          readOnly={readOnly}
          kind={kind}
          value={draft.signature}
          format={draft.signature_format}
          placeholder="e.g. Regards, the {org_name} team"
          rows={3}
          maxLength={40000}
          onChange={(v) => setDraft({ ...draft, signature: v })}
          onModeChange={(f, v) => setDraft({ ...draft, signature: v, signature_format: f })}
        />
      </div>

      <div className="mt-4">
        <button
          type="button"
          className="btn-secondary px-3 py-1.5 text-sm"
          disabled={previewing}
          onClick={runPreview}
        >
          {previewing && <Spinner />}
          Preview
        </button>
      </div>

      {preview && (
        <Modal
          title="Email preview"
          hint={`Subject: ${preview.subject}`}
          onClose={() => setPreview(null)}
          className="max-w-2xl"
        >
          <iframe
            title="Email preview"
            srcDoc={preview.html}
            className="h-[520px] w-full rounded-md border border-ink-200 bg-white dark:border-ink-700"
          />
        </Modal>
      )}
    </>
  )
}

function GlobalEditModal({
  kind,
  initial,
  onClose,
  onSaved,
}: {
  kind: EmailTemplateKind
  initial: EmailTemplateOut
  onClose: () => void
  onSaved: () => void
}) {
  const toast = useToast()
  const [draft, setDraft] = useState<Draft>(toDraft(initial))
  const [saving, setSaving] = useState(false)
  const meta = KIND_META[kind]

  const save = async () => {
    setSaving(true)
    try {
      await api.put(`/email-templates/${kind}`, draft)
      toast.show('success', 'Platform default saved')
      onSaved()
      onClose()
    } catch (caught) {
      toast.show(
        'critical',
        'Could not save the template',
        caught instanceof ApiError ? caught.message : undefined,
      )
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal title="Edit platform default" onClose={onClose} className="max-w-3xl">
      <TemplateForm meta={meta} draft={draft} setDraft={setDraft} readOnly={false} kind={kind} />
      <div className="mt-5 flex items-center justify-end gap-2">
        <button type="button" className="btn-ghost px-3 py-1.5 text-sm" onClick={onClose}>
          Cancel
        </button>
        <button
          type="button"
          className="btn-primary px-3 py-1.5 text-sm"
          disabled={
            saving ||
            !draft.subject_template.trim() ||
            (draft.body_format === 'html' ? isHtmlEmpty(draft.body_text) : !draft.body_text.trim())
          }
          onClick={save}
        >
          {saving && <Spinner />}
          Save
        </button>
      </div>
    </Modal>
  )
}

function OrgTemplateModal({
  kind,
  mode,
  initial,
  onClose,
  onSaved,
}: {
  kind: EmailTemplateKind
  mode: 'create' | 'edit' | 'view'
  initial: EmailTemplateOut | null
  onClose: () => void
  onSaved: () => void
}) {
  const toast = useToast()
  const [draft, setDraft] = useState<Draft>(initial ? toDraft(initial) : EMPTY_DRAFT)
  const [saving, setSaving] = useState(false)
  const meta = KIND_META[kind]
  const readOnly = mode === 'view'

  const save = async () => {
    setSaving(true)
    try {
      if (mode === 'create') {
        await api.post('/email-templates', { kind, ...draft })
        toast.show('success', 'Template added')
      } else if (mode === 'edit' && initial) {
        await api.put(`/email-templates/item/${initial.id}`, draft)
        toast.show('success', 'Template saved')
      }
      onSaved()
      onClose()
    } catch (caught) {
      toast.show(
        'critical',
        'Could not save the template',
        caught instanceof ApiError ? caught.message : undefined,
      )
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title={mode === 'create' ? 'Add email template' : (initial?.name ?? 'Template')}
      onClose={onClose}
      className="max-w-3xl"
    >
      <TemplateForm meta={meta} draft={draft} setDraft={setDraft} readOnly={readOnly} kind={kind} />
      <div className="mt-5 flex items-center justify-end gap-2">
        <button type="button" className="btn-ghost px-3 py-1.5 text-sm" onClick={onClose}>
          {readOnly ? 'Close' : 'Cancel'}
        </button>
        {!readOnly && (
          <button
            type="button"
            className="btn-primary px-3 py-1.5 text-sm"
            disabled={
              saving ||
              !draft.name.trim() ||
              !draft.subject_template.trim() ||
              (draft.body_format === 'html' ? isHtmlEmpty(draft.body_text) : !draft.body_text.trim())
            }
            onClick={save}
          >
            {saving && <Spinner />}
            Save
          </button>
        )}
      </div>
    </Modal>
  )
}

function SuperAdminView() {
  const [items, setItems] = useState<EmailTemplateOut[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<EmailTemplateKind | null>(null)

  const load = () => {
    setError(null)
    api
      .get<EmailTemplateOut[]>('/email-templates')
      .then(setItems)
      .catch((caught) => setError(caught instanceof ApiError ? caught.message : 'Failed to load'))
  }

  useEffect(load, [])

  const byKind = new Map((items ?? []).map((item) => [item.kind, item]))

  return (
    <>
      {error && (
        <Banner tone="error" className="mb-4">
          {error}
        </Banner>
      )}
      <Card padded={false}>
        {items === null ? (
          <div className="space-y-3 p-5">
            {KIND_ORDER.map((kind) => (
              <Skeleton key={kind} className="h-12 w-full" />
            ))}
          </div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Review kind</th>
                <th>Subject</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {KIND_ORDER.map((kind) => {
                const meta = KIND_META[kind]
                const source = byKind.get(kind)
                if (!source) return null
                return (
                  <tr key={kind}>
                    <td>
                      <span className="flex items-center gap-2 font-medium text-ink-900 dark:text-ink-50">
                        <span
                          className="h-2 w-2 shrink-0 rounded-full"
                          style={{ background: meta.color }}
                          aria-hidden="true"
                        />
                        {meta.label}
                      </span>
                    </td>
                    <td className="max-w-sm truncate text-ink-500 dark:text-ink-400">
                      {humanizeTokens(source.subject_template)}
                    </td>
                    <td>
                      <div className="flex items-center justify-end">
                        <button
                          type="button"
                          className="btn-secondary px-2.5 py-1 text-xs"
                          onClick={() => setEditing(kind)}
                        >
                          Edit
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </Card>

      {editing && byKind.get(editing) && (
        <GlobalEditModal
          kind={editing}
          initial={byKind.get(editing)!}
          onClose={() => setEditing(null)}
          onSaved={load}
        />
      )}
    </>
  )
}

function OrgAdminView() {
  const toast = useToast()
  const [kind, setKind] = useState<EmailTemplateKind>('client')
  const [library, setLibrary] = useState<EmailTemplateLibrary | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [modal, setModal] = useState<
    { mode: 'create' } | { mode: 'edit' | 'view'; template: EmailTemplateOut } | null
  >(null)
  const [deleting, setDeleting] = useState<EmailTemplateOut | null>(null)
  const [activating, setActivating] = useState<EmailTemplateOut | null>(null)

  const load = () => {
    setError(null)
    api
      .get<EmailTemplateLibrary>(`/email-templates/library?kind=${kind}`)
      .then(setLibrary)
      .catch((caught) => setError(caught instanceof ApiError ? caught.message : 'Failed to load'))
  }

  useEffect(load, [kind])

  const anyOrgActive = (library?.org_templates ?? []).some((t) => t.is_active)

  // Deactivating never affects another row, so it applies immediately.
  // Activating replaces whichever template was active — that side effect
  // is confirmed first rather than just happening (and un-happening) as a
  // flicker the moment the switch is clicked.
  const deactivate = async (template: EmailTemplateOut) => {
    setBusyId(template.id)
    try {
      await api.post(`/email-templates/item/${template.id}/deactivate`)
      load()
    } catch (caught) {
      toast.show(
        'critical',
        'Could not update the template',
        caught instanceof ApiError ? caught.message : undefined,
      )
    } finally {
      setBusyId(null)
    }
  }

  const confirmActivate = async () => {
    if (!activating) return
    setBusyId(activating.id)
    try {
      await api.post(`/email-templates/item/${activating.id}/activate`)
      setActivating(null)
      load()
    } catch (caught) {
      toast.show(
        'critical',
        'Could not activate the template',
        caught instanceof ApiError ? caught.message : undefined,
      )
    } finally {
      setBusyId(null)
    }
  }

  const confirmDelete = async () => {
    if (!deleting) return
    setBusyId(deleting.id)
    try {
      await api.delete(`/email-templates/item/${deleting.id}`)
      toast.show('success', 'Template deleted')
      setDeleting(null)
      load()
    } catch (caught) {
      toast.show(
        'critical',
        'Could not delete the template',
        caught instanceof ApiError ? caught.message : undefined,
      )
    } finally {
      setBusyId(null)
    }
  }

  return (
    <>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <label className="block">
          <span className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-ink-500 dark:text-ink-400">
            Review Type
          </span>
          <select
            className="field w-64"
            value={kind}
            onChange={(event) => setKind(event.target.value as EmailTemplateKind)}
          >
            {KIND_ORDER.map((k) => (
              <option key={k} value={k}>
                {KIND_META[k].label}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className="btn-primary px-3 py-1.5 text-sm"
          onClick={() => setModal({ mode: 'create' })}
        >
          Add template
        </button>
      </div>

      {error && (
        <Banner tone="error" className="mb-4">
          {error}
        </Banner>
      )}

      <Card padded={false}>
        {library === null ? (
          <div className="space-y-3 p-5">
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
          </div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Subject</th>
                <th>Active</th>
                <th />
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>
                  <span className="font-medium text-ink-900 dark:text-ink-50">
                    {library.global_template.name}
                  </span>
                  <span className="ml-2">
                    <Chip value="info">Platform default</Chip>
                  </span>
                </td>
                <td className="max-w-sm truncate text-ink-500 dark:text-ink-400">
                  {humanizeTokens(library.global_template.subject_template)}
                </td>
                <td>
                  <Chip value={anyOrgActive ? 'disabled' : 'active'}>
                    {anyOrgActive ? 'Not in use' : 'Active'}
                  </Chip>
                </td>
                <td>
                  <div className="flex items-center justify-end">
                    <button
                      type="button"
                      className="btn-secondary px-2.5 py-1 text-xs"
                      onClick={() => setModal({ mode: 'view', template: library.global_template })}
                    >
                      View
                    </button>
                  </div>
                </td>
              </tr>

              {library.org_templates.map((template) => (
                <tr key={template.id}>
                  <td className="font-medium text-ink-900 dark:text-ink-50">{template.name}</td>
                  <td className="max-w-sm truncate text-ink-500 dark:text-ink-400">
                    {humanizeTokens(template.subject_template)}
                  </td>
                  <td>
                    <div className="flex items-center gap-2">
                      <Switch
                        checked={template.is_active}
                        disabled={busyId === template.id}
                        ariaLabel={`Toggle ${template.name} active`}
                        onChange={() =>
                          template.is_active ? deactivate(template) : setActivating(template)
                        }
                      />
                      {busyId === template.id && <Spinner />}
                    </div>
                  </td>
                  <td>
                    <div className="flex items-center justify-end gap-2">
                      <button
                        type="button"
                        className="btn-secondary px-2.5 py-1 text-xs"
                        onClick={() => setModal({ mode: 'edit', template })}
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        className="btn-ghost p-1.5 text-critical"
                        aria-label={`Delete ${template.name}`}
                        onClick={() => setDeleting(template)}
                      >
                        <IconTrash width={15} height={15} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}

              {library.org_templates.length === 0 && (
                <tr>
                  <td colSpan={4} className="py-6 text-center text-sm text-ink-400">
                    No templates of your own for this type yet — "Add template" to create one.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </Card>

      {modal?.mode === 'create' && (
        <OrgTemplateModal
          kind={kind}
          mode="create"
          initial={library?.global_template ?? null}
          onClose={() => setModal(null)}
          onSaved={load}
        />
      )}
      {modal && modal.mode !== 'create' && (
        <OrgTemplateModal
          kind={kind}
          mode={modal.mode}
          initial={modal.template}
          onClose={() => setModal(null)}
          onSaved={load}
        />
      )}

      {activating && (
        <ConfirmDialog
          title="Activate this template?"
          body="Are you sure you want to activate this template?"
          confirmLabel="Activate"
          busy={busyId === activating.id}
          onConfirm={confirmActivate}
          onCancel={() => setActivating(null)}
        />
      )}

      {deleting && (
        <Modal title="Delete template?" onClose={() => setDeleting(null)} className="max-w-sm" centered>
          <p className="text-sm text-ink-600 dark:text-ink-300">
            Are you sure you want to delete this template?
          </p>
          <div className="mt-5 flex items-center justify-end gap-2">
            <button type="button" className="btn-ghost px-3 py-1.5 text-sm" onClick={() => setDeleting(null)}>
              Cancel
            </button>
            <button
              type="button"
              className="btn-danger px-3 py-1.5 text-sm"
              disabled={busyId === deleting.id}
              onClick={confirmDelete}
            >
              {busyId === deleting.id && <Spinner />}
              Delete
            </button>
          </div>
        </Modal>
      )}
    </>
  )
}

export function EmailTemplates() {
  const { user } = useAuth()
  const isPlatform = user?.role === 'super_admin'

  return (
    <>
      <PageHeader
        title="Email Templates"
        description={
          isPlatform
            ? ''
            : "Select a review type to view its templates. Only one template can be active at a time"
        }
      />
      {isPlatform ? <SuperAdminView /> : <OrgAdminView />}
    </>
  )
}