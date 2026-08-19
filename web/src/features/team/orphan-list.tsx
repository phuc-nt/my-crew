// Recovery list: profiles sitting on disk that fell out of the registry. Without this the
// only way back is hand-editing registry.yaml, so it stays on the team page even though
// it is empty on a healthy install.
import { useRegisterProfile, useUnregisteredProfiles } from '../../api/queries/use-team-queries'
import { Button } from '../../components/ui/button'
import { useLanguage } from '../../i18n/language-context'

export function OrphanList({ onError }: { onError: (message: string) => void }) {
  const { t } = useLanguage()
  const { data } = useUnregisteredProfiles()
  const register = useRegisterProfile()
  const orphans = data?.profiles ?? []
  if (orphans.length === 0) return null

  return (
    <section className="team-orphans">
      <h3>{t('team.orphansTitle', { n: orphans.length })}</h3>
      <p className="muted">{t('team.orphansHint')}</p>
      <ul>
        {orphans.map((o) => (
          <li key={o.id}>
            <strong>{o.id}</strong> {o.name !== o.id && `(${o.name})`}{' '}
            {o.domain && <span className="muted">— {o.domain}</span>}{' '}
            {o.valid ? (
              <Button
                variant="ghost"
                disabled={register.isPending && register.variables === o.id}
                onClick={() =>
                  register
                    .mutateAsync(o.id)
                    .catch((e: unknown) =>
                      onError(e instanceof Error ? e.message : t('team.addOrphanFailed')))
                }
              >
                {register.isPending && register.variables === o.id
                  ? t('team.orphanAdding')
                  : t('team.orphanAdd')}
              </Button>
            ) : (
              <span className="error">{t('team.orphanError', { error: o.error ?? '' })}</span>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}
