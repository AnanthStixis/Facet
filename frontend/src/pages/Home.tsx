import { useEffect, type ReactNode } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { BrandLogo } from '../components/Logo'
import { GraphArtwork } from '../components/GraphArtwork'
import { PerspectivesIllustration } from '../components/PerspectivesIllustration'
import { useAuth } from '../store/auth'
import {
  IconArrowLeft,
  IconCheck,
  IconFile,
  IconGauge,
  IconLayers,
  IconLock,
  IconShield,
  IconTag,
  IconUsers,
} from '../components/icons'

const NAV_LINKS = [
  { href: '#about', label: 'About' },
  { href: '#why', label: 'Why Facet360' },
  { href: '#features', label: 'Features' },
  { href: '#pricing', label: 'Pricing' },
]

type FeedbackKindInfo = {
  label: string
  description: string
  tone: 'internal' | 'external'
}

const FEEDBACK_KIND_INFO: FeedbackKindInfo[] = [
  { label: 'Employee', tone: 'internal', description: 'Peer and self feedback among employees.' },
  { label: 'Management', tone: 'internal', description: 'Upward feedback about a manager.' },
  { label: 'Client', tone: 'external', description: 'Feedback collected from a client outside your organization.' },
  { label: 'Product', tone: 'external', description: 'Feedback tied to a specific product.' },
  { label: 'Service', tone: 'external', description: 'Feedback tied to a specific service rendered.' },
  { label: 'Proposal', tone: 'external', description: 'Feedback tied to a specific business proposal.' },
]

function HomeHeader() {
  return (
    <header className="sticky top-0 z-20 border-b border-ink-200 bg-white dark:border-ink-800 dark:bg-ink-950">
      <div className="flex w-full items-center justify-between px-6 py-4">
        <Link to="/home" className="flex items-center">
          <BrandLogo height={26} />
        </Link>
        <nav className="hidden items-center gap-7 md:flex">
          {NAV_LINKS.map((item) => (
            <a
              key={item.href}
              href={item.href}
              className="text-base font-medium text-ink-500 transition hover:text-ink-900 dark:text-ink-400 dark:hover:text-white"
            >
              {item.label}
            </a>
          ))}
        </nav>
        <div className="flex items-center gap-3">
          <Link to="/login" className="btn-ghost px-3 py-1.5 text-sm">
            Log in
          </Link>
          <Link to="/signup" className="btn-primary px-3.5 py-1.5 text-sm">
            Register here
          </Link>
        </div>
      </div>
    </header>
  )
}

function Section({
  id,
  className,
  children,
}: {
  id?: string
  className?: string
  children: ReactNode
}) {
  return (
    <section id={id} className={className}>
      <div className="mx-auto max-w-6xl px-6">{children}</div>
    </section>
  )
}

function Hero() {
  return (
    <div className="relative overflow-hidden bg-white dark:bg-ink-950">
      <div
        className="absolute inset-0 opacity-[0.35] dark:opacity-[0.06]"
        style={{
          backgroundImage:
            'linear-gradient(rgba(18,22,28,0.05) 1px, transparent 1px), linear-gradient(90deg, rgba(18,22,28,0.05) 1px, transparent 1px)',
          backgroundSize: '36px 36px',
        }}
      />
      <div
        className="absolute -left-24 top-10 h-96 w-96 rounded-full blur-3xl"
        style={{ background: 'radial-gradient(circle, rgba(47,111,98,0.16), transparent 68%)' }}
      />
      <div
        className="absolute -right-24 bottom-0 h-80 w-80 rounded-full blur-3xl"
        style={{ background: 'radial-gradient(circle, rgba(53,114,176,0.12), transparent 68%)' }}
      />
      <Section className="relative py-16 lg:py-20">
        <div className="flex flex-col gap-14 lg:flex-row lg:items-center lg:gap-16">
          <div className="relative w-full lg:w-[55%] lg:shrink-0">
            <div
              className="absolute -inset-8 -z-10 rounded-[2.5rem] blur-2xl motion-reduce:animate-none animate-[hero-glow_6s_ease-in-out_infinite]"
              style={{
                background:
                  'radial-gradient(circle, rgba(47,111,98,0.16), rgba(53,114,176,0.08) 55%, transparent 75%)',
              }}
            />
            <div className="relative overflow-hidden rounded-[2rem] border border-ink-100 p-8 shadow-[0_24px_60px_-24px_rgba(18,22,28,0.2)] dark:border-ink-800 lg:p-12">
              <div
                className="absolute inset-0"
                style={{
                  background:
                    'radial-gradient(circle at 28% 22%, rgba(53,114,176,0.07), transparent 55%), radial-gradient(circle at 72% 82%, rgba(47,111,98,0.09), transparent 55%)',
                }}
              />
              <div
                className="absolute inset-0 opacity-70 dark:opacity-15"
                style={{
                  backgroundImage: 'radial-gradient(rgba(18,22,28,0.09) 1px, transparent 1px)',
                  backgroundSize: '18px 18px',
                }}
              />
              <div className="relative animate-fade-up">
                <GraphArtwork />
              </div>
            </div>

            <div className="absolute -left-6 top-6 hidden w-48 rounded-2xl border border-ink-100 bg-white p-3.5 shadow-lg motion-reduce:animate-none animate-[float-a_5s_ease-in-out_infinite] dark:border-ink-700 dark:bg-ink-900 lg:block">
              <div className="flex items-center gap-2.5">
                <span className="accent-soft-bg accent-text flex h-8 w-8 shrink-0 items-center justify-center rounded-lg">
                  <IconGauge width={16} height={16} />
                </span>
                <div>
                  <p className="text-2xs font-medium text-ink-500 dark:text-ink-400">Feedback Coverage</p>
                  <p className="accent-text text-lg font-semibold leading-tight">360°</p>
                </div>
              </div>
              <p className="mt-1 text-2xs text-ink-400 dark:text-ink-500">Connected perspectives</p>
            </div>

            <div className="absolute -bottom-6 left-2 hidden w-52 rounded-2xl border border-ink-100 bg-white p-3.5 shadow-lg motion-reduce:animate-none animate-[float-a_5.5s_ease-in-out_infinite] dark:border-ink-700 dark:bg-ink-900 lg:block">
              <div className="flex items-center gap-2.5">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-external/10 text-external">
                  <IconUsers width={16} height={16} />
                </span>
                <p className="text-sm font-semibold text-ink-900 dark:text-ink-50">Feedback Types</p>
              </div>
              <p className="mt-1.5 text-2xs leading-snug text-ink-500 dark:text-ink-400">
                Employee · Client · Product · Service · Proposal
              </p>
            </div>

            <style>{`
              @keyframes hero-glow { 0%, 100% { opacity: 0.75; transform: scale(1); } 50% { opacity: 1; transform: scale(1.05); } }
              @keyframes float-a { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-6px); } }
              @keyframes float-b { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(6px); } }
            `}</style>
          </div>

          <div className="animate-fade-up text-center lg:flex-1 lg:text-left">
            <div className="inline-flex flex-col items-center gap-2 lg:items-start">
              <span className="accent-text text-2xs font-semibold uppercase tracking-[0.14em]">
                360° Feedback & Insights
              </span>
              <span className="accent-bg h-0.5 w-10 rounded-full" />
            </div>

            <h1 className="mx-auto mt-5 max-w-md text-4xl font-bold leading-[1.15] tracking-[-0.03em] text-ink-900 dark:text-white lg:mx-0 lg:text-5xl">
              Bring Every Perspective Into <span className="accent-text">Focus.</span>
            </h1>

            <p className="mx-auto mt-5 max-w-md text-base leading-relaxed text-ink-500 dark:text-ink-400 lg:mx-0">
              Facet360 brings employee, manager, client, product, service, and
              proposal feedback together in one connected view — helping you
              uncover meaningful insights and make better decisions.
            </p>

            <div className="mt-8 flex flex-wrap justify-center gap-3 lg:justify-start">
              <Link to="/signup" className="btn-primary inline-flex items-center gap-1.5 px-5 py-2.5">
                Get Started
                <IconArrowLeft width={16} height={16} className="rotate-180" />
              </Link>
              <a href="#features" className="btn-secondary inline-flex items-center gap-1.5 px-5 py-2.5">
                Explore Features
                <IconArrowLeft width={16} height={16} className="rotate-180" />
              </a>
            </div>
          </div>
        </div>
      </Section>
    </div>
  )
}

function About() {
  return (
    <Section id="about" className="py-16 lg:py-20">
      <div className="grid gap-10 lg:grid-cols-[1fr_1.05fr] lg:items-center lg:gap-14">
        <div className="animate-fade-up rounded-3xl border border-ink-100 bg-ink-50/60 p-6 dark:border-ink-800 dark:bg-ink-900/30">
          <PerspectivesIllustration />
        </div>
        <div>
          <span className="accent-text text-2xs font-semibold uppercase tracking-[0.12em]">
            One connected view
          </span>
          <h2 className="mt-3 text-3xl font-semibold tracking-[-0.02em] text-ink-900 dark:text-white">
            Bring every perspective together
          </h2>
          <div className="mt-5 space-y-4 text-base leading-relaxed text-ink-600 dark:text-ink-300">
            <p>
              Feedback is most valuable when you can see the complete picture.
              Facet360 brings employee, manager, client, product, service, and
              proposal feedback together in one connected platform.
            </p>
            <p>
              Run structured feedback cycles, collect responses from internal
              teams and external reviewers, and turn that information into clear
              insights and actionable reports. Instead of managing feedback
              across spreadsheets, forms, emails, and disconnected tools, your
              organization gets one consistent view of how people, teams,
              clients, and opportunities are performing.
            </p>
          </div>
        </div>
      </div>
    </Section>
  )
}

function WhyCard({
  icon,
  title,
  children,
}: {
  icon: ReactNode
  title: string
  children: ReactNode
}) {
  return (
    <div className="group relative rounded-[20px] border border-ink-200 bg-white p-7 shadow-card transition-all duration-300 ease-out hover:-translate-y-1.5 hover:border-[var(--accent)] hover:bg-[var(--accent-soft)] hover:shadow-[0_16px_38px_-12px_rgba(47,111,98,0.3)] dark:border-ink-700 dark:bg-ink-900 dark:hover:border-[var(--accent)]">
      <span className="accent-soft-bg accent-text flex h-11 w-11 items-center justify-center rounded-xl">
        {icon}
      </span>
      <h3 className="mt-4 text-lg font-semibold text-ink-900 dark:text-ink-50">{title}</h3>
      <p className="mt-2 text-sm leading-relaxed text-ink-500 dark:text-ink-400">{children}</p>
    </div>
  )
}

function WhyChooseUs() {
  return (
    <div className="relative overflow-hidden bg-ink-50 dark:bg-ink-900/40">
      <div
        className="absolute inset-0 opacity-[0.35] dark:opacity-[0.06]"
        style={{
          backgroundImage:
            'linear-gradient(rgba(18,22,28,0.05) 1px, transparent 1px), linear-gradient(90deg, rgba(18,22,28,0.05) 1px, transparent 1px)',
          backgroundSize: '36px 36px',
        }}
      />
      <div
        className="absolute -left-20 top-0 h-80 w-80 rounded-full blur-3xl"
        style={{ background: 'radial-gradient(circle, rgba(47,111,98,0.14), transparent 68%)' }}
      />
      <div
        className="absolute -right-20 bottom-0 h-80 w-80 rounded-full blur-3xl"
        style={{ background: 'radial-gradient(circle, rgba(47,111,98,0.12), transparent 68%)' }}
      />
      <Section id="why" className="relative py-20 lg:py-24">
        <div className="mx-auto max-w-2xl text-center">
          <div className="flex items-center justify-center gap-4">
            <span className="h-px w-10 bg-ink-200 dark:bg-ink-700" />
            <span className="accent-text text-2xs font-semibold uppercase tracking-[0.12em]">
              Why choose Facet360
            </span>
            <span className="h-px w-10 bg-ink-200 dark:bg-ink-700" />
          </div>
          <h2 className="mt-4 text-4xl font-bold tracking-[-0.02em] text-ink-900 dark:text-white lg:text-5xl">
            Why choose Facet360
          </h2>
          <p className="mx-auto mt-4 max-w-lg text-base text-ink-500 dark:text-ink-400">
            Everything you need to collect feedback, understand it, and take
            action that drives real improvement.
          </p>
        </div>
        <div className="mt-14 grid gap-7 sm:grid-cols-2">
          <WhyCard icon={<IconLayers width={20} height={20} />} title="One connected feedback platform">
            Bring internal reviews and external feedback together instead of
            managing separate tools for each relationship.
          </WhyCard>
          <WhyCard icon={<IconUsers width={20} height={20} />} title="Built for every relationship">
            Collect feedback from employees, managers, clients, product users,
            service recipients, and proposal stakeholders through structured
            workflows.
          </WhyCard>
          <WhyCard icon={<IconShield width={20} height={20} />} title="Secure external feedback">
            Invite clients and other external reviewers through secure,
            single-use links.
          </WhyCard>
          <WhyCard icon={<IconTag width={20} height={20} />} title="Designed for your organization">
            Keep the experience aligned with your brand through
            organization-specific logos, emails, reports, and controlled access.
          </WhyCard>
        </div>
      </Section>
    </div>
  )
}

function FeatureCard({
  icon,
  title,
  children,
}: {
  icon: ReactNode
  title: string
  children: ReactNode
}) {
  return (
    <div className="rounded-[20px] border border-ink-200 bg-white p-7 shadow-card transition-all duration-300 ease-out hover:-translate-y-1.5 hover:border-[var(--accent)] hover:bg-[var(--accent-soft)] hover:shadow-[0_16px_38px_-12px_rgba(47,111,98,0.3)] dark:border-ink-700 dark:bg-ink-900 dark:hover:border-[var(--accent)]">
      <span className="accent-soft-bg accent-text flex h-11 w-11 items-center justify-center rounded-xl">
        {icon}
      </span>
      <h3 className="mt-4 text-lg font-semibold text-ink-900 dark:text-ink-50">{title}</h3>
      <p className="mt-2 text-sm leading-relaxed text-ink-500 dark:text-ink-400">{children}</p>
    </div>
  )
}

function Features() {
  return (
    <Section id="features" className="py-20 lg:py-24">
      <div className="mx-auto max-w-2xl text-center">
        <span className="accent-text text-2xs font-semibold uppercase tracking-[0.12em]">
          Platform features
        </span>
        <h2 className="mt-3 text-4xl font-bold tracking-[-0.02em] text-ink-900 dark:text-white lg:text-5xl">
          What's included
        </h2>
        <p className="mx-auto mt-4 max-w-lg text-base text-ink-500 dark:text-ink-400">
          Six feedback kinds, run through the same cycles and reported on
          together.
        </p>
      </div>

      <div className="mx-auto mt-8 grid max-w-4xl grid-cols-2 gap-3 sm:grid-cols-3">
        {FEEDBACK_KIND_INFO.map((kind) => (
          <div
            key={kind.label}
            className={
              kind.tone === 'internal'
                ? 'rounded-xl border border-internal/25 bg-internal/5 p-4 dark:border-internal/40 dark:bg-internal/10'
                : 'rounded-xl border border-external/25 bg-external/5 p-4 dark:border-external/40 dark:bg-external/10'
            }
          >
            <p className={kind.tone === 'internal' ? 'text-sm font-semibold text-internal' : 'text-sm font-semibold text-external'}>
              {kind.label}
            </p>
            <p className="mt-1 text-xs leading-relaxed text-ink-500 dark:text-ink-400">
              {kind.description}
            </p>
          </div>
        ))}
      </div>

      <div className="mt-14 grid gap-6 sm:grid-cols-2">
        <FeatureCard icon={<IconLayers width={20} height={20} />} title="Cycles & campaigns">
          Run structured, repeatable feedback rounds instead of one-off requests.
        </FeatureCard>
        <FeatureCard icon={<IconGauge width={20} height={20} />} title="Role-based dashboards">
          Super Admins, Client Admins, Managers, and Employees each see what's
          relevant to them.
        </FeatureCard>
        <FeatureCard icon={<IconFile width={20} height={20} />} title="Exportable reports">
          PDF and Excel exports for any cycle, campaign, or insight.
        </FeatureCard>
        <FeatureCard icon={<IconLock width={20} height={20} />} title="Session security & audit trail">
          See and revoke active sessions per device, with a full record of
          platform activity.
        </FeatureCard>
      </div>
    </Section>
  )
}

type PlanFeature = {
  label: string
  included: boolean
}

type Tier = {
  name: string
  // The real value the backend's OrgPlan understands — this display name
  // (Basic/Standard/Enterprise) is marketing copy only; `value` is what
  // actually gets sent to /auth/self-register.
  value: string
  price: string
  limit: string
  cta: string
  highlighted?: boolean
  badge?: string
  features: PlanFeature[]
}

const TIERS: Tier[] = [
  {
    name: 'Basic',
    value: 'starter',
    price: '₹2,499',
    limit: '1 Admin + 50 Users',
    cta: 'Get Started',
    features: [
      { label: 'Employee & Management Review', included: true },
      { label: 'Export Results — Only export option available in Results page', included: true },
      { label: 'Client, Product, Service & Proposal Feedback', included: false },
      { label: 'All export options (PDF, Excel, full reports)', included: false },
    ],
  },
  {
    name: 'Standard',
    value: 'growth',
    price: '₹7,999',
    limit: '3 Admins + 150 Users',
    cta: 'Get Started',
    highlighted: true,
    badge: 'Most Popular',
    features: [
      { label: 'Employee & Management Review', included: true },
      { label: 'Client, Product, Service & Proposal Feedback', included: true },
      { label: 'All export options (PDF, Excel, full reports)', included: true },
    ],
  },
  {
    name: 'Enterprise',
    value: 'enterprise',
    price: '₹14,999',
    limit: 'Unlimited Admins & Users',
    cta: 'Get Started',
    features: [
      { label: 'Employee & Management Review', included: true },
      { label: 'Client, Product, Service & Proposal Feedback', included: true },
      { label: 'All export options (PDF, Excel, full reports)', included: true },
    ],
  },
]

// Higher number = higher tier. Used to disable a signed-in visitor's
// current plan and anything below it, leaving only real upgrades clickable.
const PLAN_ORDER: Record<string, number> = { starter: 0, growth: 1, enterprise: 2 }

function PricingCard({ tier, disabled, isCurrent }: { tier: Tier; disabled: boolean; isCurrent: boolean }) {
  return (
    <div
      className={
        tier.highlighted
          ? 'relative rounded-lg border-2 accent-border bg-white p-7 shadow-lg transition-all duration-300 ease-out hover:-translate-y-1.5 hover:shadow-[0_16px_40px_-10px_rgba(47,111,98,0.32)] dark:bg-ink-900'
          : 'relative rounded-lg border border-ink-200 bg-white p-7 shadow-card transition-all duration-300 ease-out hover:-translate-y-1.5 hover:border-ink-300 hover:shadow-[0_14px_34px_-10px_rgba(47,111,98,0.22)] dark:border-ink-700 dark:bg-ink-900 dark:hover:border-ink-600'
      }
    >
      {tier.badge && (
        <span className="accent-bg absolute -top-3 left-7 rounded-full px-3 py-1 text-2xs font-semibold uppercase tracking-[0.08em] text-white">
          {tier.badge}
        </span>
      )}
      <h3 className="text-lg font-semibold text-ink-900 dark:text-ink-50">{tier.name}</h3>

      <div className="mt-4 flex items-baseline gap-1.5">
        <span className="text-3xl font-semibold tracking-[-0.02em] text-ink-900 dark:text-white">
          {tier.price}
        </span>
        <span className="text-xs text-ink-500 dark:text-ink-400">/year</span>
      </div>

      <p className="mt-2 text-base font-semibold text-ink-700 dark:text-ink-200">
        {tier.limit}
      </p>

      <ul className="mt-6 space-y-2.5 border-t border-ink-100 pt-6 dark:border-ink-800">
        {tier.features.map((feature) => (
          <li
            key={feature.label}
            className={
              feature.included
                ? 'flex items-start gap-2 text-sm text-ink-600 dark:text-ink-300'
                : 'flex items-start gap-2 text-sm text-ink-400 dark:text-ink-500'
            }
          >
            {feature.included ? (
              <IconCheck width={16} height={16} className="mt-0.5 shrink-0 accent-text" />
            ) : (
              <span className="mt-0.5 w-4 shrink-0 text-center text-ink-300 dark:text-ink-600" aria-hidden="true">
                ✗
              </span>
            )}
            {feature.label}
          </li>
        ))}
      </ul>

      {disabled ? (
        <span
          className={
            tier.highlighted
              ? 'btn-primary mt-7 flex w-full cursor-not-allowed items-center justify-center py-2.5 opacity-50'
              : 'btn-secondary mt-7 flex w-full cursor-not-allowed items-center justify-center py-2.5 opacity-50'
          }
        >
          {isCurrent ? 'Current plan' : 'Not available'}
        </span>
      ) : (
        <Link
          to={`/signup?plan=${tier.value}`}
          className={
            tier.highlighted
              ? 'btn-primary mt-7 w-full py-2.5 shadow-card transition-all duration-200 hover:-translate-y-0.5 hover:shadow-lg'
              : 'btn-secondary mt-7 w-full py-2.5 transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md'
          }
        >
          {tier.cta}
        </Link>
      )}
    </div>
  )
}

function Pricing() {
  // Only meaningful for a signed-in visitor who arrived via the in-app
  // "Upgrade" link — a stranger seeing this page for the first time has no
  // organization, so every tier stays enabled for them.
  const currentPlan = useAuth((state) => state.organization?.plan)

  return (
    <div className="relative overflow-hidden bg-ink-50 dark:bg-ink-900/40">
      <div
        className="absolute inset-0 opacity-[0.35] dark:opacity-[0.06]"
        style={{
          backgroundImage:
            'linear-gradient(rgba(18,22,28,0.05) 1px, transparent 1px), linear-gradient(90deg, rgba(18,22,28,0.05) 1px, transparent 1px)',
          backgroundSize: '36px 36px',
        }}
      />
      <div
        className="absolute -right-24 top-1/4 h-96 w-96 rounded-full blur-3xl"
        style={{ background: 'radial-gradient(circle, rgba(47,111,98,0.14), transparent 68%)' }}
      />
      <Section id="pricing" className="relative py-20 lg:py-24">
        <div className="mx-auto max-w-2xl text-center">
          <span className="accent-text text-2xs font-semibold uppercase tracking-[0.12em]">
            Plans & pricing
          </span>
          <h2 className="mt-3 text-3xl font-semibold tracking-[-0.02em] text-ink-900 dark:text-white">
            Plans that grow with you
          </h2>
          <p className="mx-auto mt-3 max-w-lg text-base text-ink-500 dark:text-ink-400">
            Choose the plan that fits your organization's size and feedback needs.
          </p>
        </div>
        <div className="mt-12 grid gap-6 lg:grid-cols-3">
          {TIERS.map((tier) => (
            <PricingCard
              key={tier.name}
              tier={tier}
              disabled={Boolean(currentPlan) && PLAN_ORDER[tier.value] <= PLAN_ORDER[currentPlan as string]}
              isCurrent={tier.value === currentPlan}
            />
          ))}
        </div>
        <div className="mt-10 flex justify-center">
          <div className="inline-flex items-center gap-2 rounded-full border border-ink-200 bg-white px-4 py-2 text-xs text-ink-500 dark:border-ink-700 dark:bg-ink-900 dark:text-ink-400">
            <IconLock width={14} height={14} className="shrink-0" />
            All plans include secure access, data isolation and audit trail.
          </div>
        </div>
      </Section>
    </div>
  )
}

function HomeFooter() {
  return (
    <footer className="border-t border-ink-200 py-10 dark:border-ink-800">
      <div className="mx-auto flex max-w-6xl flex-col items-center gap-4 px-6 text-center">
        <BrandLogo height={22} />
        <nav className="flex flex-wrap justify-center gap-x-6 gap-y-2">
          {NAV_LINKS.map((item) => (
            <a
              key={item.href}
              href={item.href}
              className="text-sm text-ink-500 hover:text-ink-800 dark:text-ink-400 dark:hover:text-ink-100"
            >
              {item.label}
            </a>
          ))}
        </nav>
        <p className="flex items-center gap-1.5 text-2xs text-ink-400">
          <IconLock width={12} height={12} />
          Powered by Stixis AI Solutions © Copyright 2026-2027
        </p>
      </div>
    </footer>
  )
}

export function Home() {
  const location = useLocation()

  // Anchor nav links (#about, #why, ...) should ease-scroll rather than jump —
  // scoped to this page's lifetime rather than a global CSS change, since no
  // other screen in the app has same-page anchor navigation.
  useEffect(() => {
    const previous = document.documentElement.style.scrollBehavior
    document.documentElement.style.scrollBehavior = 'smooth'
    return () => {
      document.documentElement.style.scrollBehavior = previous
    }
  }, [])

  // Arriving here with a hash (e.g. the sidebar's "Upgrade" link, which
  // points to /home#pricing) is a full route change, not an in-page anchor
  // click — React Router doesn't scroll to the fragment the way a real
  // browser navigation would, so this does it by hand.
  useEffect(() => {
    if (!location.hash) return
    document.getElementById(location.hash.slice(1))?.scrollIntoView({ behavior: 'smooth' })
  }, [location.hash])

  return (
    <div className="bg-white dark:bg-ink-950">
      <HomeHeader />
      <Hero />
      <About />
      <WhyChooseUs />
      <Features />
      <Pricing />
      <HomeFooter />
    </div>
  )
}