import { withTranslation } from 'react-i18next'
import { AlertTriangle, RefreshCw, Home } from 'lucide-react'
import { Link } from 'react-router'
import { Button } from '@/components/ui/Button'
import { Card, CardContent } from '@/components/ui/Card'

function ErrorFallbackImpl({ error, t }: { error?: Error; t: (key: string) => string }) {
  return (
    <div className="flex min-h-[60vh] items-center justify-center p-4">
      <Card className="glass-card max-w-md">
        <CardContent className="py-10 text-center">
          <AlertTriangle className="text-destructive mx-auto mb-4 h-12 w-12" />
          <h2 className="text-foreground mb-2 text-xl font-semibold">
            {t('errors.boundaryTitle')}
          </h2>
          <p className="text-muted-foreground mb-2 text-sm">{t('errors.boundaryDescription')}</p>
          {error?.message ? (
            <p className="text-muted-foreground truncate text-xs">{error.message}</p>
          ) : null}
          <div className="mt-6 flex justify-center gap-3">
            <Button variant="outline" onClick={() => window.location.reload()}>
              <RefreshCw className="h-4 w-4" />
              {t('common.refresh')}
            </Button>
            <Link to="/reports">
              <Button variant="ghost">
                <Home className="h-4 w-4" />
                {t('common.backHome')}
              </Button>
            </Link>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

const ErrorFallback = withTranslation()(ErrorFallbackImpl)

export { ErrorFallback }
