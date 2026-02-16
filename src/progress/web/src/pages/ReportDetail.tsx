import { Card, CardContent } from '@/components/ui/card'
import { SkeletonText } from '@/components/ui/skeleton'
import { Header, PageContainer } from '@/components/layout'
import { useReport } from '@/hooks/api'
import { useParams } from 'react-router-dom'
import { ArrowUpRight, Calendar, ExternalLink } from 'lucide-react'

export default function ReportDetail() {
  const { id } = useParams<{ id: string }>()
  const reportId = id ? parseInt(id, 10) : undefined
  const { data: report, error, isLoading } = useReport(reportId)

  if (isLoading) {
    return (
      <>
        <Header />
        <PageContainer size="narrow">
          <Card>
            <CardContent className="py-6">
              <div className="mb-6 h-4 w-20 bg-muted rounded animate-pulse" />
              <div className="mb-8 border-b border-border/30 pb-6">
                <div className="h-8 w-3/4 bg-muted rounded animate-pulse mb-3" />
                <div className="h-4 w-1/3 bg-muted rounded animate-pulse" />
              </div>
              <SkeletonText lines={8} />
            </CardContent>
          </Card>
        </PageContainer>
      </>
    )
  }

  if (error || !report) {
    return (
      <>
        <Header />
        <PageContainer size="narrow">
          <Card>
            <CardContent className="py-12 text-center">
              <div className="text-error mb-4 text-lg font-medium">Report not found</div>
              <p className="text-muted-foreground mb-6">The requested report could not be loaded.</p>
            </CardContent>
          </Card>
        </PageContainer>
      </>
    )
  }

  return (
    <>
      <Header />
      <PageContainer size="narrow">
        <Card>
          <CardContent className="py-6">
            <header className="mb-8 border-b border-border/30 pb-6">
              <h1 className="text-2xl font-bold tracking-tight text-foreground lg:text-3xl mb-3">
                {report.title || 'Untitled Report'}
              </h1>

              <div className="flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
                <div className="inline-flex items-center gap-1.5">
                  <Calendar className="h-4 w-4" />
                  <time>{report.created_at}</time>
                </div>

                {report.markpost_url && (
                  <a
                    href={report.markpost_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border/50 bg-muted/30 hover:bg-accent/50 hover:border-border transition-colors duration-150 text-foreground"
                  >
                    <ExternalLink className="h-3.5 w-3.5" />
                    <span>View External</span>
                    <ArrowUpRight className="h-3 w-3 text-muted-foreground" />
                  </a>
                )}
              </div>
            </header>

            <article
              className="prose max-w-none text-base leading-relaxed prose-gray dark:prose-invert"
              dangerouslySetInnerHTML={{ __html: report.content }}
            />
          </CardContent>
        </Card>
      </PageContainer>
    </>
  )
}
