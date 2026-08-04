import { useTranslation } from 'react-i18next'
import { PageContainer } from '@/components/PageContainer'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/Card'
import { Skeleton } from '@/components/ui/Skeleton'
import { $api } from '@/api/client'

export default function IntegrationsPage() {
  const { t } = useTranslation()

  const { data, error, isPending } = $api.useQuery('get', '/api/v1/integrations')

  return (
    <PageContainer>
      <h1 className="mb-2 text-2xl font-bold">{t('integrations.title')}</h1>
      <p className="text-muted-foreground mb-6 text-sm">{t('integrations.description')}</p>

      {isPending ? (
        <div className="space-y-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-24 w-full" />
          ))}
        </div>
      ) : error ? (
        <Card>
          <CardContent className="text-destructive py-12 text-center">
            {t('common.error')}
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {data?.map((integration) => (
            <Card key={integration.name}>
              <CardHeader>
                <CardTitle className="font-mono">{integration.name}</CardTitle>
                <CardDescription>{t('integrations.configSchema')}</CardDescription>
              </CardHeader>
              <CardContent>
                <pre className="bg-muted max-h-96 overflow-auto rounded-md p-4 text-xs">
                  {JSON.stringify(integration.config_schema, null, 2)}
                </pre>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </PageContainer>
  )
}
