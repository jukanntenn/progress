import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { useReports } from '@/hooks/api'
import { Link, useSearchParams } from 'react-router-dom'

export default function ReportList() {
  const [searchParams, setSearchParams] = useSearchParams()
  const page = parseInt(searchParams.get('page') || '1', 10)
  const { data, error, isLoading } = useReports(page)

  if (isLoading) {
    return (
      <div className="mx-auto my-8 max-w-2xl px-8 py-10">
        <p className="text-gray-600 dark:text-gray-400">Loading...</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="mx-auto my-8 max-w-2xl px-8 py-10">
        <p className="text-red-500">Failed to load reports</p>
      </div>
    )
  }

  const handlePageChange = (newPage: number) => {
    setSearchParams({ page: newPage.toString() })
  }

  return (
    <div className="mx-auto my-8 max-w-2xl px-8 py-10 lg:my-10">
      <Card>
        <CardHeader>
          <h1 className="text-3xl font-bold tracking-tight text-gray-900 dark:text-gray-100 lg:text-2xl">
            Progress Reports
          </h1>
          <p className="text-sm text-gray-600 dark:text-gray-400">
            {data?.total || 0} reports total
          </p>
        </CardHeader>
        <CardContent>
          <div className="mb-8">
            <Link to="/config">
              <Button variant="outline" className="mb-7 mr-2.5">
                Configuration
              </Button>
            </Link>
            <a href="/api/v1/rss">
              <Button variant="outline">RSS Feed</Button>
            </a>
          </div>

          <ul className="list-none">
            {data?.reports.map((report) => (
              <li
                key={report.id}
                className="border-b border-gray-200 py-5 last:border-b-0 dark:border-gray-700"
              >
                <Link
                  to={`/report/${report.id}`}
                  className="mb-1.5 block text-lg font-semibold text-blue-600 transition-colors hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300 lg:text-base"
                >
                  {report.title || 'Untitled Report'}
                </Link>
                <div className="text-sm text-gray-600 dark:text-gray-400">
                  {report.created_at}
                  {report.markpost_url && (
                    <a
                      href={report.markpost_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="ml-2 rounded border border-gray-300 px-2 py-0.5 text-xs transition-all hover:-translate-y-px hover:bg-gray-50 dark:border-gray-600 dark:hover:bg-gray-700"
                    >
                      View External ↗
                    </a>
                  )}
                </div>
              </li>
            ))}
          </ul>

          <div className="mt-8 flex items-center justify-center gap-5 border-t border-gray-200 pt-5 dark:border-gray-700">
            <Button
              variant="outline"
              disabled={!data?.has_prev}
              onClick={() => handlePageChange(page - 1)}
              className={!data?.has_prev ? 'pointer-events-none opacity-60' : ''}
            >
              Previous
            </Button>

            <span className="text-sm text-gray-600 dark:text-gray-400">
              Page {data?.page || 1} of {data?.total_pages || 1}
            </span>

            <Button
              variant="outline"
              disabled={!data?.has_next}
              onClick={() => handlePageChange(page + 1)}
              className={!data?.has_next ? 'pointer-events-none opacity-60' : ''}
            >
              Next
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

