import { useTheme } from '../context/ThemeContext.jsx';

const roleOptions = ['Cliente', 'Ejecutivo'];

export default function Header({
  appMode,
  onReturnHome,
  branches,
  selectedBranch,
  onSelectBranch,
  selectedRole,
  onSelectRole,
  chatTextSize,
  onSelectChatTextSize,
  preferenceNotice,
}) {
  const { theme, toggleTheme } = useTheme();
  const nextThemeLabel = theme === 'dark' ? 'Cambiar a modo claro' : 'Cambiar a tema oscuro';
  const brandTagline = appMode === 'warehouse'
    ? 'Río, asistente de almacén'
    : appMode === 'home'
      ? 'Río, asistencia para cada equipo'
      : 'Río, asistente virtual de devoluciones';

  return (
    <header className="site-header">
      <a className="brand" href="/" aria-label="Distribuidora Río Claro, inicio">
        <img className="brand-logo" src="/rio-bravo-logo.jpg" alt="" />
        <span className="brand-lockup">
          <span className="brand-name">Distribuidora Río Claro</span>
          <span className="brand-tagline">
            {brandTagline}
            <span className="brand-online"><span aria-hidden="true" />En línea</span>
          </span>
        </span>
      </a>

      <div className="header-tools" aria-label={appMode === 'customer'
        ? 'Configuración de sucursal, rol y tema'
        : 'Configuración de tema y texto'}>
        {appMode === 'customer' && (
          <>
            <label className="branch-picker" htmlFor="branch-select">
              <span className="branch-picker-label">Sucursal</span>
              <select
                id="branch-select"
                value={selectedBranch.id}
                onChange={(event) => {
                  const nextBranch = branches.find((branch) => branch.id === event.target.value);
                  if (nextBranch) onSelectBranch(nextBranch);
                }}
              >
                {branches.map((branch) => (
                  <option key={branch.id} value={branch.id}>{branch.name}</option>
                ))}
              </select>
            </label>

            <div className="role-picker" aria-label="Selecciona un rol">
              {roleOptions.map((role) => (
                <button
                  key={role}
                  type="button"
                  className={`role-option ${selectedRole === role ? 'is-selected' : ''}`}
                  onClick={() => onSelectRole(role)}
                  aria-pressed={selectedRole === role}
                >
                  {role}
                </button>
              ))}
            </div>
          </>
        )}

        {appMode !== 'home' && (
          <div className="assistant-switch-anchor">
            <button className="back-to-home-button" type="button" onClick={onReturnHome}>
              Cambiar asistente
            </button>
            {appMode === 'customer' && selectedRole === 'Cliente' && (
              <aside className="customer-demo-note" aria-label="Datos de cliente para la demostración">
                <p>Para efectos de demo use estos datos de cliente:</p>
                <p>Producto 1: <strong>SKU-1001.</strong> Factura: <strong>TK-4821.</strong></p>
                <p>Producto 2: <strong>SKU-1033.</strong> Factura: <strong>TK-7394.</strong></p>
              </aside>
            )}
          </div>
        )}

        <label className="text-size-picker" htmlFor="chat-text-size">
          <span>Tamaño del texto</span>
          <select
            id="chat-text-size"
            value={chatTextSize}
            onChange={(event) => onSelectChatTextSize(event.target.value)}
          >
            <option value="small">Pequeño</option>
            <option value="normal">Normal</option>
            <option value="large">Grande</option>
          </select>
        </label>

        <button
          className="theme-toggle"
          type="button"
          onClick={toggleTheme}
          aria-label={nextThemeLabel}
          title={nextThemeLabel}
        >
          <span aria-hidden="true">{theme === 'dark' ? 'Claro' : 'Oscuro'}</span>
          <span className="theme-toggle-indicator" aria-hidden="true" />
        </button>
        {preferenceNotice && <p className="preference-notice" role="status">{preferenceNotice}</p>}
      </div>
    </header>
  );
}