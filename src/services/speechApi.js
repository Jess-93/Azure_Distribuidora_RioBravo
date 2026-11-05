export async function getSpeechAuthorization() {
  let response;
  try {
    response = await fetch('/api/speech/token');
  } catch (error) {
    throw new Error('No se pudo conectar con el servicio de dictado de voz.', { cause: error });
  }

  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new Error(
      response.ok
        ? 'El servicio de dictado devolvió una respuesta no válida.'
        : `El servicio de dictado respondió con el estado HTTP ${response.status}.`,
    );
  }

  if (!response.ok) {
    const detail = typeof payload?.detail === 'string' ? ` ${payload.detail}` : '';
    throw new Error(`No se pudo autorizar el dictado de voz.${detail}`);
  }

  if (
    !payload
    || typeof payload !== 'object'
    || typeof payload.token !== 'string'
    || !payload.token.trim()
    || typeof payload.region !== 'string'
    || !payload.region.trim()
  ) {
    throw new Error('El servicio de dictado devolvió datos de autorización no válidos.');
  }

  return { token: payload.token, region: payload.region };
}
