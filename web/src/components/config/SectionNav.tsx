import { cn } from '@/lib/utils'

export interface NavSection {
  id: string
  title: string
}

export function SectionNav({
  sections,
  activeSection,
  onSectionClick,
}: {
  sections: NavSection[]
  activeSection: string | null
  onSectionClick: (id: string) => void
}) {
  return (
    <nav className="space-y-1">
      {sections.map((section) => (
        <button
          key={section.id}
          type="button"
          onClick={() => onSectionClick(section.id)}
          className={cn(
            'w-full rounded-lg px-3 py-2 text-left text-sm font-medium transition-all duration-150',
            'focus-visible:ring-ring/50 focus-visible:ring-2 focus-visible:outline-none',
            activeSection === section.id
              ? 'bg-primary/10 text-primary'
              : 'text-muted-foreground hover:bg-accent hover:text-foreground',
          )}
        >
          {section.title}
        </button>
      ))}
    </nav>
  )
}
