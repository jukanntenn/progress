import { lazy, Suspense } from 'react'
import { Navigate, createBrowserRouter, RouterProvider } from 'react-router'
import { RootLayout } from '@/routes/RootLayout'
import { SettingsLayout } from '@/routes/SettingsLayout'
import { Spinner } from '@/components/ui/Spinner'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { RequireAuth } from '@/auth/RequireAuth'
import LoginPage from '@/auth/LoginPage'
import SettingsPage from '@/routes/SettingsPage'

const ReportsListPage = lazy(() => import('@/routes/ReportsListPage'))
const ReportDetailPage = lazy(() => import('@/routes/ReportDetailPage'))
const IntegrationsPage = lazy(() => import('@/routes/IntegrationsPage'))
const NotFoundPage = lazy(() => import('@/routes/NotFoundPage'))

// SettingsConfigSection has a named export; wrap it for lazy via a default shim.
const SettingsConfigSection = lazy(async () => {
  const mod = await import('@/routes/SettingsConfigSection')
  return { default: mod.SettingsConfigSection }
})

function RouteFallback() {
  return (
    <div className="flex h-64 items-center justify-center">
      <Spinner className="text-muted-foreground h-6 w-6" />
    </div>
  )
}

const router = createBrowserRouter([
  // Login is a standalone full-screen page (no global Header/footer) — matches
  // Linear/Vercel/GitHub where the auth screen has no app chrome.
  {
    path: '/login',
    element: (
      <ErrorBoundary>
        <LoginPage />
      </ErrorBoundary>
    ),
  },
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
          // Unified Settings area — schema-driven grouped sidebar lives in
          // SettingsLayout; each config section is a child route.
          {
            path: 'settings',
            element: <SettingsLayout />,
            children: [
              { index: true, element: <Navigate to="/settings/config/core" replace /> },
              {
                path: 'config/:section',
                element: (
                  <Suspense fallback={<RouteFallback />}>
                    <SettingsConfigSection />
                  </Suspense>
                ),
              },
              { path: 'account', element: <SettingsPage /> },
              {
                path: 'integrations',
                element: (
                  <Suspense fallback={<RouteFallback />}>
                    <IntegrationsPage />
                  </Suspense>
                ),
              },
            ],
          },
          // Legacy redirects — old entry points now funnel into Settings.
          { path: 'config', element: <Navigate to="/settings/config/core" replace /> },
          { path: 'integrations-old', element: <Navigate to="/settings/integrations" replace /> },
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
