import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { SkeletonList } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { Header, PageContainer } from '@/components/layout'
import { useReports } from '@/hooks/api'
import { Link, useSearchParams } from 'react-router-dom'
import { ChevronLeft, ChevronRight, ArrowUpRight } from 'lucide-react'

export default function ReportList() {
  const [searchParams, setSearchParams] = useSearchParams()
  const page = parseInt(searchParams.get('page') || '1', 10)
  const { data, error, isLoading } = useReports(page)

  if (isLoading) {
    return (
      <>
        <Header />
        <PageContainer size="narrow">
          <Card>
            <CardHeader>
              <div className="h-8 w-40 bg-muted rounded animate-pulse" />
              <div className="h-4 w-24 bg-muted rounded animate-pulse mt-2" />
            </CardHeader>
            <CardContent>
              <SkeletonList items={5} />
            </CardContent>
          </Card>
        </PageContainer>
      </>
    )
  }

  if (error) {
    return (
      <>
        <Header />
        <PageContainer size="narrow">
          <Card>
            <CardContent className="py-12 text-center">
              <div className="text-error mb-4 text-lg font-medium">Failed to load reports</div>
              <p className="text-muted-foreground mb-6">Something went wrong while fetching the reports.</p>
              <Button variant="outline" onClick={() => window.location.reload()}>
                Try Again
              </Button>
            </CardContent>
          </Card>
        </PageContainer>
      </>
    )
  }

  const handlePageChange = (newPage: number) => {
    setSearchParams({ page: newPage.toString() })
  }

  return (
    <>
      <Header />
      <PageContainer size="narrow">
        <Card>
          <CardContent>
            <ul className="divide-y divide-border/30">
              {data?.reports.map((report, idx) => (
                <li
                  key={report.id}
                  className="group py-4 first:pt-0 last:pb-0"
                  style={{
                    animationDelay: `${idx * 30}ms`,
                  }}
                >
                  <Link
                    to={`/report/${report.id}`}
                    className={`
                      block
                      -mx-3 px-3 py-2 -my-2 rounded-lg
                      transition-colors duration-150
                      hover:bg-accent/50
                      focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50
                    `}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex-1 min-w-0">
                        <h2 className="text-base font-semibold text-foreground group-hover:text-gray-600 transition-colors duration-150 truncate">
                          {report.title || 'Untitled Report'}
                        </h2>
                        <div className="mt-1 flex items-center gap-2 text-sm text-muted-foreground">
                          <time>{report.created_at}</time>
                          {report.markpost_url && (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded border border-border/50 bg-muted/30 transition-colors duration-150">
                              <span>External</span>
                              <ArrowUpRight className="h-3 w-3" />
                            </span>
                          )}
                        </div>
                      </div>
                      <ChevronRight className="h-5 w-5 text-muted-foreground/50 group-hover:text-foreground group-hover:translate-x-0.5 transition-all duration-200 flex-shrink-0" />
                    </div>
                  </Link>
                </li>
              ))}
            </ul>

            {(!data?.reports || data.reports.length === 0) && (
              <div className="py-12 text-center text-muted-foreground">
                No reports found.
              </div>
            )}

            {/* Pagination */}
            {(data?.total_pages || 0) > 1 && (
              <div className="mt-6 pt-6 border-t border-border/30 flex items-center justify-between">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!data?.has_prev}
                  onClick={() => handlePageChange(page - 1)}
                  leftIcon={<ChevronLeft className="h-4 w-4" />}
                >
                  Previous
                </Button>

                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <span className="tabular-nums font-medium text-foreground">{data?.page || 1}</span>
                  <span>/</span>
                  <span className="tabular-nums">{data?.total_pages || 1}</span>
                </div>

                <Button
                  variant="outline"
                  size="sm"
                  disabled={!data?.has_next}
                  onClick={() => handlePageChange(page + 1)}
                  rightIcon={<ChevronRight className="h-4 w-4" />}
                >
                  Next
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      </PageContainer>
    </>
  )
}
