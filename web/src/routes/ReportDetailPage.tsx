import { useMemo } from 'react'
import { Link, useParams } from 'react-router'
import { useTranslation } from 'react-i18next'
import { ArrowLeft, ExternalLink, ArrowUpRight, Calendar } from 'lucide-react'
import GithubSlugger from 'github-slugger'
import { PageContainer } from '@/components/PageContainer'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card'
import { buttonVariants } from '@/components/ui/button-variants'
import { ReportDetailSkeleton } from '@/components/ui/Skeleton'
import { MarkdownRenderer } from '@/components/MarkdownRenderer'
import { Toc, type TocItem } from '@/components/Toc'
import { $api } from '@/api/client'
import { formatDateTime } from '@/lib/format'
import { cn } from '@/lib/utils'

const HEADING_RE = /^(#{2,3})\s+(.+?)\s*$/
const FENCE_RE = /^\s{0,3}(`{3,}|~{3,})/

export default function ReportDetailPage() {
  const { t } = useTranslation()
  const { id } = useParams<{ id: string }>()
  const reportId = Number(id)

  const { data, error, isPending } = $api.useQuery('get', '/api/v1/reports/{report_id}', {
    params: { path: { report_id: isNaN(reportId) ? 0 : reportId } },
  })

  // Extract h2/h3 headings for the right-side TOC. github-slugger generates the
  // same ids as rehype-slug (which runs inside MarkdownRenderer), so TOC anchors
  // match the rendered headings. Fenced code blocks are skipped so a ``#`` line
  // inside a code block is never mistaken for a heading.
  const tocItems = useMemo<TocItem[]>(() => {
    if (!data?.content) return []
    const slugger = new GithubSlugger()
    const items: TocItem[] = []
    let inFence = false
    for (const line of data.content.split('\n')) {
      if (FENCE_RE.test(line)) {
        inFence = !inFence
        continue
      }
      if (inFence) continue
      const m = HEADING_RE.exec(line)
      if (m) {
        const [prefix, text] = m.slice(1) as [string, string]
        items.push({ id: slugger.slug(text), text, level: prefix.length })
      }
    }
    return items
  }, [data?.content])

  if (isPending) {
    return (
      <PageContainer size="wide">
        <ReportDetailSkeleton />
      </PageContainer>
    )
  }

  if (error || !data) {
    return (
      <PageContainer size="wide">
        <Card>
          <CardContent className="py-12 text-center">
            <div className="text-destructive mb-4 text-lg font-medium">{t('reports.notFound')}</div>
            <p className="text-muted-foreground mb-6">{t('reports.notFoundDescription')}</p>
            <Link to="/reports" className={cn(buttonVariants({ variant: 'outline' }))}>
              {t('reports.backToList')}
            </Link>
          </CardContent>
        </Card>
      </PageContainer>
    )
  }

  return (
    <PageContainer size="wide">
      <div className="mb-4 flex items-center justify-between gap-3">
        <Link to="/reports" className={cn(buttonVariants({ variant: 'ghost', size: 'sm' }))}>
          <ArrowLeft className="h-4 w-4" />
          {t('reports.backToList')}
        </Link>
        <div className="flex items-center gap-2">
          {data.markpost_url && (
            <a
              href={data.markpost_url}
              target="_blank"
              rel="noopener noreferrer"
              className={cn(buttonVariants({ variant: 'outline', size: 'sm' }))}
            >
              <ExternalLink className="h-4 w-4" />
              {t('reports.viewExternal')}
            </a>
          )}
        </div>
      </div>

      <div className="flex gap-8">
        <div className="min-w-0 flex-1">
          <Card>
            <CardHeader>
              <CardTitle className="text-foreground text-2xl font-bold tracking-tight">
                {data.title || t('reports.untitled')}
              </CardTitle>
              <div className="text-muted-foreground mt-2 flex flex-wrap items-center gap-3 text-sm">
                <span className="inline-flex items-center gap-1.5">
                  <Calendar className="h-4 w-4" />
                  <time>{formatDateTime(data.created_at)}</time>
                </span>
                <span className="border-border/50 bg-muted/30 rounded border px-2 py-0.5 text-xs">
                  {data.report_type}
                </span>
                {data.commit_hash && (
                  <code className="border-border/50 bg-muted/30 rounded border px-1.5 py-0.5 text-xs">
                    {data.commit_hash.slice(0, 8)}
                  </code>
                )}
                {data.markpost_url && (
                  <a
                    href={data.markpost_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="border-border/50 bg-muted/30 hover:bg-accent/50 inline-flex items-center gap-1 rounded border px-2 py-0.5 text-xs transition-colors"
                  >
                    {t('reports.external')}
                    <ArrowUpRight className="h-3 w-3" />
                  </a>
                )}
              </div>
            </CardHeader>
            <CardContent>
              <MarkdownRenderer content={data.content} />
            </CardContent>
          </Card>
        </div>
        {tocItems.length > 0 && (
          <aside className="hidden w-56 flex-shrink-0 lg:block">
            <div className="sticky top-24">
              <Toc items={tocItems} />
            </div>
          </aside>
        )}
      </div>
    </PageContainer>
  )
}
