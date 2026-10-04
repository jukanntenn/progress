import { useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { useTranslation } from 'react-i18next'
import { ChevronLeft, ChevronRight, ArrowUpRight, FileText } from 'lucide-react'
import { PageContainer } from '@/components/PageContainer'
import { Card, CardContent } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { ReportListItemSkeleton } from '@/components/ui/Skeleton'
import { formatDateTime } from '@/lib/format'
import { $api } from '@/api/client'

export default function ReportsListPage() {
  const { t } = useTranslation()
  const [searchParams, setSearchParams] = useSearchParams()
  const page = Math.max(1, parseInt(searchParams.get('page') ?? '1', 10) || 1)
  const [pageSize] = useState(20)

  const { data, error, isPending } = $api.useQuery('get', '/api/v1/reports', {
    params: { query: { page, page_size: pageSize } },
  })

  const handlePageChange = (newPage: number) => {
    const next = new URLSearchParams(searchParams)
    next.set('page', String(newPage))
    setSearchParams(next)
  }

  if (isPending) {
    return (
      <PageContainer size="wide">
        <Card>
          <CardContent>
            {Array.from({ length: 5 }).map((_, i) => (
              <ReportListItemSkeleton key={i} />
            ))}
          </CardContent>
        </Card>
      </PageContainer>
    )
  }

  if (error) {
    return (
      <PageContainer size="wide">
        <Card>
          <CardContent className="py-12 text-center">
            <div className="text-destructive mb-4 text-lg font-medium">
              {t('reports.loadFailed')}
            </div>
            <p className="text-muted-foreground mb-6">{t('reports.loadFailedDescription')}</p>
            <Button variant="outline" onClick={() => window.location.reload()}>
              {t('reports.tryAgain')}
            </Button>
          </CardContent>
        </Card>
      </PageContainer>
    )
  }

  const items = data?.items ?? []
  const total = data?.total ?? 0
  const hasNext = data?.has_next ?? false

  return (
    <PageContainer size="wide">
      <Card>
        <CardContent>
          {items.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <FileText className="text-muted-foreground/50 mb-4 h-16 w-16" />
              <h3 className="text-foreground mb-2 text-lg font-medium">
                {t('reports.emptyTitle')}
              </h3>
              <p className="text-muted-foreground max-w-sm text-sm">
                {t('reports.emptyDescription')}
              </p>
            </div>
          ) : (
            <ul className="divide-border/30 divide-y">
              {items.map((report, idx) => (
                <li
                  key={report.id}
                  className="group animate-fade-in py-4 first:pt-0 last:pb-0"
                  style={{ animationDelay: `${idx * 30}ms` }}
                >
                  <Link
                    to={`/reports/${report.id}`}
                    className="hover:bg-accent/50 focus-visible:ring-ring/50 -mx-3 -my-2 block rounded-lg px-3 py-2 transition-all duration-150 focus-visible:ring-2 focus-visible:outline-none"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <h2 className="text-foreground group-hover:text-muted-foreground truncate text-base font-semibold transition-colors duration-150">
                          {report.title || t('reports.untitled')}
                        </h2>
                        <div className="text-muted-foreground mt-1 flex flex-wrap items-center gap-2 text-sm">
                          <time>{formatDateTime(report.created_at)}</time>
                          <span className="border-border/50 bg-muted/30 rounded border px-2 py-0.5 text-xs">
                            {report.report_type}
                          </span>
                          {report.markpost_url && (
                            <span className="border-border/50 bg-muted/30 inline-flex items-center gap-1 rounded border px-2 py-0.5 text-xs transition-colors duration-150">
                              <span>{t('reports.external')}</span>
                              <ArrowUpRight className="h-3 w-3" />
                            </span>
                          )}
                        </div>
                      </div>
                      <ChevronRight className="text-muted-foreground/50 group-hover:text-foreground h-5 w-5 flex-shrink-0 transition-all duration-200 group-hover:translate-x-0.5" />
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          )}

          {total > pageSize && (
            <div className="border-border/30 mt-6 flex items-center justify-between border-t pt-6">
              <Button
                variant="outline"
                size="sm"
                disabled={page <= 1}
                onClick={() => handlePageChange(page - 1)}
              >
                <ChevronLeft className="h-4 w-4" />
                {t('reports.previous')}
              </Button>

              <div className="text-muted-foreground flex items-center gap-2 text-sm">
                <span className="text-foreground font-medium tabular-nums">{page}</span>
                <span>/</span>
                <span className="tabular-nums">{Math.ceil(total / pageSize)}</span>
              </div>

              <Button
                variant="outline"
                size="sm"
                disabled={!hasNext}
                onClick={() => handlePageChange(page + 1)}
              >
                {t('reports.next')}
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </PageContainer>
  )
}
