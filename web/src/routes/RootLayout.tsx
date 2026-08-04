import { Outlet } from 'react-router'
import { Header } from '@/components/Header'

export function RootLayout() {
  return (
    <div className="flex min-h-screen flex-col">
      <Header />
      <div className="flex-1">
        <Outlet />
      </div>
      <footer className="text-muted-foreground mx-auto w-full max-w-3xl px-4 py-6 text-center text-xs">
        <a
          href="https://github.com/jukanntenn/progress"
          target="_blank"
          rel="noopener noreferrer"
          className="hover:text-foreground transition-colors"
        >
          Progress
        </a>
      </footer>
    </div>
  )
}
