import { useEffect, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { BrandLogo, FacetMark } from '../components/Logo'
import { GraphArtwork } from '../components/GraphArtwork'
import { PerspectivesIllustration } from '../components/PerspectivesIllustration'
import {
  IconBriefcase,
  IconCheck,
  IconFile,
  IconGauge,
  IconLayers,
  IconLock,
  IconShield,
  IconSpark,
  IconTag,
  IconUsers,
} from '../components/icons'

const NAV_LINKS = [
  { href: '#about', label: 'About' },
  { href: '#why', label: 'Why Facet360' },
  { href: '#features', label: 'Features' },
  { href: '#pricing', label: 'Pricing' },
]

const FEEDBACK_KINDS = ['Employee', 'Management', 'Client', 'Product', 'Service', 'Proposal']

function HomeHeader() {
  return (
    <header className="sticky top-0 z-20 border-b border-ink-200 bg-white dark:border-ink-800 dark:bg-ink-950">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
        <Link to="/home" className="flex items-center">
          <BrandLogo height={26} />
        </Link>
        <nav className="hidden items-center gap-7 md:flex">
          {NAV_LINKS.map((item) => (
            <a
              key={item.href}
              href={item.href}
              className="text-sm font-medium text-ink-500 transition hover:text-ink-900 dark:text-ink-400 dark:hover:text-white"
            >
              {item.label}
            </a>
          ))}
        </nav>
        <div className="flex items-center gap-3">
          <Link to="/login" className="btn-ghost px-3 py-1.5 text-sm">
            Log in
          </Link>
          <Link to="/register" className="btn-primary px-3.5 py-1.5 text-sm">
            Request access
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

function Legend() {
  return (
    <div className="flex flex-wrap gap-x-6 gap-y-2 text-2xs uppercase tracking-[0.12em] text-ink-500 dark:text-ink-500">
      <span className="flex items-center gap-1.5">
        <span className="h-1.5 w-1.5 rounded-full bg-internal" /> Internal 360
      </span>
      <span className="flex items-center gap-1.5">
        <span className="h-1.5 w-1.5 rounded-full bg-external" /> Client experience
      </span>
      <span className="flex items-center gap-1.5">
        <span className="h-1.5 w-1.5 rounded-full bg-external opacity-60" /> Proposal quality
      </span>
    </div>
  )
}

function Hero() {
  return (
    <div className="relative overflow-hidden">
      <div
        className="absolute inset-0 opacity-[0.35] dark:opacity-[0.06]"
        style={{
          backgroundImage:
            'linear-gradient(rgba(18,22,28,0.05) 1px, transparent 1px), linear-gradient(90deg, rgba(18,22,28,0.05) 1px, transparent 1px)',
          backgroundSize: '36px 36px',
        }}
      />
      <div
        className="absolute -left-24 top-1/3 h-96 w-96 rounded-full blur-3xl"
        style={{ background: 'radial-gradient(circle, rgba(47,111,98,0.16), transparent 68%)' }}
      />
      <Section className="relative py-14 lg:py-16">
        <div className="flex flex-col items-center gap-10 lg:flex-row lg:items-center lg:gap-14">
          <div className="w-full max-w-xs shrink-0 animate-fade-up lg:w-2/5">
            <GraphArtwork />
          </div>
          <div className="animate-fade-up text-center lg:flex-1 lg:text-left">
          <h1 className="text-4xl font-semibold leading-tight tracking-[-0.03em] text-ink-900 dark:text-white lg:text-5xl">
            Every relationship has more than one side.
          </h1>
          <p className="mx-auto mt-5 max-w-lg text-base leading-relaxed text-ink-500 dark:text-ink-400 lg:mx-0">
            Facet360 runs employee, manager, client, and proposal feedback in a single
            graph — so you can see whether the teams working well together are the
            ones actually winning the work.
          </p>
          <div className="mt-9 flex justify-center lg:justify-start">
            <Legend />
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
          <div className="mt-6 flex items-center gap-5 rounded-2xl border border-ink-200 bg-ink-50/60 p-5 dark:border-ink-800 dark:bg-ink-900/30">
            <div className="shrink-0 text-center">
              <p className="accent-text text-3xl font-semibold tracking-[-0.02em]">6</p>
              <p className="mt-0.5 text-2xs uppercase tracking-[0.1em] text-ink-500 dark:text-ink-400">
                Perspectives
              </p>
            </div>
            <div className="h-10 w-px shrink-0 bg-ink-200 dark:bg-ink-700" />
            <p className="text-base font-medium leading-snug text-ink-900 dark:text-ink-50">
              From collecting feedback to understanding what it means — Facet360
              connects the entire process.
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
    <div className="surface p-6">
      <span className="accent-soft-bg accent-text flex h-10 w-10 items-center justify-center rounded-md">
        {icon}
      </span>
      <h3 className="mt-4 text-lg font-semibold text-ink-900 dark:text-ink-50">{title}</h3>
      <p className="mt-2 text-sm leading-relaxed text-ink-500 dark:text-ink-400">{children}</p>
    </div>
  )
}

function WhyChooseUs() {
  return (
    <Section id="why" className="bg-ink-50 py-20 dark:bg-ink-900/40 lg:py-24">
      <h2 className="text-3xl font-semibold tracking-[-0.02em] text-ink-900 dark:text-white">
        Why choose Facet360
      </h2>
      <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
        <WhyCard icon={<IconLayers width={20} height={20} />} title="One connected feedback platform">
          Bring internal reviews and external feedback together instead of
          managing separate tools for each relationship.
        </WhyCard>
        <WhyCard icon={<IconUsers width={20} height={20} />} title="Built for every relationship">
          Collect feedback from employees, managers, clients, product users,
          service recipients, and proposal stakeholders through structured
          workflows.
        </WhyCard>
        <WhyCard icon={<IconSpark width={20} height={20} />} title="Actionable insights, not just responses">
          Surface trends, themes, sentiment, participation gaps, and areas that
          need attention so teams know where to focus.
        </WhyCard>
        <WhyCard icon={<IconShield width={20} height={20} />} title="Secure external feedback">
          Invite clients and other external reviewers through secure,
          single-use links — no account or password required.
        </WhyCard>
        <WhyCard icon={<IconBriefcase width={20} height={20} />} title="Data-driven decisions">
          Use historical feedback and proposal outcomes to identify trends and
          support better decisions with predictive analytics.
        </WhyCard>
        <WhyCard icon={<IconTag width={20} height={20} />} title="Designed for your organization">
          Keep the experience aligned with your brand through
          organization-specific logos, emails, reports, and controlled access.
        </WhyCard>
      </div>
    </Section>
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
    <div className="flex gap-4">
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-ink-100 text-ink-600 dark:bg-ink-800 dark:text-ink-300">
        {icon}
      </span>
      <div>
        <h3 className="text-base font-semibold text-ink-900 dark:text-ink-50">{title}</h3>
        <p className="mt-1 text-sm leading-relaxed text-ink-500 dark:text-ink-400">{children}</p>
      </div>
    </div>
  )
}

function Features() {
  return (
    <Section id="features" className="py-20 lg:py-24">
      <div className="max-w-2xl">
        <h2 className="text-3xl font-semibold tracking-[-0.02em] text-ink-900 dark:text-white">
          What's included
        </h2>
        <p className="mt-3 text-base text-ink-500 dark:text-ink-400">
          Six feedback kinds, run through the same cycles and reported on
          together.
        </p>
        <div className="mt-5 flex flex-wrap gap-2">
          {FEEDBACK_KINDS.map((kind) => (
            <span
              key={kind}
              className="rounded-full border border-ink-200 px-3 py-1 text-sm text-ink-600 dark:border-ink-700 dark:text-ink-300"
            >
              {kind}
            </span>
          ))}
        </div>
      </div>

      <div className="mt-12 grid gap-x-10 gap-y-9 sm:grid-cols-2">
        <FeatureCard icon={<IconLayers width={20} height={20} />} title="Cycles & campaigns">
          Run structured, repeatable feedback rounds instead of one-off requests.
        </FeatureCard>
        <FeatureCard icon={<IconGauge width={20} height={20} />} title="Role-based dashboards">
          Super Admins, Client Admins, Managers, and Employees each see what's
          relevant to them.
        </FeatureCard>
        <FeatureCard icon={<IconSpark width={20} height={20} />} title="Insights engine">
          Automatic findings — low participation, sharp declines, negative
          sentiment clusters, stalled campaigns — surfaced without anyone
          digging for them.
        </FeatureCard>
        <FeatureCard icon={<IconBriefcase width={20} height={20} />} title="Predictive analytics">
          Win-probability and trend forecasts for proposals, built on your own
          feedback history.
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
  limit: string
  cta: string
  highlighted?: boolean
  badge?: string
  features: PlanFeature[]
}

const TIERS: Tier[] = [
  {
    name: 'Basic',
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
    limit: 'Unlimited Admins & Users',
    cta: 'Get Started',
    features: [
      { label: 'Employee & Management Review', included: true },
      { label: 'Client, Product, Service & Proposal Feedback', included: true },
      { label: 'All export options (PDF, Excel, full reports)', included: true },
    ],
  },
]

function PricingCard({ tier }: { tier: Tier }) {
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

      <p className="mt-4 text-xl font-semibold tracking-[-0.01em] text-ink-900 dark:text-white">
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

      <Link
        to="/register"
        className={
          tier.highlighted
            ? 'btn-primary mt-7 w-full py-2.5 shadow-card transition-all duration-200 hover:-translate-y-0.5 hover:shadow-lg'
            : 'btn-secondary mt-7 w-full py-2.5 transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md'
        }
      >
        {tier.cta}
      </Link>
    </div>
  )
}

function Pricing() {
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
            <PricingCard key={tier.name} tier={tier} />
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

function LoginCta() {
  return (
    <Section id="login" className="py-20 lg:py-24">
      <div className="surface flex flex-col items-center gap-5 px-6 py-14 text-center">
        <FacetMark size={32} />
        <h2 className="text-3xl font-semibold tracking-[-0.02em] text-ink-900 dark:text-white">
          Ready to see it?
        </h2>
        <p className="max-w-md text-base text-ink-500 dark:text-ink-400">
          Sign in if your organization already has a Facet360 account, or request
          access to get your organization set up.
        </p>
        <div className="mt-2 flex flex-wrap justify-center gap-3">
          <Link to="/login" className="btn-secondary px-5 py-2.5">
            Log in
          </Link>
          <Link to="/register" className="btn-primary px-5 py-2.5">
            Request access
          </Link>
        </div>
      </div>
    </Section>
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

  return (
    <div className="bg-white dark:bg-ink-950">
      <HomeHeader />
      <Hero />
      <About />
      <WhyChooseUs />
      <Features />
      <Pricing />
      <LoginCta />
      <HomeFooter />
    </div>
  )
}