import { useEffect, useRef, useState } from 'react';
import ChatHeader from './ChatHeader.jsx';
import ChatInput from './ChatInput.jsx';
import MessageList from './MessageList.jsx';
import { isChatApiConfigured, mockWelcome, sendChatMessage } from '../../services/chatApi.js';
import { advisorPhone, branches } from '../../config/branches.js';

const DISCLAIMER = 'Asistente virtual de políticas internas. Las decisiones finales son validadas por un ejecutivo de cuenta.';
const HISTORY_STORAGE_KEY = 'rio-claro-chat-history-v1';
const QUALITY_REVIEW_STORAGE_KEY = 'rio-claro-quality-reviews-v1';
const PRIVACY_CONTACT_EMAIL = 'Riobravoatencionclientes2026@outlook.com';
const MAX_SAVED_CONVERSATIONS = 10;
const MAX_SAVED_MESSAGES = 60;

function createConversationId() {
  return globalThis.crypto?.randomUUID?.() ?? `conversation-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function loadConversationHistory() {
  try {
    const stored = window.localStorage.getItem(HISTORY_STORAGE_KEY);
    if (!stored) return { entries: [], error: '' };
    const history = JSON.parse(stored);
    if (!Array.isArray(history)) return { entries: [], error: 'El historial local no tiene un formato válido y no se pudo cargar.' };

    return {
      entries: history
        .filter((item) => item
          && typeof item.id === 'string'
          && Array.isArray(item.messages)
          && item.messages.every((message) => message && typeof message === 'object' && typeof message.role === 'string'))
        .slice(0, MAX_SAVED_CONVERSATIONS),
      error: '',
    };
  } catch {
    return { entries: [], error: 'No se pudo leer el historial local en este navegador.' };
  }
}

function getWelcomeMessage(role, branch) {
  const greeting = role === 'Ejecutivo'
    ? 'Bienvenido de vuelta, estimado ejecutivo.'
    : 'Bienvenido, estimado cliente.';

  return {
    ...mockWelcome,
    response: `${greeting} Estás consultando para la sucursal ${branch.name}. Soy el asistente virtual de Distribuidora Río Claro y puedo orientarte sobre nuestra política oficial de devoluciones. Las decisiones finales son validadas por un ejecutivo de cuenta.`,
  };
}

function normalizeSearchText(value) {
  return value
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLocaleLowerCase('es');
}

function isSupportOpen(now = new Date()) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/Tijuana',
    weekday: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(now);
  const values = Object.fromEntries(parts.map(({ type, value }) => [type, value]));
  const minutes = Number(values.hour) * 60 + Number(values.minute);
  const weekdayHours = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri'].includes(values.weekday);

  return (weekdayHours && minutes >= 9 * 60 && minutes < 18 * 60)
    || (values.weekday === 'Sat' && minutes >= 7 * 60 && minutes < 12 * 60);
}

export default function ChatWindow({ selectedBranch, selectedRole }) {
  const [initialHistory] = useState(loadConversationHistory);
  const [messages, setMessages] = useState([getWelcomeMessage(selectedRole, selectedBranch)]);
  const [history, setHistory] = useState(initialHistory.entries);
  const [activeConversationId, setActiveConversationId] = useState(createConversationId);
  const [historyViewId, setHistoryViewId] = useState('');
  const [historyError, setHistoryError] = useState(initialHistory.error);
  const [historySearch, setHistorySearch] = useState('');
  const [noticesVisible, setNoticesVisible] = useState(false);
  const [isTyping, setIsTyping] = useState(false);
  const [error, setError] = useState('');
  const [failedQuery, setFailedQuery] = useState('');
  const [isSlowResponse, setIsSlowResponse] = useState(false);
  const [inputClearToken, setInputClearToken] = useState(0);
  const [supportOpen, setSupportOpen] = useState(() => isSupportOpen());
  const messageListRef = useRef(null);
  const chatInputRef = useRef(null);
  const privacyDetailsRef = useRef(null);
  const previousBranchIdRef = useRef(selectedBranch.id);
  const historyRef = useRef(history);
  const displayedHistory = history.find((item) => item.id === historyViewId);
  const displayedMessages = displayedHistory?.messages ?? messages;
  const displayedBranch = displayedHistory
    ? branches.find((branch) => branch.id === displayedHistory.branchId) ?? selectedBranch
    : selectedBranch;
  const filteredHistory = history.filter((item) => {
    const query = normalizeSearchText(historySearch.trim());
    if (!query) return true;
    const transcript = item.messages
      .map((message) => (typeof message.content === 'string' ? message.content : message.response))
      .filter((text) => typeof text === 'string')
      .join(' ');
    return normalizeSearchText(`${item.branchName ?? ''} ${item.title ?? ''} ${transcript}`).includes(query);
  });

  function saveHistoryEntry(entry) {
    const nextHistory = [entry, ...historyRef.current.filter((item) => item.id !== entry.id)]
      .slice(0, MAX_SAVED_CONVERSATIONS);
    historyRef.current = nextHistory;
    setHistory(nextHistory);
    try {
      window.localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(nextHistory));
      setHistoryError('');
    } catch {
      setHistoryError('No se pudo guardar el historial en este dispositivo. Revisa el espacio disponible o los permisos del navegador.');
    }
  }

  useEffect(() => {
    const firstQuestion = messages.find((message) => message.role === 'user')?.content;
    if (historyViewId || !firstQuestion) return;

    saveHistoryEntry({
      id: activeConversationId,
      title: firstQuestion.slice(0, 72),
      updatedAt: new Date().toISOString(),
      branchId: selectedBranch.id,
      branchName: selectedBranch.name,
      role: selectedRole,
      messages: messages.slice(-MAX_SAVED_MESSAGES),
    });
  }, [messages, activeConversationId, historyViewId, selectedBranch, selectedRole]);

  useEffect(() => {
    setMessages((currentMessages) => {
      if (currentMessages.length !== 1 || currentMessages[0].id !== 'welcome') return currentMessages;
      return [getWelcomeMessage(selectedRole, selectedBranch)];
    });
  }, [selectedRole, selectedBranch]);

  useEffect(() => {
    if (previousBranchIdRef.current === selectedBranch.id) return;
    previousBranchIdRef.current = selectedBranch.id;
    setMessages((currentMessages) => [
      ...currentMessages,
      {
        id: `branch-change-${Date.now()}`,
        role: 'system',
        content: `Has cambiado a «${selectedBranch.name}».`,
      },
    ]);
  }, [selectedBranch]);

  useEffect(() => {
    const list = messageListRef.current;
    if (list && !historyViewId) list.scrollTop = list.scrollHeight;
  }, [displayedMessages, isTyping, historyViewId]);

  useEffect(() => {
    if (!isTyping) {
      setIsSlowResponse(false);
      return undefined;
    }

    const timeoutId = window.setTimeout(() => setIsSlowResponse(true), 8000);
    return () => window.clearTimeout(timeoutId);
  }, [isTyping]);

  useEffect(() => {
    const updateSupportHours = () => setSupportOpen(isSupportOpen());
    const intervalId = window.setInterval(updateSupportHours, 60_000);
    return () => window.clearInterval(intervalId);
  }, []);

  async function handleSend(content, { isRetry = false } = {}) {
    if (isTyping || historyViewId) return false;
    if (!isRetry) {
      const userMessage = { id: `user-${Date.now()}`, role: 'user', content };
      setMessages((currentMessages) => [...currentMessages, userMessage]);
    }
    setIsTyping(true);
    setError('');

    try {
      const result = await sendChatMessage(content, {
        branch: selectedBranch.name,
        role: selectedRole,
      });
      setMessages((currentMessages) => [
        ...currentMessages,
        { ...result, id: `assistant-${Date.now()}`, role: 'assistant' },
      ]);
      setFailedQuery('');
      if (isRetry) setInputClearToken((token) => token + 1);
      return true;
    } catch (requestError) {
      setError(requestError.message || 'No fue posible contactar al agente. Intenta nuevamente.');
      setFailedQuery(content);
      return false;
    } finally {
      setIsTyping(false);
    }
  }

  function openHistoryEntry(id) {
    if (isTyping) return;
    setHistoryViewId(id);
    setError('');
  }

  function returnToCurrentConversation() {
    setHistoryViewId('');
    setError('');
    chatInputRef.current?.focus();
  }

  function clearHistory() {
    if (isTyping) return;
    if (!window.confirm('Se borrarán las conversaciones guardadas localmente en este dispositivo y se iniciará un chat nuevo. Esta acción no borra los datos del backend o de Foundry. ¿Deseas continuar?')) {
      return;
    }
    try {
      window.localStorage.removeItem(HISTORY_STORAGE_KEY);
      historyRef.current = [];
      setHistory([]);
      setHistoryError('');
      setHistoryViewId('');
      setMessages([getWelcomeMessage(selectedRole, selectedBranch)]);
      setActiveConversationId(createConversationId());
      setFailedQuery('');
      setError('');
      chatInputRef.current?.focus();
    } catch {
      setHistoryError('No se pudo borrar el historial local. Revisa los permisos del navegador.');
    }
  }

  function startNewConversation() {
    if (isTyping) return;
    setHistoryViewId('');
    setMessages([getWelcomeMessage(selectedRole, selectedBranch)]);
    setActiveConversationId(createConversationId());
    setFailedQuery('');
    setError('');
    chatInputRef.current?.focus();
  }

  function showPrivacyDetails() {
    if (!privacyDetailsRef.current) return;
    privacyDetailsRef.current.open = true;
    privacyDetailsRef.current.querySelector('summary')?.focus();
    privacyDetailsRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  async function copyFailedQuery() {
    try {
      await navigator.clipboard.writeText(failedQuery);
    } catch {
      setError('No se pudo copiar la consulta. Puedes seleccionarla en el campo de texto.');
    }
  }

  return (
    <section className="chat-panel" aria-label="Chat de políticas de devolución">
      <ChatHeader
        isConfigured={isChatApiConfigured}
        onNewConversation={startNewConversation}
        newConversationDisabled={isTyping || (!displayedHistory && messages.length === 1)}
        onPrint={() => window.print()}
      />
      <button
        className="notices-toggle"
        type="button"
        onClick={() => setNoticesVisible((visible) => !visible)}
        aria-expanded={noticesVisible}
        aria-controls="chat-notices"
      >
        {noticesVisible ? 'Minimizar avisos y herramientas' : 'Mostrar avisos y herramientas'}
      </button>
      <div className="chat-notices" id="chat-notices" hidden={!noticesVisible}>
      {history.length > 0 && (
        <details className="local-history">
          <summary>Historial local · {history.length}</summary>
          <div className="local-history-content">
            <p>Guardado solo en este dispositivo. Las conversaciones anteriores se muestran en modo lectura.</p>
            <label className="history-search">
              Buscar por consulta o sucursal
              <input
                type="search"
                value={historySearch}
                onChange={(event) => setHistorySearch(event.target.value)}
                placeholder="Ej. León, factura, plazo"
              />
            </label>
            <ul>
              {filteredHistory.map((item) => (
                <li key={item.id}>
                  <button type="button" onClick={() => openHistoryEntry(item.id)} disabled={isTyping}>
                    <span>{item.title || 'Consulta sin título'}</span>
                    <small>{item.branchName} · {new Date(item.updatedAt).toLocaleString()}</small>
                  </button>
                </li>
              ))}
            </ul>
            {filteredHistory.length === 0 && <p>No hay conversaciones que coincidan con la búsqueda.</p>}
            <button className="clear-history-button" type="button" onClick={clearHistory} disabled={isTyping}>
              Borrar historial y empezar de nuevo
            </button>
          </div>
        </details>
      )}
      {historyError && <p className="chat-error" role="alert">{historyError}</p>}
      <details className="support-hours">
        <summary>
          <span
            className={`support-status ${supportOpen ? 'is-open' : 'is-closed'}`}
            role="status"
            aria-live="polite"
          >
            <span aria-hidden="true" />
            Atención {supportOpen ? 'abierta' : 'cerrada'}
          </span>
          · Horario y canales
        </summary>
        <p>Horario de atención: lunes a viernes de 9:00 a. m. a 6:00 p. m. Y sábados de 7:00 a. m. a 12:00 p. m.</p>
        <p>Estado calculado con la hora local de Tijuana. El horario no garantiza respuesta inmediata.</p>
        <p>
          Ejecutivo: <a href={`tel:${advisorPhone}`}>+52 55 9602 3980</a>
          {' · '}
          Correo: <a href={`mailto:${PRIVACY_CONTACT_EMAIL}`}>{PRIVACY_CONTACT_EMAIL}</a>
        </p>
      </details>
      <details className="privacy-details" id="privacy-details" ref={privacyDetailsRef}>
        <summary>Privacidad e información de la conversación</summary>
        <div className="privacy-details-content">
          <p>
            Al consultar, se envían el texto de tu pregunta, un identificador de conversación, la sucursal y el perfil
            seleccionado al servicio de atención y a Microsoft Foundry para generar la respuesta. No necesitas iniciar sesión.
          </p>
          <p>
            Este navegador conserva hasta 10 conversaciones recientes, con un máximo de 60 mensajes por conversación,
            hasta que borres el historial aquí o elimines los datos del sitio en tu navegador.
          </p>
          <p>
            El backend conserva el identificador de conversación, el identificador de la respuesta de Foundry y la fecha
            de actualización para mantener el contexto. El código actual no define una fecha de expiración. La duración
            del tratamiento o retención adicional de Microsoft Foundry no está especificada por esta aplicación.
          </p>
          <p>
            Puedes borrar el historial local desde “Historial local”. Para solicitar que el responsable revise una
            solicitud de eliminación de datos del servicio, contacta a {PRIVACY_CONTACT_EMAIL}; la app no puede borrar
            esos datos del backend o de Foundry ni confirmar su eliminación.
          </p>
          <div className="privacy-contact-actions">
            {['Gmail', 'Outlook'].map((provider) => {
              const params = new URLSearchParams({
                to: PRIVACY_CONTACT_EMAIL,
                subject: 'Solicitud de privacidad y eliminación de datos',
                body: 'Solicito información sobre la eliminación de mis datos relacionados con el asistente de devoluciones.',
              }).toString().replace(/\+/g, '%20');
              const url = provider === 'Gmail'
                ? `https://mail.google.com/mail/?view=cm&fs=1&${params}`
                : `https://outlook.live.com/mail/0/deeplink/compose?${params}`;
              return (
                <a key={provider} href={url} target="_blank" rel="noopener noreferrer">
                  Abrir {provider} para solicitar información
                </a>
              );
            })}
          </div>
          <p className="privacy-caveat">
            La fecha de retención de Foundry y la gestión de solicitudes por correo deben confirmarse con el responsable del servicio.
          </p>
        </div>
      </details>
      {!displayedHistory && !messages.some((message) => message.role === 'user') && (
        <details className="first-message-privacy">
          <summary>Aviso de privacidad antes de consultar</summary>
          <p>
            Antes de consultar: se enviarán tu pregunta, sucursal, perfil e identificador de conversación al servicio
            para generar la respuesta. Evita compartir datos sensibles.
          </p>
          <button type="button" onClick={showPrivacyDetails}>Ver información de privacidad</button>
        </details>
      )}
      {selectedRole === 'Ejecutivo' && (
        <details className="quality-process-note">
          <summary>Control de calidad de respuestas</summary>
          <p>
            Revisa las fuentes y compáralas con la política vigente mediante el control de cada respuesta. Los registros
            se guardan solo en este navegador; no se envían a un sistema central ni representan una certificación.
            Este selector de perfil no restringe el acceso.
          </p>
        </details>
      )}
      </div>
      {displayedHistory && (
        <div className="history-view-notice" role="status">
          Viendo una conversación guardada · {displayedHistory.branchName} · solo lectura
          <button type="button" onClick={returnToCurrentConversation}>Volver al chat actual</button>
        </div>
      )}
      <MessageList
        messages={displayedMessages}
        isTyping={isTyping}
        isSlowResponse={isSlowResponse}
        listRef={messageListRef}
        branch={displayedBranch}
        qualityReviewEnabled={selectedRole === 'Ejecutivo' && !displayedHistory}
        showSuggestions={!displayedHistory && messages.length === 1}
        onSuggestionSelect={(question) => handleSend(question)}
        suggestionsDisabled={isTyping || Boolean(displayedHistory)}
        onContinue={() => chatInputRef.current?.focus()}
      />
      {error && (
        <p className="chat-error" role="alert">
          {error} Si necesitas ayuda inmediata,{' '}
          <a href={`tel:${advisorPhone}`}>contacta a un ejecutivo de {selectedBranch.name}</a>.
        </p>
      )}
      {failedQuery && !historyViewId && (
        <div className="error-actions">
          <button type="button" onClick={() => handleSend(failedQuery, { isRetry: true })} disabled={isTyping}>
            Reintentar consulta
          </button>
          <button type="button" onClick={copyFailedQuery} disabled={isTyping}>
            Copiar consulta
          </button>
        </div>
      )}
      <div className="active-branch-status" aria-label={`Sucursal activa: ${selectedBranch.name}`}>
        <span>Sucursal activa: <strong>{selectedBranch.name}</strong></span>
        <a href={`tel:${advisorPhone}`} aria-label={`Llamar al ejecutivo al ${advisorPhone}`}>
          Ejecutivo: +52 55 9602 3980
        </a>
      </div>
      <ChatInput
        inputRef={chatInputRef}
        onSend={handleSend}
        disabled={isTyping || Boolean(displayedHistory)}
        clearToken={inputClearToken}
      />
      <p className="chat-disclaimer">{DISCLAIMER}</p>
      <nav className="mobile-quick-actions" aria-label="Accesos rápidos">
        <a href={`tel:${advisorPhone}`}>Llamar</a>
        <button
          type="button"
          onClick={startNewConversation}
          disabled={isTyping || (!displayedHistory && messages.length === 1)}
        >
          Nueva conversación
        </button>
      </nav>
    </section>
  );
}