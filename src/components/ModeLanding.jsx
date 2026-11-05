export default function ModeLanding({ onSelectMode }) {
  return (
    <section className="mode-landing" aria-labelledby="mode-landing-title">
      <p className="mode-landing-eyebrow">ASISTENCIA RÍO CLARO</p>
      <h1 id="mode-landing-title">¿Cómo podemos ayudarte?</h1>
      <p className="mode-landing-intro">Elige el espacio que necesitas para continuar.</p>
      <div className="mode-card-grid">
        <button
          className="mode-card customer-mode-card"
          type="button"
          onClick={() => onSelectMode('customer')}
        >
          <span className="mode-card-icon" aria-hidden="true">
            <svg viewBox="0 0 32 32">
              <path d="M5 8.5A3.5 3.5 0 0 1 8.5 5h15A3.5 3.5 0 0 1 27 8.5v10a3.5 3.5 0 0 1-3.5 3.5H14l-7 5v-5.8a3.5 3.5 0 0 1-2-3.2z" />
              <path d="M11 12h10M11 16h7" />
            </svg>
          </span>
          <span className="mode-card-title">Clientes</span>
          <span className="mode-card-description">
            Consulta la política de devoluciones y encuentra orientación para tu compra.
          </span>
          <span className="mode-card-action">Abrir chat de devoluciones</span>
        </button>
        <button
          className="mode-card warehouse-mode-card"
          type="button"
          onClick={() => onSelectMode('warehouse')}
        >
          <span className="mode-card-icon" aria-hidden="true">
            <svg viewBox="0 0 32 32">
              <path d="m4 10 12-6 12 6v14l-12 5-12-5z" />
              <path d="m4 10 12 6 12-6M16 16v13M10 7l12 6" />
            </svg>
          </span>
          <span className="mode-card-title">Colaboradores</span>
          <span className="mode-card-description">
            Consulta por voz o texto la existencia disponible de productos y SKU.
          </span>
          <span className="mode-card-action">Abrir chat de almacén</span>
        </button>
      </div>
      <p className="mode-landing-note">
        El inventario muestra los datos cargados en el archivo de existencias y su fecha de actualización.
      </p>
    </section>
  );
}
