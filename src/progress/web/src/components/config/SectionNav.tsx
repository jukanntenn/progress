import { cn } from '@/lib/utils'

interface Section {
  id: string
  title: string
}

interface SectionNavProps {
  sections: Section[]
  activeSection: string | null
  onSectionClick: (sectionId: string) => void
}

export function SectionNav({
  sections,
  activeSection,
  onSectionClick,
}: SectionNavProps) {
  return (
    <nav className="space-y-1">
      {sections.map((section) => (
        <button
          key={section.id}
          type="button"
          onClick={() => onSectionClick(section.id)}
          className={cn(
            'w-full rounded-lg px-3 py-2 text-left text-sm font-medium',
            'transition-all duration-150',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
            activeSection === section.id
              ? 'bg-primary/10 text-primary'
              : 'text-muted-foreground hover:bg-accent hover:text-foreground'
          )}
        >
          {section.title}
        </button>
      ))}
    </nav>
  )
}
