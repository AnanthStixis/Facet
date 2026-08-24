import logoUrl from '../assets/logo_1.png'

export function BrandLogo({ height = 28, className }: { height?: number; className?: string }) {
  return (
    <img
      src={logoUrl}
      alt="Facet360"
      style={{ height, width: 'auto' }}
      className={className}
    />
  )
}

/**
 * The Facet mark: three planes of a cut gem meeting at a point.
 *
 * It reads as a single object made of distinct faces, which is the product
 * thesis in one glyph - every relationship has more than one side, and the
 * platform shows all of them at once.
 */
export function FacetMark({ size = 26 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden="true">
      <path d="M16 2.5 29 10v12L16 29.5 3 22V10L16 2.5Z" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" opacity="0.32" />
      <path d="M16 2.5 29 10 16 17.5 3 10 16 2.5Z" fill="currentColor" opacity="0.95" />
      <path d="M16 17.5 29 10v12L16 29.5V17.5Z" fill="currentColor" opacity="0.55" />
      <path d="M16 17.5 3 10v12l13 7.5V17.5Z" fill="currentColor" opacity="0.28" />
    </svg>
  )
}

export function Wordmark({ name, size = 26 }: { name: string; size?: number }) {
  return (
    <span className="flex items-center gap-2.5">
      <span className="accent-text">
        <FacetMark size={size} />
      </span>
      <span className="text-lg font-semibold tracking-[-0.02em] text-ink-900 dark:text-white">
        {name}
      </span>
    </span>
  )
}