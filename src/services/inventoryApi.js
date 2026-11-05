function isNonEmptyString(value) {
  return typeof value === 'string' && value.trim().length > 0;
}

const REQUESTED_INVENTORY_FIELDS = new Set([
  'available',
  'exists',
  'priceMxn',
  'presentation',
  'product',
  'sku',
  'updatedAt',
]);

function readRequestedFields(payload) {
  if (payload.requestedFields === undefined) return [];
  if (
    !Array.isArray(payload.requestedFields)
    || payload.requestedFields.some((field) => !REQUESTED_INVENTORY_FIELDS.has(field))
  ) {
    throw new Error('El inventario devolvió campos solicitados no válidos.');
  }
  return [...new Set(payload.requestedFields)];
}

async function readApiResponse(response, operation) {
  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new Error(
      response.ok
        ? `El servicio de ${operation} devolvió una respuesta no válida.`
        : `El servicio de ${operation} respondió con el estado HTTP ${response.status}.`,
    );
  }

  if (!response.ok) {
    const detail = typeof payload?.detail === 'string' ? ` ${payload.detail}` : '';
    const error = new Error(`No se pudo completar ${operation}.${detail}`);
    error.status = response.status;
    throw error;
  }
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    throw new Error(`El servicio de ${operation} devolvió datos con un formato no válido.`);
  }
  return payload;
}

export async function loginInventory(username, password) {
  let response;
  try {
    response = await fetch('/api/inventory/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
  } catch (error) {
    throw new Error('No se pudo conectar con el inicio de sesión del almacén.', { cause: error });
  }

  const payload = await readApiResponse(response, 'el inicio de sesión');
  if (
    typeof payload.access_token !== 'string'
    || !payload.access_token.trim()
    || payload.token_type !== 'bearer'
    || !Number.isInteger(payload.expires_in)
    || payload.expires_in < 1
  ) {
    throw new Error('El inicio de sesión devolvió datos de sesión no válidos.');
  }
  return { accessToken: payload.access_token, expiresIn: payload.expires_in };
}

function authorizationHeaders(accessToken) {
  if (typeof accessToken !== 'string' || !accessToken.trim()) {
    throw new Error('Inicia sesión para consultar el inventario.');
  }
  return { Authorization: `Bearer ${accessToken}` };
}

export async function getInventoryCatalog(accessToken) {
  let response;
  try {
    response = await fetch('/api/inventory/catalog', {
      headers: authorizationHeaders(accessToken),
      cache: 'no-store',
    });
  } catch (error) {
    if (error instanceof Error && error.message === 'Inicia sesión para consultar el inventario.') {
      throw error;
    }
    throw new Error('No se pudo conectar con el catálogo de inventario.', { cause: error });
  }

  const payload = await readApiResponse(response, 'el catálogo de inventario');
  if (!Array.isArray(payload.items)) {
    throw new Error('El catálogo de inventario devolvió datos con un formato no válido.');
  }
  return payload.items
    .filter((item) => item && typeof item === 'object')
    .filter((item) => (
      isNonEmptyString(item.sku)
      && isNonEmptyString(item.product)
      && isNonEmptyString(item.presentation)
      && isNonEmptyString(item.available)
      && /^\d+(?:\.\d+)?$/.test(item.available)
      && isNonEmptyString(item.unit)
      && isNonEmptyString(item.updatedAt)
    ))
    .map((item) => ({
      sku: item.sku.trim(),
      product: item.product.trim(),
      presentation: item.presentation.trim(),
      available: item.available.trim(),
      unit: item.unit.trim(),
      updatedAt: item.updatedAt.trim(),
      aliases: typeof item.aliases === 'string' ? item.aliases.trim() : '',
    }));
}

async function requestInventory(query, accessToken, endpoint, sessionId) {
  if (typeof query !== 'string' || !query.trim()) {
    throw new Error('Di el nombre, la presentación o el SKU del producto que buscas.');
  }
  if (query.trim().length > 250) {
    throw new Error('La consulta de inventario no puede superar los 250 caracteres.');
  }
  if (sessionId !== undefined && !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(sessionId)) {
    throw new Error('El identificador de sesión del almacén no es válido.');
  }

  let response;
  try {
    response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...authorizationHeaders(accessToken),
      },
      cache: 'no-store',
      body: JSON.stringify(sessionId ? { query: query.trim(), sessionId } : { query: query.trim() }),
    });
  } catch (error) {
    if (error instanceof Error && error.message === 'Inicia sesión para consultar el inventario.') {
      throw error;
    }
    throw new Error('No se pudo conectar con el inventario. Verifica que el backend esté disponible.', {
      cause: error,
    });
  }

  const payload = await readApiResponse(response, 'el inventario');
  let mode;
  let assistantResponse;
  let inventoryPayload = payload;
  if (sessionId) {
    if (
      !['agent', 'inventory'].includes(payload.mode)
      || (payload.assistantResponse !== null && !isNonEmptyString(payload.assistantResponse))
      || !payload.result
      || typeof payload.result !== 'object'
      || Array.isArray(payload.result)
      || (payload.mode === 'agent' && !isNonEmptyString(payload.assistantResponse))
      || (payload.mode === 'inventory' && payload.assistantResponse !== null)
    ) {
      throw new Error('El chat de almacén devolvió datos con un formato no válido.');
    }
    mode = payload.mode;
    assistantResponse = payload.assistantResponse?.trim() ?? '';
    inventoryPayload = payload.result;
  }
  const completeResult = (result) => (
    sessionId ? { ...result, mode, assistantResponse } : result
  );
  if (inventoryPayload.status === 'not_found') return completeResult({ status: 'not_found' });
  if (inventoryPayload.status === 'no_prices') return completeResult({ status: 'no_prices' });
  if (inventoryPayload.status === 'help' || inventoryPayload.status === 'greeting') {
    return completeResult({ status: inventoryPayload.status });
  }

  const isValidInventoryItem = (item) => (
    item
    && typeof item === 'object'
    && isNonEmptyString(item.sku)
    && isNonEmptyString(item.product)
    && isNonEmptyString(item.presentation)
    && isNonEmptyString(item.available)
    && /^\d+(?:\.\d+)?$/.test(item.available)
    && isNonEmptyString(item.unit)
    && isNonEmptyString(item.updatedAt)
    && (
      item.priceMxn === undefined
      || (isNonEmptyString(item.priceMxn) && /^\d+(?:\.\d+)?$/.test(item.priceMxn))
    )
  );
  const cleanInventoryItem = (item) => {
    const cleanedItem = {
      sku: item.sku.trim(),
      product: item.product.trim(),
      presentation: item.presentation.trim(),
      available: item.available.trim(),
      unit: item.unit.trim(),
      updatedAt: item.updatedAt.trim(),
    };
    if (item.priceMxn !== undefined) cleanedItem.priceMxn = item.priceMxn.trim();
    return cleanedItem;
  };

  if (inventoryPayload.status === 'random_selection' && Array.isArray(inventoryPayload.items)) {
    const items = inventoryPayload.items.filter(isValidInventoryItem).map(cleanInventoryItem);
    if (items.length) {
      return completeResult({
        status: 'random_selection',
        items,
        priceRequested: inventoryPayload.priceRequested === true,
      });
    }
    throw new Error('La selección aleatoria no contiene productos válidos.');
  }

  if (inventoryPayload.status === 'multiple_matches' && Array.isArray(inventoryPayload.matches)) {
    const matches = inventoryPayload.matches
      .filter((match) => (
        match
        && typeof match === 'object'
        && isNonEmptyString(match.term)
        && typeof match.closest === 'boolean'
        && Array.isArray(match.items)
      ))
      .map((match) => ({
        term: match.term.trim(),
        closest: match.closest,
        items: match.items.filter(isValidInventoryItem).map(cleanInventoryItem),
      }))
      .filter((match) => match.items.length > 0);
    if (matches.length >= 2) {
      return completeResult({
        status: 'multiple_matches',
        matches,
        unmatched: Array.isArray(inventoryPayload.unmatched)
          ? inventoryPayload.unmatched.filter(isNonEmptyString).map((term) => term.trim())
          : [],
        priceRequested: inventoryPayload.priceRequested === true,
      });
    }
    throw new Error('La búsqueda de varios productos devolvió datos no válidos.');
  }

  if (inventoryPayload.status === 'inventory_list' && Array.isArray(inventoryPayload.groups)) {
    const groups = inventoryPayload.groups
      .filter((group) => group && typeof group === 'object')
      .filter((group) => (
        isNonEmptyString(group.unit)
        && isNonEmptyString(group.total)
        && /^\d+(?:\.\d+)?$/.test(group.total)
        && Number.isInteger(group.count)
        && group.count >= 0
        && Array.isArray(group.items)
      ))
      .map((group) => ({
        unit: group.unit.trim(),
        total: group.total.trim(),
        count: group.count,
        items: group.items
          .filter((item) => item && typeof item === 'object')
          .filter((item) => (
            isNonEmptyString(item.sku)
            && isNonEmptyString(item.product)
            && isNonEmptyString(item.presentation)
            && isNonEmptyString(item.available)
            && /^\d+(?:\.\d+)?$/.test(item.available)
            && isNonEmptyString(item.updatedAt)
            && (
              item.priceMxn === undefined
              || (isNonEmptyString(item.priceMxn) && /^\d+(?:\.\d+)?$/.test(item.priceMxn))
            )
          ))
          .map((item) => ({
            ...cleanInventoryItem(item),
            unit: group.unit.trim(),
          })),
      }))
      .filter((group) => group.items.length > 0);
    if (groups.length) {
      return completeResult({
        status: 'inventory_list',
        groups,
        priceRequested: inventoryPayload.priceRequested === true,
      });
    }
    throw new Error('La lista de inventario no contiene productos válidos.');
  }

  if (
    inventoryPayload.status === 'ranking'
    && Number.isInteger(inventoryPayload.limit)
    && inventoryPayload.limit >= 1
    && inventoryPayload.limit <= 50
    && Array.isArray(inventoryPayload.groups)
  ) {
    const groups = inventoryPayload.groups
      .filter((group) => group && typeof group === 'object')
      .filter((group) => isNonEmptyString(group.unit) && Array.isArray(group.items))
      .map((group) => ({
        unit: group.unit.trim(),
        items: group.items
          .filter((item) => item && typeof item === 'object')
          .filter((item) => (
            isNonEmptyString(item.sku)
            && isNonEmptyString(item.product)
            && isNonEmptyString(item.presentation)
            && isNonEmptyString(item.available)
            && /^\d+(?:\.\d+)?$/.test(item.available)
            && isNonEmptyString(item.unit)
            && isNonEmptyString(item.updatedAt)
            && (
              item.priceMxn === undefined
              || (isNonEmptyString(item.priceMxn) && /^\d+(?:\.\d+)?$/.test(item.priceMxn))
            )
          ))
          .map(cleanInventoryItem),
      }))
      .filter((group) => group.items.length > 0);
    if (groups.length) {
      return completeResult({
        status: 'ranking',
        limit: inventoryPayload.limit,
        rankingBy: inventoryPayload.rankingBy === 'price' ? 'price' : 'stock',
        groups,
        priceRequested: inventoryPayload.priceRequested === true,
      });
    }
    throw new Error('El ranking de inventario no contiene productos válidos.');
  }

  if (
    ['ambiguous', 'closest_match'].includes(inventoryPayload.status)
    && Array.isArray(inventoryPayload.candidates)
  ) {
    const candidates = inventoryPayload.candidates
      .filter((candidate) => candidate && typeof candidate === 'object')
      .filter((candidate) => (
        isNonEmptyString(candidate.sku)
        && isNonEmptyString(candidate.product)
        && isNonEmptyString(candidate.presentation)
        && isNonEmptyString(candidate.available)
        && /^\d+(?:\.\d+)?$/.test(candidate.available)
        && isNonEmptyString(candidate.unit)
        && isNonEmptyString(candidate.updatedAt)
        && (
          candidate.priceMxn === undefined
          || (isNonEmptyString(candidate.priceMxn) && /^\d+(?:\.\d+)?$/.test(candidate.priceMxn))
        )
      ))
      .slice(0, 10)
      .map(cleanInventoryItem);
    if (candidates.length) {
      return completeResult({
        status: inventoryPayload.status,
        candidates,
        priceRequested: inventoryPayload.priceRequested === true,
      });
    }
  }

  if (
    ['found', 'closest_match'].includes(inventoryPayload.status)
    && inventoryPayload.item
    && typeof inventoryPayload.item === 'object'
    && isNonEmptyString(inventoryPayload.item.sku)
    && isNonEmptyString(inventoryPayload.item.product)
    && isNonEmptyString(inventoryPayload.item.presentation)
    && isNonEmptyString(inventoryPayload.item.available)
    && /^\d+(?:\.\d+)?$/.test(inventoryPayload.item.available)
    && isNonEmptyString(inventoryPayload.item.unit)
    && isNonEmptyString(inventoryPayload.item.updatedAt)
    && (
      inventoryPayload.item.priceMxn === undefined
      || (
        isNonEmptyString(inventoryPayload.item.priceMxn)
        && /^\d+(?:\.\d+)?$/.test(inventoryPayload.item.priceMxn)
      )
    )
  ) {
    const requestedFields = readRequestedFields(inventoryPayload);
    return completeResult({
      status: inventoryPayload.status,
      item: cleanInventoryItem(inventoryPayload.item),
      priceRequested: inventoryPayload.priceRequested === true,
      ...(requestedFields.length ? { requestedFields } : {}),
    });
  }

  throw new Error('El inventario devolvió datos con un formato no válido.');
}

export async function queryInventory(query, accessToken) {
  return requestInventory(query, accessToken, '/api/inventory/query');
}

export async function chatInventory(query, accessToken, sessionId) {
  return requestInventory(query, accessToken, '/api/inventory/chat', sessionId);
}
