export default function AppLayout({ children }) {
  return (
    <div className="min-h-screen bg-brand-black text-brand-white">
      <header className="pt-safe-top sticky top-0 z-20 border-b border-brand-line bg-brand-black/85 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-4 md:px-6">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.3em] text-brand-orange">TYMRO</p>
            <h1 className="mt-1 text-xl font-bold">Gestión de gimnasios</h1>
          </div>
          <div className="hidden gap-2 md:flex">
            <span className="badge-accent">Mobile first</span>
            <span className="badge-accent">Multi-sucursal</span>
            <span className="badge-accent">Pagos a profesores</span>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-6 md:px-6 md:py-8">{children}</main>
    </div>
  )
}
