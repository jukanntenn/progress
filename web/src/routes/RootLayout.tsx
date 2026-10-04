import { Outlet } from 'react-router'
import { useTranslation } from 'react-i18next'
import { Header } from '@/components/Header'

export function RootLayout() {
  const { t } = useTranslation()
  return (
    <div className="flex min-h-screen flex-col">
      <Header />
      <div className="flex-1">
        <Outlet />
      </div>
      <footer className="text-muted-foreground mx-auto w-full max-w-6xl px-4 py-6 text-center text-xs">
        <a
          href="https://github.com/jukanntenn/progress"
          target="_blank"
          rel="noopener noreferrer"
          className="hover:text-foreground transition-colors"
        >
          {t('app.title')}
        </a>
      </footer>
    </div>
  )
}
