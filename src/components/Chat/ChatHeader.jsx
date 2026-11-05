export default function ChatHeader({ isConfigured, onNewConversation, newConversationDisabled, onPrint }) {
  return (
    <header className="chat-header">
      <div>
        <p className="chat-eyebrow">CONSULTA DE POLÍTICAS</p>
        <h1>Asistente de devoluciones</h1>
      </div>
      <div className="chat-header-actions">
        <button className="print-conversation-button" type="button" onClick={onPrint}>
          Imprimir / guardar
        </button>
        <button
          className="new-conversation-button"
          type="button"
          onClick={onNewConversation}
          disabled={newConversationDisabled}
          title="Limpia el chat visible; el contexto de la sesión del asistente se conserva"
        >
          Limpiar conversación
        </button>
        <div
          className={`connection-status ${isConfigured ? 'is-connected' : 'is-demo'}`}
          role="status"
          aria-live="polite"
        >
          <span className="connection-dot" aria-hidden="true" />
          <span>{isConfigured ? 'Acceso público' : 'Configura acceso'}</span>
        </div>
      </div>
    </header>
  );
}