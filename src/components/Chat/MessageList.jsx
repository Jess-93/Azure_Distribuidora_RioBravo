import { useState } from 'react';
import createDOMPurify from 'dompurify';
import { advisorPhone } from '../../config/branches.js';

const SUGGESTED_QUESTIONS = [
  '¿Qué necesito para solicitar una devolución?',
  '¿Qué productos puedo devolver?',
  '¿Cuál es el plazo para devolver una compra?',
  '¿Cómo inicio una solicitud de devolución?',
];

const FOLLOW_UP_QUESTIONS = [
  '¿Puedes aclararme algún punto de esta respuesta?',
  '¿Qué parte de la política respalda esta respuesta?',
  '¿Qué puedo hacer a continuación?',
];

const FEEDBACK_EMAIL = 'Riobravoatencionclientes2026@outlook.com';
const QUALITY_REVIEW_STORAGE_KEY = 'rio-claro-quality-reviews-v1';

const sanitizer = typeof window !== 'undefined' ? createDOMPurify(window) : null;

function sanitizeHtml(value) {
  if (typeof value !== 'string') return '';
  if (!sanitizer) return value.replace(/[<>]/g, '');

  return sanitizer.sanitize(value, {
    ALLOWED_TAGS: ['b', 'strong', 'i', 'em', 'u', 'br', 'p', 'ul', 'ol', 'li', 'a', 'h2', 'h3'],
    ALLOWED_ATTR: ['href', 'target', 'rel'],
    ADD_ATTR: ['target'],
    FORBID_TAGS: ['script', 'style', 'iframe', 'object', 'embed'],
    FORBID_ATTR: ['style', 'onerror', 'onload'],
  });
}

function prepareAnswer(value, messageId) {
  const html = sanitizeHtml(value);
  if (typeof window === 'undefined') return { html, headings: [] };

  const document = new DOMParser().parseFromString(html, 'text/html');
  const headings = [...document.body.querySelectorAll('h2, h3')].map((heading, index) => {
    const id = `answer-${String(messageId).replace(/[^a-zA-Z0-9_-]/g, '-')}-${index}`;
    heading.id = id;
    return { id, text: heading.textContent?.trim() ?? '' };
  }).filter((heading) => heading.text);
  const longAnswer = document.body.textContent.length > 700;

  return {
    html: document.body.innerHTML,
    headings: longAnswer && headings.length > 1 ? headings : [],
  };
}

function getPlainText(value) {
  if (typeof value !== 'string') return '';
  if (typeof window === 'undefined') return value.replace(/<[^>]*>/g, '').trim();

  const document = new DOMParser().parseFromString(sanitizeHtml(value), 'text/html');
  return document.body.textContent?.trim() ?? '';
}

function formatShareText(message, branch) {
  const content = getPlainText(message.response ?? message.content);
  const sources = message.sources?.length
    ? `\n\nFuentes consultadas:\n${message.sources.map((source) => {
      const page = Number.isFinite(source.page) && source.page > 0 ? `, página ${source.page}` : '';
      return `- ${source.title} — ${source.section}${page}`;
    }).join('\n')}`
    : '';

  return `${content}${sources}\n\nAsistente de devoluciones · Distribuidora Río Claro · Sucursal ${branch.name}`;
}

function MessageActions({ message, branch, previousQuestion, onContinue }) {
  const [copied, setCopied] = useState('');
  const [copyError, setCopyError] = useState('');

  function showConfirmation(message) {
    setCopied(message);
    window.setTimeout(() => setCopied(''), 5000);
  }

  async function copyText(value, confirmation) {
    try {
      await navigator.clipboard.writeText(value);
      showConfirmation(confirmation);
      setCopyError('');
    } catch {
      setCopyError('No se pudo copiar. Revisa los permisos del navegador.');
    }
  }

  async function copyAnswerWithSources() {
    const text = formatShareText(message, branch);
    await copyText(text, 'Respuesta y fuentes copiadas');
  }

  async function prepareAdvisorSummary() {
    const answer = getPlainText(message.response ?? message.content).slice(0, 500);
    const summary = [
      'Resumen para compartir con un ejecutivo de Distribuidora Río Claro',
      `Sucursal: ${branch.name}`,
      previousQuestion ? `Consulta: ${previousQuestion}` : '',
      `Respuesta del asistente: ${answer}${answer.length === 500 ? '…' : ''}`,
      message.sources?.length
        ? `Fuentes: ${message.sources.map((source) => source.title).join(', ')}`
        : 'La respuesta no incluyó fuentes.',
    ].filter(Boolean).join('\n\n');

    await copyText(summary, 'Resumen copiado. Pégalo donde quieras compartirlo.');
  }

  return (
    <div className="message-actions">
      <button type="button" onClick={() => copyText(getPlainText(message.response ?? message.content), 'Copiado')}>
        {copied === 'Copiado' ? 'Copiado' : 'Copiar respuesta'}
      </button>
      <button type="button" onClick={copyAnswerWithSources}>
        {copied === 'Respuesta y fuentes copiadas' ? 'Copiado con fuentes' : 'Copiar respuesta y fuentes'}
      </button>
      <a href={`tel:${advisorPhone}`}>Llamar a un ejecutivo</a>
      <button type="button" onClick={prepareAdvisorSummary}>
        {copied.startsWith('Resumen copiado')
          ? 'Resumen listo'
          : 'Preparar resumen para ejecutivo'}
      </button>
      <button type="button" onClick={onContinue}>Continuar preguntando</button>
      {copyError && <span className="message-action-error" role="status">{copyError}</span>}
      {copied && <span className="message-action-confirmation" role="status">{copied}</span>}
    </div>
  );
}

function MessageFeedback({ message, branch }) {
  const [rating, setRating] = useState('');
  const [comment, setComment] = useState('');
  const [showComment, setShowComment] = useState(false);
  const [reportReason, setReportReason] = useState('');

  if (message.id === 'welcome') return null;

  const feedbackBody = [
    `Valoración: ${rating || 'Sin seleccionar'}`,
    `Sucursal: ${branch.name}`,
    `Comentario: ${comment.trim() || 'Sin comentario adicional.'}`,
  ].filter(Boolean).join('\n\n');
  const feedbackSubject = 'Opinión sobre el asistente de devoluciones';
  const emailParameters = new URLSearchParams({
    to: FEEDBACK_EMAIL,
    subject: feedbackSubject,
    body: feedbackBody,
  }).toString().replace(/\+/g, '%20');
  const gmailComposeUrl = `https://mail.google.com/mail/?view=cm&fs=1&${emailParameters}`;
  const outlookComposeUrl = `https://outlook.live.com/mail/0/deeplink/compose?${emailParameters}`;
  const reportBody = [
    `Sucursal: ${branch.name}`,
    `Motivo: ${reportReason}`,
    `Respuesta posiblemente incorrecta o desactualizada: ${getPlainText(message.response ?? message.content).slice(0, 500)}`,
  ].join('\n\n');
  const reportParameters = new URLSearchParams({
    to: FEEDBACK_EMAIL,
    subject: 'Reporte de respuesta del asistente',
    body: reportBody,
  }).toString().replace(/\+/g, '%20');
  const gmailReportUrl = `https://mail.google.com/mail/?view=cm&fs=1&${reportParameters}`;
  const outlookReportUrl = `https://outlook.live.com/mail/0/deeplink/compose?${reportParameters}`;

  return (
    <div className="message-feedback">
      <p>¿Te fue útil?</p>
      <div className="feedback-options">
        <button type="button" aria-pressed={rating === 'Sí'} onClick={() => { setRating('Sí'); setShowComment(false); }}>
          Sí
        </button>
        <button type="button" aria-pressed={rating === 'No'} onClick={() => { setRating('No'); setShowComment(true); }}>
          No
        </button>
      </div>
      {showComment && (
        <label className="feedback-comment">
          ¿Qué faltó?
          <textarea
            value={comment}
            maxLength={500}
            rows={2}
            onChange={(event) => setComment(event.target.value)}
            placeholder="Cuéntanos qué información habría sido útil."
          />
        </label>
      )}
      {rating && (
        <>
          <p>Formulario: valoración, sucursal y comentario. Se abrirá un borrador; revisa los datos y pulsa “Enviar” en tu correo.</p>
          <div className="feedback-email-actions" aria-label="Elige dónde redactar tu opinión">
            <a className="feedback-send" href={gmailComposeUrl} target="_blank" rel="noopener noreferrer">
              Abrir Gmail
            </a>
            <a className="feedback-send" href={outlookComposeUrl} target="_blank" rel="noopener noreferrer">
              Abrir Outlook
            </a>
          </div>
          <p className="feedback-email-recipient">Destinatario: {FEEDBACK_EMAIL}</p>
          <p className="feedback-response-time">El tiempo de respuesta al correo puede ser de 8 a 24 horas.</p>
        </>
      )}
      <details className="response-report">
        <summary>Reportar respuesta incorrecta o desactualizada</summary>
        <label>
          Motivo del reporte
          <select value={reportReason} onChange={(event) => setReportReason(event.target.value)}>
            <option value="">Selecciona un motivo</option>
            <option value="La respuesta podría ser incorrecta">Podría ser incorrecta</option>
            <option value="La respuesta podría estar desactualizada">Podría estar desactualizada</option>
          </select>
        </label>
        {reportReason && (
          <>
            <p>Se preparará un correo con la sucursal, el motivo y un fragmento de la respuesta. Tú decides si lo envías.</p>
            <div className="feedback-email-actions">
              <a className="feedback-send" href={gmailReportUrl} target="_blank" rel="noopener noreferrer">Reportar con Gmail</a>
              <a className="feedback-send" href={outlookReportUrl} target="_blank" rel="noopener noreferrer">Reportar con Outlook</a>
            </div>
          </>
        )}
      </details>
    </div>
  );
}

function QualityReview({ message }) {
  const [savedReview, setSavedReview] = useState(() => {
    try {
      const entries = JSON.parse(window.localStorage.getItem(QUALITY_REVIEW_STORAGE_KEY) || '{}');
      return entries && typeof entries === 'object' && !Array.isArray(entries)
        ? entries[message.id] ?? null
        : null;
    } catch {
      return null;
    }
  });
  const [sourcesChecked, setSourcesChecked] = useState(false);
  const [policyChecked, setPolicyChecked] = useState(false);
  const [reviewError, setReviewError] = useState('');

  function saveReview() {
    try {
      const parsed = JSON.parse(window.localStorage.getItem(QUALITY_REVIEW_STORAGE_KEY) || '{}');
      const entries = parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
      const savedAt = new Date().toISOString();
      const nextEntries = {
        ...entries,
        [message.id]: {
          reviewedAt: savedAt,
          sourceTitles: message.sources?.map((source) => source.title) ?? [],
          sourcesPresent: Boolean(message.sources?.length),
          sourcesInspected: sourcesChecked,
          policyAligned: policyChecked,
        },
      };
      const boundedEntries = Object.fromEntries(Object.entries(nextEntries).slice(-100));
      window.localStorage.setItem(QUALITY_REVIEW_STORAGE_KEY, JSON.stringify(boundedEntries));
      setSavedReview(nextEntries[message.id]);
      setReviewError('');
    } catch {
      setReviewError('No se pudo guardar la revisión en este dispositivo.');
    }
  }

  return (
    <details className="quality-review">
      <summary>Revisión de calidad</summary>
      <div className="quality-review-content">
        <p>Revisión manual auxiliar; el registro permanece solo en este dispositivo.</p>
        <label>
          <input
            type="checkbox"
            checked={sourcesChecked}
            onChange={(event) => setSourcesChecked(event.target.checked)}
        />
        {message.sources?.length
          ? 'Inspeccioné las fuentes citadas y su validez'
          : 'Confirmé que la respuesta no incluye fuentes (hallazgo)'}
        </label>
        <label>
          <input
            type="checkbox"
            checked={policyChecked}
            onChange={(event) => setPolicyChecked(event.target.checked)}
          />
          Comparé la respuesta con la política oficial vigente
        </label>
        <button type="button" onClick={saveReview} disabled={!sourcesChecked || !policyChecked}>
          Registrar revisión
        </button>
        {savedReview?.reviewedAt && (
          <span role="status">
            Última revisión local: {new Date(savedReview.reviewedAt).toLocaleString()}
            {!savedReview.sourcesPresent && ' · respuesta sin fuentes; requiere seguimiento'}
            {savedReview.sourcesPresent && !savedReview.sourcesInspected && ' · fuentes no verificadas'}
            {!savedReview.policyAligned && ' · alineación con política no confirmada'}
          </span>
        )}
        {reviewError && <span role="alert">{reviewError}</span>}
      </div>
    </details>
  );
}

function Sources({ sources }) {
  if (!sources?.length) return null;

  return (
    <details className="message-sources">
      <summary>Fuentes consultadas <span aria-hidden="true">({sources.length})</span></summary>
      <ul>
        {sources.map((source, index) => (
          <li key={`${source.title}-${source.page}-${index}`}>
            <span className="source-title">{source.title}</span>
            <span>{source.section}</span>
            {Number.isFinite(source.page) && source.page > 0 && <span>Página {source.page}</span>}
          </li>
        ))}
      </ul>
    </details>
  );
}

function Message({ message, branch, previousQuestion, onContinue, qualityReviewEnabled }) {
  if (message.role === 'system') {
    return (
      <div className="branch-change-notice" role="status">
        {message.content}
      </div>
    );
  }

  const isUser = message.role === 'user';
  const content = message.response ?? message.content;
  const answer = prepareAnswer(content, message.id);

  return (
    <article className={`message-row ${isUser ? 'from-user' : 'from-agent'}`}>
      <div className="message-content">
        {!isUser && <span className="message-author">Río Claro · Asistente</span>}
        {!isUser && answer.headings.length > 0 && (
          <nav className="answer-outline" aria-label="Índice de la respuesta">
            <p>En esta respuesta</p>
            <ol>
              {answer.headings.map((heading) => (
                <li key={heading.id}><a href={`#${heading.id}`}>{heading.text}</a></li>
              ))}
            </ol>
          </nav>
        )}
        <div
          className="message-bubble"
          dangerouslySetInnerHTML={isUser ? undefined : { __html: answer.html }}
        >
          {isUser ? content : null}
        </div>
        {!isUser && <Sources sources={message.sources} />}
        {!isUser && (
          <>
            <MessageActions
              message={message}
              branch={branch}
              previousQuestion={previousQuestion}
              onContinue={onContinue}
            />
            <MessageFeedback message={message} branch={branch} />
            {qualityReviewEnabled && message.id !== 'welcome' && <QualityReview message={message} />}
          </>
        )}
        {message.escalateToHuman && (
          <div className="advisor-card">
            <p>Se requiere revisión de un ejecutivo de cuenta.</p>
            <a className="advisor-action" href={`tel:${advisorPhone}`}>
              Contactar Asesor de Devoluciones
            </a>
          </div>
        )}
      </div>
    </article>
  );
}

export default function MessageList({
  messages,
  isTyping,
  isSlowResponse,
  listRef,
  branch,
  showSuggestions,
  onSuggestionSelect,
  suggestionsDisabled,
  onContinue,
  qualityReviewEnabled,
}) {
  const lastMessage = messages[messages.length - 1];
  const showFollowUps = messages.length > 2 && lastMessage?.role === 'assistant' && !isTyping;

  return (
    <div
      className="message-list"
      ref={listRef}
      role="log"
      aria-label="Conversación"
      aria-live="polite"
      aria-relevant="additions text"
      aria-atomic="false"
    >
      {messages.map((message, index) => (
        <Message
          key={message.id}
          message={message}
          branch={branch}
          previousQuestion={messages.slice(0, index).reverse().find((item) => item.role === 'user')?.content}
          onContinue={onContinue}
          qualityReviewEnabled={qualityReviewEnabled}
        />
      ))}
      {showSuggestions && (
        <section className="suggested-questions" aria-labelledby="suggested-questions-title">
          <h2 id="suggested-questions-title">Puedes preguntarme, por ejemplo:</h2>
          <div className="suggested-questions-list">
            {SUGGESTED_QUESTIONS.map((question) => (
              <button
                key={question}
                className="suggested-question"
                type="button"
                onClick={() => onSuggestionSelect(question)}
                disabled={suggestionsDisabled}
              >
                {question}
              </button>
            ))}
          </div>
        </section>
      )}
      {showFollowUps && (
        <section className="follow-up-questions" aria-label="Preguntas de seguimiento">
          <p>¿Quieres continuar?</p>
          <div className="follow-up-list">
            {FOLLOW_UP_QUESTIONS.map((question) => (
              <button
                key={question}
                type="button"
                onClick={() => onSuggestionSelect(question)}
                disabled={suggestionsDisabled}
              >
                {question}
              </button>
            ))}
          </div>
        </section>
      )}
      {isTyping && (
        <div className="message-row from-agent" aria-label={isSlowResponse ? 'La consulta sigue en curso' : 'El asistente está escribiendo'}>
          <div className="typing-indicator" role="status">
            <span>{isSlowResponse ? 'La consulta sigue en curso; puede tardar un poco más' : 'Consultando la política...'}</span>
            <i /><i /><i />
          </div>
        </div>
      )}
    </div>
  );
}