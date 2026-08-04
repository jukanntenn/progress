import { lazy, Suspense } from 'react'
import { Navigate, createBrowserRouter, RouterProvider } from 'react-router'
import { RootLayout } from '@/routes/RootLayout'
import { Spinner } from '@/components/ui/Spinner'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { RequireAuth } from '@/auth/RequireAuth'
import LoginPage from '@/auth/LoginPage'
import SettingsPage from '@/routes/SettingsPage'

const ReportsListPage = lazy(() => import('@/routes/ReportsListPage'))
const ReportDetailPage = lazy(() => import('@/routes/ReportDetailPage'))
const IntegrationsPage = lazy(() => import('@/routes/IntegrationsPage'))
const ConfigPage = lazy(() => import('@/routes/ConfigPage'))
const NotFoundPage = lazy(() => import('@/routes/NotFoundPage'))

function RouteFallback() {
  return (
    <div className="flex h-64 items-center justify-center">
      <Spinner className="text-muted-foreground h-6 w-6" />
    </div>
  )
}

const router = createBrowserRouter([
  {
    path: '/',
    element: (
      <ErrorBoundary>
        <RootLayout />
      </ErrorBoundary>
    ),
    children: [
      { index: true, element: <Navigate to="/reports" replace /> },
      {
        path: 'login',
        element: <LoginPage />,
      },
      {
        element: <RequireAuth />,
        children: [
          {
            path: 'reports',
            element: (
              <Suspense fallback={<RouteFallback />}>
                <ReportsListPage />
              </Suspense>
            ),
          },
          {
            path: 'reports/:id',
            element: (
              <Suspense fallback={<RouteFallback />}>
                <ReportDetailPage />
              </Suspense>
            ),
          },
          {
            path: 'integrations',
            element: (
              <Suspense fallback={<RouteFallback />}>
                <IntegrationsPage />
              </Suspense>
            ),
          },
          {
            path: 'config',
            element: (
              <Suspense fallback={<RouteFallback />}>
                <ConfigPage />
              </Suspense>
            ),
          },
          {
            path: 'settings',
            element: <SettingsPage />,
          },
        ],
      },
      {
        path: '*',
        element: (
          <Suspense fallback={<RouteFallback />}>
            <NotFoundPage />
          </Suspense>
        ),
      },
    ],
  },
])

export default function App() {
  return <RouterProvider router={router} />
}
