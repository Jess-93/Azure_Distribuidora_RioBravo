import { useEffect, useRef, useState } from 'react';
import createDOMPurify from 'dompurify';
import ChatInput from './ChatInput.jsx';
import {
  chatInventory,
  getInventoryCatalog,
  loginInventory,
} from '../../services/inventoryApi.js';

const sanitizer = typeof window !== 'undefined' ? createDOMPurify(window) : null;

const SKU_DEMO_QUESTION_TEMPLATES = [
  ({ sku }) => `¿Cuánta existencia hay del ${sku}?`,
  ({ sku }) => `¿Qué precio tiene el ${sku}?`,
  ({ sku }) => `¿Qué producto corresponde al ${sku}?`,
  ({ sku }) => `¿Qué presentación tiene el ${sku}?`,
  ({ sku }) => `¿Qué fecha de actualización tiene el ${sku}?`,
];

const GENERAL_DEMO_QUESTIONS = [
  '¿Qué hay en Línea Blanca?',
  'Dame los 3 productos con más existencias.',
  'Dame los 3 productos con precio más alto.',
  'Muestra el catálogo completo.',
  'Dame 3 productos al azar.',
  'Dame los inventarios de licuadoras, escobas, parrillas y Línea Blanca.',
  '¿Cuánto cuesta y cuántas unidades hay de la cafetera AromaPlus?',
];

function createDemoQuestions(items) {
  if (!items.length) return [];

  const skuQuestions = SKU_DEMO_QUESTION_TEMPLATES.map((createQuestion, index) => (
    createQuestion(items[index % items.length])
  ));
  return [...skuQuestions, ...GENERAL_DEMO_QUESTIONS];
}

function sanitizeInventoryHtml(value) {
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

function getInventoryPlainText(value) {
  const sanitized = sanitizeInventoryHtml(value);
  if (typeof window === 'undefined') return sanitized.replace(/<[^>]*>/g, '').trim();

  const document = new DOMParser().parseFromString(sanitized, 'text/html');
  return document.body.textContent?.trim() ?? '';
}

function createWelcomeMessage() {
  return {
    id: 'inventory-welcome',
    role: 'assistant',
    content: 'Hola. Soy Río, tu asistente de almacén. Pregúntame por un producto o SKU y te indicaré la existencia disponible y la fecha registrada en el inventario. Si hay varias presentaciones, te mostraré las opciones para que elijas.',
  };
}

function formatUpdatedAt(value) {
  const dateOnly = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (dateOnly) {
    return new Date(Number(dateOnly[1]), Number(dateOnly[2]) - 1, Number(dateOnly[3]))
      .toLocaleDateString('es-MX', { dateStyle: 'long' });
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('es-MX');
}

function normalizeCatalogText(value) {
  return value
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLocaleLowerCase('es');
}

function formatPrice(value) {
  return new Intl.NumberFormat('es-MX', {
    style: 'currency',
    currency: 'MXN',
  }).format(Number(value));
}

function priceLabel(item, showPrice) {
  if (!showPrice) return '';
  return item.priceMxn
    ? `Precio: ${formatPrice(item.priceMxn)} MXN`
    : 'Precio: no registrado';
}

function formatInventoryAnswer(result) {
  if (result.status === 'help') {
    return '¡Claro! Puedo consultar existencias por nombre, presentación o SKU; mostrar varias opciones cuando hay coincidencias; revisar precios si están registrados; y preparar listas o rankings del inventario. ¿Qué producto buscas? Por ejemplo: «¿Cuánto cloro de 1 litro queda?» o puedes escribirme su SKU.';
  }

  if (result.status === 'greeting') {
    return '¡Hola! Soy Río, tu asistente de almacén. Dime el nombre, la presentación o el SKU de un producto y con gusto reviso sus existencias.';
  }

  if (result.status === 'not_found') {
    return 'No logré ubicar ese producto en el inventario. ¿Me compartes su nombre, presentación o SKU? También puedes explorar el catálogo y elegir el producto que buscas.';
  }

  if (result.status === 'no_prices') {
    return 'No hay precios registrados en el inventario para preparar ese ranking.';
  }

  if (result.status === 'ambiguous') {
    return 'Encontré varias opciones con ese nombre. Revisa las presentaciones y existencias de abajo, y elige el producto que buscas.';
  }

  if (result.status === 'closest_match') {
    if (result.candidates?.length) {
      return 'No encontré una coincidencia exacta. Estas son las coincidencias más cercanas; revisa las presentaciones y existencias para elegir la correcta.';
    }
    return `No encontré una coincidencia exacta. La coincidencia más cercana es: ${formatInventoryAnswer({ ...result, status: 'found' })}`;
  }

  if (result.status === 'ranking') {
    if (result.rankingBy === 'price') {
      return `Aquí tienes los ${result.groups[0]?.items.length ?? 0} productos con mayor precio, ordenados de mayor a menor.`;
    }
    return `Ranking actualizado desde el CSV. Los productos están ordenados por existencia dentro de cada unidad; las piezas, paquetes y juegos no se comparan entre sí. Se muestran hasta ${result.limit} códigos por unidad, incluyendo empates.`;
  }

  if (result.status === 'inventory_list') {
    const totalProducts = result.groups.reduce((total, group) => total + group.count, 0);
    const totalsByUnit = result.groups
      .map((group) => `${group.total} ${group.unit}`)
      .join(', ');
    return `Inventario completo actualizado desde el CSV: ${totalProducts} productos. Totales por unidad: ${totalsByUnit}. Las cantidades se mantienen separadas por unidad y la lista completa aparece abajo.`;
  }

  if (result.status === 'multiple_matches') {
    const unmatchedText = result.unmatched?.length
      ? ` No encontré coincidencias para: ${result.unmatched.join(', ')}.`
      : '';
    return `Busqué cada producto solicitado por separado. Revisa las coincidencias y elige la presentación correcta cuando haya varias.${unmatchedText}`;
  }

  if (result.status === 'random_selection') {
    return `Aquí tienes una selección aleatoria de ${result.items.length} productos del inventario, con su código y existencia.`;
  }

  const { item } = result;
  if (result.status === 'found' && result.requestedFields?.length) {
    const requestedDetails = result.requestedFields.map((field) => {
      if (field === 'exists') return `Sí, ${item.sku} está registrado en el inventario`;
      if (field === 'available') return `Existencia disponible: ${item.available} ${item.unit}`;
      if (field === 'updatedAt') return `Fecha de actualización: ${formatUpdatedAt(item.updatedAt)}`;
      if (field === 'priceMxn') {
        return item.priceMxn
          ? `Precio: ${formatPrice(item.priceMxn)} MXN`
          : 'Precio: no registrado';
      }
      if (field === 'product') return `Producto: ${item.product}`;
      if (field === 'presentation') return `Presentación: ${item.presentation}`;
      if (field === 'sku') return `SKU: ${item.sku}`;
      return '';
    }).filter(Boolean);
    if (requestedDetails.length) return `${requestedDetails.join('. ')}.`;
  }

  const priceDetails = result.priceRequested
    ? item.priceMxn
      ? ` Precio: ${formatPrice(item.priceMxn)} MXN.`
      : ' Precio: no registrado.'
    : '';
  return `Existencia disponible: ${item.available} ${item.unit} de ${item.product}, ${item.presentation}. Código de inventario: ${item.sku}. Fecha registrada en el inventario: ${formatUpdatedAt(item.updatedAt)}.${priceDetails}`;
}

function InventoryLogin({ onLogin, isLoggingIn, error }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');

  async function submitLogin(event) {
    event.preventDefault();
    const authenticated = await onLogin(username.trim(), password);
    if (authenticated) {
      setUsername('');
      setPassword('');
    }
  }

  return (
    <section className="chat-panel inventory-login-panel" aria-labelledby="inventory-login-title">
      <aside className="inventory-demo-note" aria-label="Acceso para demostración">
        <strong>Acceso para demostración</strong>
        <span>Usuario: Almacén1</span>
        <span>Contraseña: riobravo1</span>
      </aside>
      <div className="inventory-login-content">
        <p className="chat-eyebrow">ACCESO PARA COLABORADORES</p>
        <h1 id="inventory-login-title">Iniciar sesión en almacén</h1>
        <p>Ingresa tus credenciales para consultar el catálogo y las existencias.</p>
        <form className="inventory-login-form" onSubmit={submitLogin}>
          <label>
            Usuario
            <input
              type="text"
              name="username"
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              maxLength={80}
              required
              disabled={isLoggingIn}
            />
          </label>
          <label>
            Contraseña
            <input
              type="password"
              name="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              maxLength={200}
              required
              disabled={isLoggingIn}
            />
          </label>
          <button type="submit" disabled={isLoggingIn || !username.trim() || !password}>
            {isLoggingIn ? 'Verificando…' : 'Entrar al almacén'}
          </button>
          {error && <p className="inventory-error" role="alert">{error}</p>}
        </form>
        <p className="inventory-login-note">La sesión vence en una hora y no se conserva al cerrar esta pestaña.</p>
      </div>
    </section>
  );
}

export default function EmployeeInventoryChat() {
  const [messages, setMessages] = useState([createWelcomeMessage()]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [readAloudMessageId, setReadAloudMessageId] = useState('');
  const [readResponsesEnabled, setReadResponsesEnabled] = useState(true);
  const [credentials, setCredentials] = useState(null);
  const [accessToken, setAccessToken] = useState('');
  const [isLoggingIn, setIsLoggingIn] = useState(false);
  const [loginError, setLoginError] = useState('');
  const [catalog, setCatalog] = useState([]);
  const [catalogError, setCatalogError] = useState('');
  const [catalogSearch, setCatalogSearch] = useState('');
  const [catalogOpen, setCatalogOpen] = useState(false);
  const [inputClearToken, setInputClearToken] = useState(0);
  const messageListRef = useRef(null);
  const inputRef = useRef(null);
  const sessionIdRef = useRef(crypto.randomUUID());

  useEffect(() => {
    const list = messageListRef.current;
    if (list) list.scrollTop = list.scrollHeight;
  }, [messages, isLoading]);

  useEffect(() => () => window.speechSynthesis?.cancel(), []);

  useEffect(() => {
    if (!credentials || !accessToken) return undefined;
    let active = true;
    const timeoutId = window.setTimeout(() => {
      if (!active) return;
      setCredentials(null);
      setAccessToken('');
      setCatalog([]);
      setError('La sesión del almacén venció. Inicia sesión para continuar.');
    }, credentials.expiresIn * 1000);
    return () => {
      active = false;
      window.clearTimeout(timeoutId);
    };
  }, [credentials, accessToken]);

  useEffect(() => {
    if (!accessToken) return undefined;
    let active = true;
    getInventoryCatalog(accessToken)
      .then((items) => {
        if (active) {
          setCatalog(items);
          setCatalogError('');
        }
      })
      .catch((catalogLoadError) => {
        if (!active) return;
        if (catalogLoadError.status === 401) {
          setCredentials(null);
          setAccessToken('');
          setCatalog([]);
          setError('La sesión del almacén venció. Inicia sesión para continuar.');
          return;
        }
        setCatalogError(catalogLoadError.message || 'No se pudo cargar el catálogo.');
      });
    return () => {
      active = false;
    };
  }, [accessToken]);

  async function handleLogin(username, password) {
    setIsLoggingIn(true);
    setLoginError('');
    setError('');
    try {
      const session = await loginInventory(username, password);
      setAccessToken(session.accessToken);
      setCredentials({ expiresIn: session.expiresIn });
      sessionIdRef.current = crypto.randomUUID();
      setMessages([createWelcomeMessage()]);
      setLoginError('');
      return true;
    } catch (loginRequestError) {
      setLoginError(
        loginRequestError.status === 401
          ? 'Usuario o contraseña incorrectos, por favor verifique de nuevo.'
          : loginRequestError.message || 'No se pudo iniciar sesión.',
      );
      return false;
    } finally {
      setIsLoggingIn(false);
    }
  }

  function expireSession() {
    setCredentials(null);
    setAccessToken('');
    setCatalog([]);
    setError('La sesión del almacén venció. Inicia sesión para continuar.');
  }

  function resetChat() {
    if (isLoading) return;
    window.speechSynthesis?.cancel();
    setReadAloudMessageId('');
    setMessages([createWelcomeMessage()]);
    setError('');
    setCatalogSearch('');
    sessionIdRef.current = crypto.randomUUID();
    setInputClearToken((token) => token + 1);
  }

  async function handleSend(query, exactSku = '') {
    if (isLoading || !accessToken) return false;
    setMessages((currentMessages) => [
      ...currentMessages,
      { id: `inventory-user-${Date.now()}`, role: 'user', content: query },
    ]);
    setIsLoading(true);
    setError('');

    try {
      const result = await chatInventory(exactSku || query, accessToken, sessionIdRef.current);
      const hasStructuredResults = [
        'ambiguous',
        'closest_match',
        'inventory_list',
        'multiple_matches',
        'random_selection',
        'ranking',
      ].includes(result.status);
      const assistantMessage = {
        id: `inventory-assistant-${Date.now()}`,
        role: 'assistant',
        content: hasStructuredResults || result.requestedFields?.length
          ? formatInventoryAnswer(result)
          : result.assistantResponse || formatInventoryAnswer(result),
        responseMode: result.mode || 'inventory',
        priceRequested: result.priceRequested === true,
        rankingBy: result.rankingBy || 'stock',
        rankingGroups: result.status === 'ranking' ? result.groups : [],
        inventoryGroups: result.status === 'inventory_list' ? result.groups : [],
        randomItems: result.status === 'random_selection' ? result.items : [],
        matches: result.status === 'multiple_matches' ? result.matches : [],
        candidates: ['ambiguous', 'closest_match'].includes(result.status)
          ? result.candidates || []
          : [],
      };
      setMessages((currentMessages) => [
        ...currentMessages,
        assistantMessage,
      ]);
      if (readResponsesEnabled) readAnswer(assistantMessage);
      return true;
    } catch (requestError) {
      if (requestError.status === 401) {
        expireSession();
        return false;
      }
      setError(requestError.message || 'No se pudo consultar el inventario.');
      return false;
    } finally {
      setIsLoading(false);
    }
  }

  function selectProduct(item) {
    const query = `¿Cuánto ${item.product}, ${item.presentation}, nos queda?`;
    return handleSend(query, item.sku);
  }

  function selectDemoQuestion(question) {
    const input = inputRef.current;
    if (!input || isLoading) return;

    input.value = question;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.focus();
  }

  function readAnswer(message) {
    if (!('speechSynthesis' in window) || !('SpeechSynthesisUtterance' in window)) {
      setError('Este navegador no permite leer la respuesta en voz alta.');
      return;
    }

    if (readAloudMessageId === message.id) {
      window.speechSynthesis.cancel();
      setReadAloudMessageId('');
      return;
    }

    window.speechSynthesis.cancel();
    const candidateText = message.candidates?.length
      ? ` Opciones encontradas: ${message.candidates.map((item) => (
        `${item.product}, ${item.presentation}: ${item.available} ${item.unit}. Código ${item.sku}${
          message.priceRequested ? `. ${priceLabel(item, true)}` : ''
        }`
      )).join('. ')}.`
      : '';
    const rankingText = message.rankingGroups?.length
      ? ` ${message.rankingGroups.map((group) => (
        `${message.rankingBy === 'price' ? 'Ranking por precio' : `Unidad ${group.unit}`}. ${
          group.items.map((item, index) => (
            `Lugar ${index + 1}: código ${item.sku}, ${item.product}${
              message.rankingBy === 'price'
                ? `. ${priceLabel(item, true)}`
                : `, ${item.available} ${item.unit}${message.priceRequested ? `. ${priceLabel(item, true)}` : ''}`
            }`
          )).join('. ')
        }`
      )).join('. ')}.`
      : '';
    const inventoryListText = message.inventoryGroups?.length
      ? message.priceRequested
        ? ` ${message.inventoryGroups.map((group) => (
          `Unidad ${group.unit}. ${group.items.map((item) => (
            `${item.sku}, ${item.product}. ${priceLabel(item, true)}`
          )).join('. ')}`
        )).join('. ')}.`
        : ' La lista completa de productos está visible en la pantalla.'
      : '';
    const multipleMatchesText = message.matches?.length
      ? ` ${message.matches.map((match) => (
        `${match.closest ? 'Coincidencia aproximada' : 'Coincidencias'} para ${match.term}: ${
          match.items.map((item) => (
            `${item.product}, ${item.available} ${item.unit}, código ${item.sku}${
              message.priceRequested ? `. ${priceLabel(item, true)}` : ''
            }`
          )).join('. ')
        }`
      )).join('. ')}.`
      : '';
    const randomItemsText = message.randomItems?.length
      ? ` ${message.randomItems.map((item) => (
        `${item.sku}, ${item.product}, ${item.available} ${item.unit}${
          message.priceRequested ? `. ${priceLabel(item, true)}` : ''
        }`
      )).join('. ')}.`
      : '';
    const utterance = new SpeechSynthesisUtterance(
      `${getInventoryPlainText(message.content)}${candidateText}${rankingText}${inventoryListText}${multipleMatchesText}${randomItemsText}`,
    );
    utterance.lang = 'es-MX';
    utterance.onend = () => setReadAloudMessageId('');
    utterance.onerror = () => {
      setReadAloudMessageId('');
      setError('No se pudo reproducir la respuesta en voz alta.');
    };
    setReadAloudMessageId(message.id);
    window.speechSynthesis.speak(utterance);
  }

  const normalizedCatalogSearch = normalizeCatalogText(catalogSearch.trim());
  const filteredCatalog = catalog.filter((item) => (
    `${item.product} ${item.presentation} ${item.sku} ${item.aliases}`
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .toLocaleLowerCase('es')
      .includes(normalizedCatalogSearch)
  ));

  if (!accessToken) {
    return (
      <InventoryLogin
        onLogin={handleLogin}
        isLoggingIn={isLoggingIn}
        error={loginError || error}
      />
    );
  }

  return (
    <section className="chat-panel inventory-chat-panel" aria-label="Chat de inventario para colaboradores">
      <header className="chat-header">
        <div>
          <p className="chat-eyebrow">CONSULTA DE EXISTENCIAS</p>
          <h1>Asistente de almacén</h1>
        </div>
        <div className="inventory-chat-header-actions">
          <span className="inventory-data-label">Fuente: archivo CSV</span>
          <button
            className="inventory-logout-button"
            type="button"
            onClick={resetChat}
            disabled={isLoading}
          >
            Reiniciar chat
          </button>
          <button
            className="inventory-logout-button"
            type="button"
            aria-pressed={readResponsesEnabled}
            onClick={() => {
              const shouldEnable = !readResponsesEnabled;
              setReadResponsesEnabled(shouldEnable);
              if (!shouldEnable) {
                window.speechSynthesis?.cancel();
                setReadAloudMessageId('');
              }
            }}
          >
            {readResponsesEnabled ? 'Desactivar lectura automática' : 'Activar lectura automática'}
          </button>
          <button
            className="inventory-logout-button"
            type="button"
            onClick={() => {
              window.speechSynthesis?.cancel();
              setCredentials(null);
              setAccessToken('');
              setCatalog([]);
              setMessages([createWelcomeMessage()]);
            }}
          >
            Cerrar sesión
          </button>
        </div>
      </header>
      <div
        className="message-list inventory-message-list"
        ref={messageListRef}
        role="log"
        aria-label="Conversación de inventario"
        aria-live="polite"
        aria-relevant="additions text"
        aria-atomic="false"
      >
        {messages.map((message) => (
          <article
            className={`message-row ${message.role === 'user' ? 'from-user' : 'from-agent'}`}
            key={message.id}
          >
            <div className="message-content">
              {message.role === 'assistant' && (
                <span className="message-author">Río · Asistente de almacén</span>
              )}
              <div
                className="message-bubble"
                dangerouslySetInnerHTML={message.role === 'assistant'
                  ? { __html: sanitizeInventoryHtml(message.content) }
                  : undefined}
              >
                {message.role === 'user' ? message.content : null}
              </div>
              {message.candidates?.length > 0 && (
                <div className="inventory-candidate-list" aria-label="Productos coincidentes">
                  {message.candidates.map((item) => (
                    <button
                      className="inventory-candidate"
                      key={item.sku}
                      type="button"
                      onClick={() => selectProduct(item)}
                      disabled={isLoading}
                    >
                      <span className="inventory-candidate-name">
                        {item.product} · {item.presentation}
                      </span>
                      <span>Disponible: {item.available} {item.unit}</span>
                      <span>Código: {item.sku} · actualizado {formatUpdatedAt(item.updatedAt)}</span>
                      {message.priceRequested && <span>{priceLabel(item, true)}</span>}
                      <strong>Consultar este producto</strong>
                    </button>
                  ))}
                </div>
              )}
              {message.rankingGroups?.length > 0 && (
                <div
                  className="inventory-ranking"
                  aria-label={message.rankingBy === 'price' ? 'Ranking de precios' : 'Ranking de existencias por unidad'}
                >
                  {message.rankingGroups.map((group) => (
                    <section className="inventory-ranking-group" key={group.unit}>
                      <h2>
                        {message.rankingBy === 'price' ? 'Precios más altos' : `Más existencias · ${group.unit}`}
                      </h2>
                      <ol>
                        {group.items.map((item) => (
                          <li key={item.sku}>
                            <strong>{item.sku}</strong>
                            <span>{item.product} · {item.presentation}</span>
                            {message.rankingBy === 'price'
                              ? <span>{priceLabel(item, true)}</span>
                              : (
                                <>
                                  <span>{item.available} {item.unit}</span>
                                  {message.priceRequested && <span>{priceLabel(item, true)}</span>}
                                </>
                              )}
                          </li>
                        ))}
                      </ol>
                    </section>
                  ))}
                </div>
              )}
              {message.inventoryGroups?.length > 0 && (
                <div className="inventory-ranking" aria-label="Inventario completo por unidad">
                  {message.inventoryGroups.map((group) => (
                    <section className="inventory-ranking-group" key={group.unit}>
                      <h2>
                        {group.unit}: {group.total} en total · {group.count} productos
                      </h2>
                      <ol>
                        {group.items.map((item) => (
                          <li key={item.sku}>
                            <strong>{item.sku}</strong>
                            <span>{item.product} · {item.presentation}</span>
                            <span>{item.available} {item.unit} · actualizado {formatUpdatedAt(item.updatedAt)}</span>
                            {message.priceRequested && <span>{priceLabel(item, true)}</span>}
                          </li>
                        ))}
                      </ol>
                    </section>
                  ))}
                </div>
              )}
              {message.matches?.length > 0 && (
                <div className="inventory-ranking" aria-label="Coincidencias para cada producto solicitado">
                  {message.matches.map((match) => (
                    <section className="inventory-ranking-group" key={match.term}>
                      <h2>
                        {match.closest ? 'Coincidencia más cercana' : 'Coincidencias'} · {match.term}
                      </h2>
                      <div className="inventory-candidate-list">
                        {match.items.map((item) => (
                          <button
                            className="inventory-candidate"
                            key={item.sku}
                            type="button"
                            onClick={() => selectProduct(item)}
                            disabled={isLoading}
                          >
                            <span className="inventory-candidate-name">
                              {item.product} · {item.presentation}
                            </span>
                            <span>Disponible: {item.available} {item.unit}</span>
                            <span>Código: {item.sku} · actualizado {formatUpdatedAt(item.updatedAt)}</span>
                            {message.priceRequested && <span>{priceLabel(item, true)}</span>}
                            <strong>Consultar este producto</strong>
                          </button>
                        ))}
                      </div>
                    </section>
                  ))}
                </div>
              )}
              {message.randomItems?.length > 0 && (
                <div className="inventory-candidate-list" aria-label="Selección aleatoria del inventario">
                  {message.randomItems.map((item) => (
                    <button
                      className="inventory-candidate"
                      key={item.sku}
                      type="button"
                      onClick={() => selectProduct(item)}
                      disabled={isLoading}
                    >
                      <span className="inventory-candidate-name">
                        {item.product} · {item.presentation}
                      </span>
                      <span>Disponible: {item.available} {item.unit}</span>
                      <span>Código: {item.sku} · actualizado {formatUpdatedAt(item.updatedAt)}</span>
                      {message.priceRequested && <span>{priceLabel(item, true)}</span>}
                      <strong>Consultar este producto</strong>
                    </button>
                  ))}
                </div>
              )}
              {message.role === 'assistant' && message.id !== 'inventory-welcome' && (
                <button
                  className="inventory-read-aloud"
                  type="button"
                  onClick={() => readAnswer(message)}
                  aria-pressed={readAloudMessageId === message.id}
                >
                  {readAloudMessageId === message.id ? 'Detener audio' : 'Escuchar respuesta'}
                </button>
              )}
            </div>
          </article>
        ))}
        {messages.length === 1 && catalog.length > 0 && (
          <section className="suggested-questions inventory-suggestions" aria-labelledby="inventory-suggestions-title">
            <h2 id="inventory-suggestions-title">Preguntas para demostración</h2>
            <p className="inventory-suggestions-note">
              Elige una para colocarla en el campo de texto. No se enviará hasta que confirmes el envío.
            </p>
            <div className="suggested-questions-list">
              {createDemoQuestions(catalog).map((question) => (
                <button
                  className="suggested-question"
                  key={question}
                  type="button"
                  onClick={() => selectDemoQuestion(question)}
                  disabled={isLoading}
                >
                  {question}
                </button>
              ))}
            </div>
          </section>
        )}
        {isLoading && (
          <p className="inventory-loading" role="status">Consultando el archivo de inventario…</p>
        )}
      </div>
      {error && <p className="chat-error inventory-error" role="alert">{error}</p>}
      {catalogError && <p className="inventory-error" role="alert">{catalogError}</p>}
      <details
        className="inventory-catalog"
        open={catalogOpen}
        onToggle={(event) => setCatalogOpen(event.currentTarget.open)}
      >
        <summary>Explorar catálogo · {catalog.length} productos</summary>
        <label className="inventory-catalog-search">
          Buscar por nombre, presentación o SKU
          <input
            type="search"
            value={catalogSearch}
            onChange={(event) => setCatalogSearch(event.target.value)}
            placeholder="Ej. licuadora, 1 litro, SKU-1001"
          />
        </label>
        {filteredCatalog.length > 0 ? (
          <div className="inventory-catalog-list">
            {filteredCatalog.map((item) => (
              <button
                className="inventory-catalog-item"
                key={item.sku}
                type="button"
                onClick={() => selectProduct(item)}
                disabled={isLoading}
              >
                <span>{item.product} · {item.presentation}</span>
                <strong>{item.available} {item.unit}</strong>
                <small>Código: {item.sku}</small>
              </button>
            ))}
          </div>
        ) : (
          <p className="inventory-catalog-empty">No hay productos que coincidan con esa búsqueda.</p>
        )}
      </details>
      <p className="inventory-data-disclaimer">
        Existencias del archivo de inventario. Confirma la fecha de actualización antes de tomar decisiones.
      </p>
      <ChatInput
        inputRef={inputRef}
        onSend={handleSend}
        disabled={isLoading}
        clearToken={inputClearToken}
        speechHints={[
          'SKU',
          ...catalog.flatMap(({ sku }) => [
            sku,
            sku.replace(/[-\s]/g, ' '),
            sku.replace(/-/g, ''),
          ]),
        ]}
        placeholder="Pregunta por nombre, presentación o SKU"
      />
    </section>
  );
}
