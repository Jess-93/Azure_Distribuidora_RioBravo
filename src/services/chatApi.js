export const isChatApiConfigured = true;

export const mockWelcome = {
  id: 'welcome',
  role: 'assistant',
  response:
    'Hola. Soy el asistente virtual de Distribuidora Río Claro. Puedo orientarte sobre nuestra política oficial de devoluciones; las decisiones finales son validadas por un ejecutivo de cuenta.',
  sources: [
    {
      title: 'Politica_Devoluciones_Oficial_2026.pdf',
      section: 'Sección 1: Alcance de la política',
      page: 1,
    },
    {
      title: 'Politica_Devoluciones_Oficial_2026.pdf',
      section: 'Sección 3: Productos perecederos',
      page: 2,
    },
  ],
};

function createSessionId() {
  if (!globalThis.crypto?.randomUUID) {
    throw new Error('Este navegador no permite crear un identificador seguro para la conversación.');
  }

  return globalThis.crypto.randomUUID();
}

const sessionId = createSessionId();

function normalizeSources(sources) {
  if (!Array.isArray(sources)) return [];

  return sources
    .filter((source) => source && typeof source === 'object' && !Array.isArray(source))
    .filter((source) => typeof source.title === 'string' && typeof source.section === 'string')
    .map((source) => ({
      title: source.title.trim().slice(0, 120),
      section: source.section.trim().slice(0, 180),
      ...(Number.isInteger(source.page) && source.page > 0 ? { page: source.page } : {}),
    }))
    .filter((source) => source.title && source.section)
    .slice(0, 5);
}

function cleanCitationMarkers(answer) {
  return answer
    .replace(/\uE200filecite\uE202.*?(?:\uE201|$)/gs, '')
    .replace(/\s*,?\s*(?:【(?:\d+:[^】]*|\d+†[^】]*)】|\[\d+:[^\]]*\])/g, '')
    .trim()
    .replace(/[ ,]+$/, '')
    .trim();
}

export async function sendChatMessage(message, { branch = 'Guadalajara', role = 'Cliente' } = {}) {
  if (typeof message !== 'string' || !message.trim()) {
    throw new Error('Escribe una consulta antes de enviar el mensaje.');
  }

  let response;
  try {
    response = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: message.trim(),
        sessionId,
        context: {
          branch: typeof branch === 'string' ? branch : 'Guadalajara',
          role: typeof role === 'string' ? role : 'Cliente',
        },
      }),
    });
  } catch (error) {
    throw new Error('No se pudo conectar con el servidor del chat. Verifica que el backend esté iniciado.', {
      cause: error,
    });
  }

  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new Error(
      response.ok
        ? 'El servidor del chat devolvió una respuesta que no es JSON válido.'
        : `El servidor del chat respondió con el estado HTTP ${response.status}.`,
    );
  }

  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    throw new Error('El servidor del chat devolvió un JSON con un formato no válido.');
  }

  if (!response.ok) {
    const detail = typeof payload.detail === 'string' ? ` ${payload.detail}` : '';
    throw new Error(`El servidor del chat respondió con el estado HTTP ${response.status}.${detail}`);
  }

  if (typeof payload.response !== 'string' || !payload.response.trim()) {
    throw new Error('El servidor del chat no devolvió una respuesta en el formato esperado.');
  }

  const cleanedResponse = cleanCitationMarkers(payload.response);
  if (!cleanedResponse) {
    throw new Error('El servidor del chat no devolvió una respuesta legible. Intenta nuevamente.');
  }

  return {
    response: cleanedResponse,
    sources: normalizeSources(payload.sources),
    escalateToHuman: payload.escalateToHuman === true,
    confidenceScore:
      typeof payload.confidenceScore === 'number' && Number.isFinite(payload.confidenceScore)
        ? payload.confidenceScore
        : undefined,
  };
}
