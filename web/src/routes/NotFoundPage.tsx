import { Link } from 'react-router'
import { useTranslation } from 'react-i18next'
import { PageContainer } from '@/components/PageContainer'
import { Card, CardContent } from '@/components/ui/Card'
import { buttonVariants } from '@/components/ui/button-variants'
import { cn } from '@/lib/utils'

export default function NotFoundPage() {
  const { t } = useTranslation()

  return (
    <PageContainer>
      <Card>
        <CardContent className="py-16 text-center">
          <div className="mb-4 text-3xl font-bold">{t('common.notFound')}</div>
          <p className="text-muted-foreground mb-8">{t('common.notFoundDescription')}</p>
          <Link to="/reports" className={cn(buttonVariants({ variant: 'default' }))}>
            {t('common.goHome')}
          </Link>
        </CardContent>
      </Card>
    </PageContainer>
  )
}
