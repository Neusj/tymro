import { Link } from 'react-router-dom'
import Avatar from './Avatar'

export default function OrganizationCard({ organization, showManageLink = true }) {
  return (
    <article className="card-surface p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <Avatar src={organization.logo} name={organization.name} size="md" />
          <div>
            <h3 className="text-base font-semibold">{organization.name}</h3>
            <p className="text-sm text-brand-muted">
              {organization.city || 'Sin ciudad'} · {organization.country || 'Sin país'}
            </p>
          </div>
        </div>
        <span className="rounded-full border border-brand-line px-2 py-1 text-xs text-brand-muted">
          {organization.branches_count || 0} suc.
        </span>
      </div>

      <div className="mt-4 flex items-center justify-between text-xs">
        <span className="text-brand-muted">
          Primario: <span className="font-semibold text-brand-white">{organization.primary_color || '-'}</span>
        </span>
        {showManageLink ? (
          <Link to={`/superadmin/organizations/${organization.id}`} className="rounded-lg border border-brand-line px-2 py-1 text-brand-white hover:border-brand-orange">
            Ver detalle
          </Link>
        ) : null}
      </div>
    </article>
  )
}
