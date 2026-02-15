import { Card, CardContent } from '@/components/ui/card'
import { useReport } from '@/hooks/api'
import ReactMarkdown from 'react-markdown'
import { Link, useParams } from 'react-router-dom'

export default function ReportDetail() {
  const { id } = useParams<{ id: string }>()
  const reportId = id ? parseInt(id, 10) : undefined
  const { data: report, error, isLoading } = useReport(reportId)

  if (isLoading) {
    return (
      <div className="mx-auto my-8 max-w-3xl px-8 py-10">
        <p className="text-gray-600 dark:text-gray-400">Loading...</p>
      </div>
    )
  }

  if (error || !report) {
    return (
      <div className="mx-auto my-8 max-w-3xl px-8 py-10">
        <Card>
          <CardContent>
            <p className="text-red-500">Report not found</p>
            <Link
              to="/"
              className="text-blue-600 hover:underline dark:text-blue-400"
            >
              Back to list
            </Link>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="mx-auto my-8 max-w-3xl px-8 py-10 lg:my-10">
      <Card>
        <CardContent>
          <Link
            to="/"
            className="mb-5 inline-flex items-center text-sm font-medium text-blue-600 transition-colors hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300"
          >
            ← Back to list
          </Link>
          <div className="mb-8 border-b border-gray-200 pb-5 dark:border-gray-700">
            <h1 className="mb-2.5 text-3xl font-bold tracking-tight text-gray-900 dark:text-gray-100 lg:text-2xl">
              {report.title || 'Untitled Report'}
            </h1>
            <div className="text-sm text-gray-600 dark:text-gray-400">
              {report.created_at}
              {report.markpost_url && (
                <a
                  href={report.markpost_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="ml-2.5 rounded border border-gray-300 px-2.5 py-1 text-xs transition-all hover:-translate-y-px hover:bg-gray-50 dark:border-gray-600 dark:hover:bg-gray-700"
                >
                  View External ↗
                </a>
              )}
            </div>
          </div>
          <div className="prose max-w-none text-base leading-relaxed prose-gray dark:prose-invert">
            <ReactMarkdown>{report.content}</ReactMarkdown>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

