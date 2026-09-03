import { useEffect, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { BrandLogo, FacetMark } from '../components/Logo'
import { GraphArtwork } from '../components/GraphArtwork'
import {
  IconBriefcase,
  IconCheck,
  IconFile,
  IconGauge,
  IconLayers,
  IconLock,
  IconSend,
  IconShield,
  IconSpark,
  IconTag,
  IconUsers,
} from '../components/icons'

const NAV_LINKS = [
  { href: '#about', label: 'About' },
  { href: '#why', label: 'Why Facet' },
  { href: '#features', label: 'Features' },
  { href: '#pricing', label: 'Pricing' },
]

function HomeHeader() {
  return (
    <header className="sticky top-0 z-20 border-b border-ink-200 bg-white/85 backdrop-blur dark:border-ink-800 dark:bg-ink-950/85">
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
      <Section className="relative grid gap-12 py-20 lg:grid-cols-2 lg:items-center lg:py-28">
        <div className="animate-fade-up">
          <h1 className="text-4xl font-semibold leading-tight tracking-[-0.03em] text-ink-900 dark:text-white lg:text-5xl">
            Every relationship has more than one side.
          </h1>
          <p className="mt-5 max-w-md text-base leading-relaxed text-ink-500 dark:text-ink-400">
            Facet runs employee, manager, client, and proposal feedback in a single
            graph — so you can see whether the teams working well together are the
            ones actually winning the work.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link to="/register" className="btn-primary px-5 py-2.5">
              Request access
            </Link>
            <Link to="/login" className="btn-secondary px-5 py-2.5">
              Log in
            </Link>
          </div>
          <div className="mt-9">
            <Legend />
          </div>
        </div>
        <div className="mx-auto w-full max-w-md animate-fade-up">
          <GraphArtwork />
        </div>
      </Section>
    </div>
  )
}

function About() {
  return (
    <Section id="about" className="py-20 lg:py-24">
      <div className="grid gap-10 lg:grid-cols-[0.9fr_1.1fr] lg:gap-16">
        <div>
          <h2 className="text-3xl font-semibold tracking-[-0.02em] text-ink-900 dark:text-white">
            One platform for feedback on both sides of the table
          </h2>
        </div>
        <div className="space-y-4 text-base leading-relaxed text-ink-600 dark:text-ink-300">
          <p>
            Most organizations run two separate systems: an internal tool for
            employee and manager reviews, and a scattered mix of surveys,
            spreadsheets, and inboxes for client, product, and proposal feedback.
            Facet puts both in one place — the same cycles, the same reporting,
            the same platform.
          </p>
          <p>
            Every organization on Facet runs in its own isolated space,
            multi-tenant by design and enforced at the database level rather than
            left to application code to get right. Feedback moves through
            structured cycles and campaigns, gets analyzed automatically, and
            rolls up into reports your team can act on — not just file away.
          </p>
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
        Why teams choose Facet
      </h2>
      <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
        <WhyCard icon={<IconShield width={20} height={20} />} title="Isolation enforced by the database">
          Every tenant table is protected by Postgres row-level security, not just
          application-level filters. One organization's data is structurally
          unable to reach another's.
        </WhyCard>
        <WhyCard icon={<IconLayers width={20} height={20} />} title="One graph, not two tools">
          Employee and manager reviews sit next to client, product, service, and
          proposal feedback — run from the same cycles and reported on together.
        </WhyCard>
        <WhyCard icon={<IconUsers width={20} height={20} />} title="Onboarding stays in your control">
          New organizations register themselves, but nothing goes live until an
          administrator approves it.
        </WhyCard>
        <WhyCard icon={<IconSend width={20} height={20} />} title="External reviewers need no account">
          Clients and reviewers outside your organization respond through a
          single-use secure link — no login, no account to manage on their end.
        </WhyCard>
        <WhyCard icon={<IconSpark width={20} height={20} />} title="AI reads the words, statistics do the forecasting">
          Written feedback gets AI-assisted theme and sentiment analysis.
          Win-probability and trend forecasts run on models trained on your own
          history — not a language model guessing at a percentage.
        </WhyCard>
        <WhyCard icon={<IconTag width={20} height={20} />} title="Looks like your organization, not ours">
          Your logo appears in every email and report your organization sends —
          the platform stays in the background.
        </WhyCard>
      </div>
    </Section>
  )
}

const FEEDBACK_KINDS = ['Employee', 'Management', 'Client', 'Product', 'Service', 'Proposal']

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

type Tier = {
  name: string
  price: string
  cadence: string
  description: string
  cta: string
  highlighted?: boolean
  features: string[]
}

const TIERS: Tier[] = [
  {
    name: 'Starter',
    price: '$6',
    cadence: 'per employee / month',
    description: 'Internal 360 reviews for teams getting started.',
    cta: 'Request access',
    features: [
      'Employee & Management review',
      'Cycles & campaigns',
      '100 external responses/month included',
      'PDF exports',
    ],
  },
  {
    name: 'Growth',
    price: '$10',
    cadence: 'per employee / month',
    description: 'The full feedback graph, internal and external.',
    cta: 'Request access',
    highlighted: true,
    features: [
      'All 6 feedback kinds',
      'AI insights & recommendations',
      '1,000 external responses/month included',
      'PDF + Excel exports',
      'Branded emails & reports',
    ],
  },
  {
    name: 'Enterprise',
    price: 'Custom',
    cadence: 'billed annually',
    description: 'Unlimited scale with predictive analytics and audit access.',
    cta: 'Contact sales',
    features: [
      'Everything in Growth',
      'Predictive analytics (win-probability)',
      'Unlimited external responses',
      'Full audit log access',
      'Priority support',
    ],
  },
]

function PricingCard({ tier }: { tier: Tier }) {
  return (
    <div
      className={
        tier.highlighted
          ? 'surface relative border-2 p-7 accent-border'
          : 'surface p-7'
      }
    >
      {tier.highlighted && (
        <span className="accent-bg absolute -top-3 left-7 rounded-full px-3 py-1 text-2xs font-semibold uppercase tracking-[0.08em] text-white">
          Most teams choose this
        </span>
      )}
      <h3 className="text-lg font-semibold text-ink-900 dark:text-ink-50">{tier.name}</h3>
      <p className="mt-1 text-sm text-ink-500 dark:text-ink-400">{tier.description}</p>
      <div className="mt-5 flex items-baseline gap-1.5">
        <span className="text-3xl font-semibold tracking-[-0.02em] text-ink-900 dark:text-white">
          {tier.price}
        </span>
        <span className="text-xs text-ink-500 dark:text-ink-400">{tier.cadence}</span>
      </div>
      <ul className="mt-6 space-y-2.5">
        {tier.features.map((feature) => (
          <li key={feature} className="flex items-start gap-2 text-sm text-ink-600 dark:text-ink-300">
            <IconCheck width={16} height={16} className="mt-0.5 shrink-0 accent-text" />
            {feature}
          </li>
        ))}
      </ul>
      <Link
        to="/register"
        className={tier.highlighted ? 'btn-primary mt-7 w-full py-2.5' : 'btn-secondary mt-7 w-full py-2.5'}
      >
        {tier.cta}
      </Link>
    </div>
  )
}

function Pricing() {
  return (
    <Section id="pricing" className="bg-ink-50 py-20 dark:bg-ink-900/40 lg:py-24">
      <div className="max-w-2xl">
        <h2 className="text-3xl font-semibold tracking-[-0.02em] text-ink-900 dark:text-white">
          Simple pricing, priced for how you actually use it
        </h2>
        <p className="mt-3 text-base text-ink-500 dark:text-ink-400">
          Per employee, with external feedback volume bundled in — your clients
          and proposal reviewers never need a seat.
        </p>
      </div>
      <div className="mt-12 grid gap-6 lg:grid-cols-3">
        {TIERS.map((tier) => (
          <PricingCard key={tier.name} tier={tier} />
        ))}
      </div>
      <p className="mt-6 text-xs text-ink-400 dark:text-ink-500">
        Starting points for discussion — nothing above is billed automatically yet.
      </p>
    </Section>
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
          Sign in if your organization already has a Facet account, or request
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